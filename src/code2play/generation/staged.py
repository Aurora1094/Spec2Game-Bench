"""Four-call staged-project candidate generation and resumable evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import inspect
import json
import re
from pathlib import Path
import time
from typing import Any, Callable, Mapping

from code2play.execution.candidate_project import (
    CandidateProject,
    STAGE_TARGETS,
    diagnose_stage_source,
    initialize_candidate_project,
)
from code2play.providers.dashscope import (
    GenerationNeedsRegeneration,
    GenerationResult,
    generate_stage_source,
    generation_output_issues,
)
from code2play.config.project import GameConfig, ModelConfig
from code2play.generation.prompt_builder import StagePrompt, build_stage_prompt
from code2play.execution.safe_artifacts import redact_text, write_json


STAGE_ORDER = tuple(STAGE_TARGETS)
CODE_BLOCK_PATTERN = re.compile(
    r"```(?:python|py)?\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE
)


@dataclass(frozen=True)
class StageResult:
    schema_version: int
    stage: str
    target: str
    source_sha256: str
    stage_prompt_sha256: str
    generation_contract_sha256: str
    injected_dependency_hashes: dict[str, str]
    finish_reason: str | None
    truncated: bool
    format_valid: bool
    python_block_count: int
    diagnostics: dict[str, Any]
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    elapsed_seconds: float
    provider: str
    requested_model: str
    response_model: str
    request_id: str | None
    attempts: int
    attempt_history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _usage_value(usage: Mapping[str, Any] | None, *names: str) -> int | None:
    if not isinstance(usage, Mapping):
        return None
    for name in names:
        value = usage.get(name)
        if isinstance(value, int) and not isinstance(value, bool):
            return value
    return None


def _format_diagnostics(text: str) -> tuple[bool, int]:
    blocks = list(CODE_BLOCK_PATTERN.finditer(text))
    if len(blocks) != 1:
        return False, len(blocks)
    outside = (text[: blocks[0].start()] + text[blocks[0].end() :]).strip()
    return not outside, 1


def _attempt_summary(item: Mapping[str, Any]) -> dict[str, Any]:
    """Keep stage summaries small while retaining every retry diagnostic."""

    return {
        key: item.get(key)
        for key in (
            "attempt",
            "finish_reason",
            "usage",
            "request_id",
            "output_sha256",
            "truncated",
            "reasons",
            "error_type",
            "error",
        )
        if key in item
    }


def _generation_attempts(
    generated: GenerationResult,
) -> list[dict[str, Any]]:
    history = [dict(item) for item in generated.attempt_history]
    if history:
        return history
    return [
        {
            "attempt": generated.attempts,
            "finish_reason": generated.finish_reason,
            "usage": generated.usage,
            "request_id": generated.request_id,
            "output_sha256": hashlib.sha256(
                generated.text.encode("utf-8")
            ).hexdigest(),
            "truncated": generated.truncated,
            "reasons": generation_output_issues(generated),
            "text": generated.text,
            "code": generated.code,
            "raw_response": generated.raw_response,
            "request_parameters": generated.request_parameters,
        }
    ]


def _next_generation_cycle(stage_dir: Path) -> int:
    attempts_root = stage_dir / "attempts"
    existing: list[int] = []
    if attempts_root.is_dir():
        for path in attempts_root.glob("cycle_*"):
            try:
                existing.append(int(path.name.removeprefix("cycle_")))
            except ValueError:
                continue
    return max(existing, default=0) + 1


def _load_generation_failure(task_root: Path) -> dict[str, Any] | None:
    failure_path = task_root / "generation_failure.json"
    if not failure_path.is_file():
        return None
    try:
        value = json.loads(failure_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, Mapping):
        return None
    failure = value.get("failure")
    return dict(failure) if isinstance(failure, Mapping) else None


def _raise_generation_resume_required(task_root: Path) -> None:
    failure = _load_generation_failure(task_root)
    if failure is None:
        return
    attempts = failure.get("attempts")
    history = [dict(item) for item in attempts if isinstance(item, Mapping)] if isinstance(attempts, list) else []
    try:
        attempts_made = int(failure.get("attempts_made") or failure.get("attempt_limit") or len(history) or 2)
    except (TypeError, ValueError):
        attempts_made = len(history) or 2
    stage = str(failure.get("stage") or "unknown")
    message = str(failure.get("error") or "generation output is incomplete")
    raise GenerationNeedsRegeneration(
        stage=stage,
        attempts=attempts_made,
        attempt_history=history,
        error=ValueError(
            f"{message}; pass --resume-generation to retry the failed generation stage"
        ),
    )


def _write_generation_attempt_artifacts(
    *,
    stage_dir: Path,
    prompt: StagePrompt,
    attempts: list[Mapping[str, Any]],
    cycle: int,
    fallback_error: BaseException | None = None,
) -> None:
    """Persist each response before any response can become a candidate file."""

    cycle_dir = stage_dir / "attempts" / f"cycle_{cycle:03d}"
    cycle_dir.mkdir(parents=True, exist_ok=True)
    if not attempts and fallback_error is not None:
        attempts = [
            {
                "attempt": 1,
                "finish_reason": None,
                "usage": None,
                "output_sha256": None,
                "truncated": False,
                "reasons": ["generation_exception"],
                "error_type": type(fallback_error).__name__,
                "error": redact_text(str(fallback_error)),
                "text": "",
                "code": "",
                "raw_response": {},
                "request_parameters": {},
            }
        ]
    for index, raw_item in enumerate(attempts, 1):
        item = dict(raw_item)
        attempt_number = int(item.get("attempt", index) or index)
        attempt_dir = cycle_dir / f"attempt_{attempt_number:03d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        (attempt_dir / "prompt.md").write_text(
            prompt.text, encoding="utf-8", newline="\n"
        )
        text = str(item.get("text", ""))
        code = str(item.get("code", ""))
        (attempt_dir / "raw_output.txt").write_text(
            text, encoding="utf-8", newline="\n"
        )
        (attempt_dir / "extracted_source.py").write_text(
            code, encoding="utf-8", newline="\n"
        )
        write_json(attempt_dir / "raw_response.json", item.get("raw_response", {}))
        write_json(
            attempt_dir / "diagnostic.json",
            {
                **_attempt_summary(item),
                "stage": prompt.stage,
                "target": prompt.target_file,
            },
        )
        write_json(
            attempt_dir / "call_metadata.json",
            {
                "provider": item.get("provider"),
                "requested_model": item.get("requested_model"),
                "response_model": item.get("response_model"),
                "usage": item.get("usage"),
                "request_id": item.get("request_id"),
                "finish_reason": item.get("finish_reason"),
                "truncated": item.get("truncated", False),
                "request_parameters": item.get("request_parameters", {}),
                "credentials_saved": False,
            },
        )
        write_json(attempt_dir / "attempt.json", _attempt_summary(item))


def _generation_summary(
    *,
    task_root: Path,
    generation_contract: str | None,
    completed: list[dict[str, Any]],
    status: str,
    failed_stage: str | None = None,
    failure: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    totals = {
        key: sum(int(item.get(key) or 0) for item in completed)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": status,
        "protocol": "staged_project_v1",
        "generation_contract_sha256": generation_contract,
        "stage_order": list(STAGE_ORDER),
        "stages": completed,
        "usage_totals": totals,
    }
    if failed_stage is not None:
        payload["failed_stage"] = failed_stage
    if failure is not None:
        payload["generation_failure"] = dict(failure)
    return payload


def _call_generator(
    generate: Callable[..., GenerationResult],
    model: ModelConfig,
    prompt: StagePrompt,
    *,
    config: Mapping[str, Any],
    stage_policy: Mapping[str, Any],
    generation_config: Mapping[str, Any],
    stage: str,
) -> GenerationResult:
    """Pass new completeness hooks without breaking narrow test doubles."""

    kwargs: dict[str, Any] = {
        "region": str(config["region"]),
        "max_output_tokens": int(stage_policy["max_output_tokens"]),
        "temperature": float(generation_config["temperature"]),
        "attempts": int(generation_config["attempts"]),
        "retry_delays_seconds": list(generation_config["retry_delays_seconds"]),
    }
    optional = {
        "stage": stage,
        "stop_on_truncation": bool(generation_config.get("stop_on_truncation", False)),
        "result_validator": lambda result: generation_output_issues(
            result, stage=stage
        ),
    }
    try:
        signature = inspect.signature(generate)
        accepts_kwargs = any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
        for name, value in optional.items():
            if accepts_kwargs or name in signature.parameters:
                kwargs[name] = value
    except (TypeError, ValueError):
        kwargs.update(optional)
    return generate(model, prompt.text, **kwargs)


def _stage_config(
    generation_config: Mapping[str, Any],
    stage: str,
    difficulty: str = "",
) -> dict[str, Any]:
    stages = generation_config.get("stages")
    if not isinstance(stages, list):
        raise ValueError("generation.stages must be a list")
    matches = [item for item in stages if isinstance(item, Mapping) and item.get("id") == stage]
    if len(matches) != 1:
        raise ValueError(f"generation stage {stage!r} must appear exactly once")
    result = dict(matches[0])
    if difficulty != "hard":
        return result
    overrides = generation_config.get("difficulty_overrides")
    hard = overrides.get("hard") if isinstance(overrides, Mapping) else None
    hard_stages = hard.get("stages") if isinstance(hard, Mapping) else None
    if not isinstance(hard_stages, list):
        return result
    hard_matches = [
        item for item in hard_stages if isinstance(item, Mapping) and item.get("id") == stage
    ]
    if len(hard_matches) != 1:
        return result
    tokens = hard_matches[0].get("max_output_tokens")
    if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens > 0:
        result["max_output_tokens"] = tokens
    return result


def _write_call_artifacts(
    stage_dir: Path,
    prompt: StagePrompt,
    generated: GenerationResult,
) -> None:
    stage_dir.mkdir(parents=True, exist_ok=True)
    (stage_dir / "prompt.md").write_text(prompt.text, encoding="utf-8", newline="\n")
    (stage_dir / "model_output.txt").write_text(
        generated.text, encoding="utf-8", newline="\n"
    )
    write_json(stage_dir / "raw_response.json", generated.raw_response)
    write_json(
        stage_dir / "call_metadata.json",
        {
            "provider": generated.provider,
            "requested_model": generated.requested_model,
            "response_model": generated.response_model,
            "usage": generated.usage,
            "request_id": generated.request_id,
            "attempts": generated.attempts,
            "request_parameters": generated.request_parameters,
            "finish_reason": generated.finish_reason,
            "truncated": generated.truncated,
            "credentials_saved": False,
        },
    )


def _load_completed_stage(
    *,
    stage: str,
    stage_dir: Path,
    target_path: Path,
    prompt: StagePrompt,
) -> dict[str, Any] | None:
    result_path = stage_dir / "stage_result.json"
    if not result_path.is_file():
        if target_path.exists():
            raise ValueError(
                f"{stage} target exists without locked stage_result.json; refusing overwrite"
            )
        return None
    import json

    value = json.loads(result_path.read_text(encoding="utf-8"))
    extracted_path = stage_dir / "extracted_source.py"
    if not target_path.is_file() or target_path.is_symlink():
        raise ValueError(f"locked {stage} source is missing or unsafe")
    if not extracted_path.is_file() or extracted_path.is_symlink():
        raise ValueError(f"locked {stage} extracted source evidence is missing or unsafe")
    if value.get("source_sha256") != _sha256_file(target_path):
        raise ValueError(f"locked {stage} source changed after generation")
    if _sha256_file(extracted_path) != _sha256_file(target_path):
        raise ValueError(f"locked {stage} extracted source differs from candidate file")
    if value.get("stage_prompt_sha256") != prompt.sha256:
        raise ValueError(f"locked {stage} prompt changed after generation")
    if value.get("generation_contract_sha256") != prompt.generation_contract_sha256:
        raise ValueError(f"locked {stage} generation contract changed")
    if value.get("injected_dependency_hashes") != prompt.injected_dependency_hashes:
        raise ValueError(f"locked {stage} dependency hashes changed")
    return value


def generate_candidate_project(
    *,
    game: GameConfig,
    model: ModelConfig,
    task_dir: Path,
    config: Mapping[str, Any],
    resume: bool,
    resume_generation: bool = False,
    progress: Callable[[str], None] = print,
    generate: Callable[..., GenerationResult] = generate_stage_source,
) -> CandidateProject:
    """Generate and lock all four files after conservative completeness checks."""

    task_root = Path(task_dir).resolve()
    generation_config = config.get("generation")
    if not isinstance(generation_config, Mapping):
        raise ValueError("config.generation must be a mapping")
    project = initialize_candidate_project(task_root / "candidate")
    stages_root = task_root / "generation" / "stages"
    if not resume:
        existing = [
            project.path(filename)
            for filename in STAGE_TARGETS.values()
            if project.path(filename).exists()
        ]
        if existing or stages_root.exists():
            raise ValueError("candidate project already contains generation evidence; use --resume")
    elif not resume_generation:
        _raise_generation_resume_required(task_root)

    completed: list[dict[str, Any]] = []
    generation_contract: str | None = None
    for index, stage in enumerate(STAGE_ORDER, 1):
        prompt = build_stage_prompt(
            game_slug=game.slug,
            stage=stage,  # type: ignore[arg-type]
            locked_project=project if stage != "state" else None,
            generation_config=generation_config,
        )
        if generation_contract is None:
            generation_contract = prompt.generation_contract_sha256
        elif generation_contract != prompt.generation_contract_sha256:
            raise ValueError("stage prompts disagree on generation contract SHA256")
        target_path = project.path(prompt.target_file)
        stage_dir = stages_root / f"{index:02d}_{stage}"
        locked = _load_completed_stage(
            stage=stage,
            stage_dir=stage_dir,
            target_path=target_path,
            prompt=prompt,
        )
        if locked is not None:
            completed.append(locked)
            progress(f"[locked] {game.slug}/{model.id} {stage}")
            continue

        stage_dir.mkdir(parents=True, exist_ok=True)
        (stage_dir / "prompt.md").write_text(
            prompt.text, encoding="utf-8", newline="\n"
        )
        stage_policy = _stage_config(
            generation_config, stage, difficulty=str(game.difficulty or "")
        )
        started = time.perf_counter()
        cycle = _next_generation_cycle(stage_dir)
        try:
            generated = _call_generator(
                generate,
                model,
                prompt,
                config=config,
                stage_policy=stage_policy,
                generation_config=generation_config,
                stage=stage,
            )
        except GenerationNeedsRegeneration as exc:
            elapsed = round(time.perf_counter() - started, 6)
            attempts = [dict(item) for item in exc.attempt_history]
            _write_generation_attempt_artifacts(
                stage_dir=stage_dir,
                prompt=prompt,
                attempts=attempts,
                cycle=cycle,
                fallback_error=exc,
            )
            failure = {
                **exc.to_dict(),
                "stage": stage,
                "target": prompt.target_file,
                "elapsed_seconds": elapsed,
                "cycle": cycle,
                "generation_contract_sha256": prompt.generation_contract_sha256,
            }
            write_json(stage_dir / "generation_failure.json", failure)
            write_json(
                task_root / "generation_failure.json",
                {"stage": stage, "failure": failure},
            )
            write_json(
                task_root / "generation_summary.json",
                _generation_summary(
                    task_root=task_root,
                    generation_contract=generation_contract,
                    completed=completed,
                    status="needs_regeneration",
                    failed_stage=stage,
                    failure=failure,
                ),
            )
            progress(
                f"[needs_regeneration] {game.slug}/{model.id} {stage} "
                f"attempts={exc.attempts_made}"
            )
            raise
        except BaseException as exc:
            write_json(
                stage_dir / "transport_failure.json",
                {
                    "stage": stage,
                    "type": type(exc).__name__,
                    "message": redact_text(str(exc)),
                    "elapsed_seconds": round(time.perf_counter() - started, 6),
                },
            )
            raise
        elapsed = round(time.perf_counter() - started, 6)
        attempts = _generation_attempts(generated)
        _write_generation_attempt_artifacts(
            stage_dir=stage_dir,
            prompt=prompt,
            attempts=attempts,
            cycle=cycle,
        )
        completeness_issues = generation_output_issues(generated, stage=stage)
        if bool(generation_config.get("stop_on_truncation", False)) and completeness_issues:
            failure = GenerationNeedsRegeneration(
                stage=stage,
                attempts=int(generated.attempts),
                attempt_history=attempts,
                error=ValueError("; ".join(completeness_issues)),
            )
            failure_payload = {
                **failure.to_dict(),
                "stage": stage,
                "target": prompt.target_file,
                "elapsed_seconds": elapsed,
                "cycle": cycle,
                "generation_contract_sha256": prompt.generation_contract_sha256,
            }
            write_json(stage_dir / "generation_failure.json", failure_payload)
            write_json(
                task_root / "generation_failure.json",
                {"stage": stage, "failure": failure_payload},
            )
            write_json(
                task_root / "generation_summary.json",
                _generation_summary(
                    task_root=task_root,
                    generation_contract=generation_contract,
                    completed=completed,
                    status="needs_regeneration",
                    failed_stage=stage,
                    failure=failure_payload,
                ),
            )
            progress(
                f"[needs_regeneration] {game.slug}/{model.id} {stage} "
                f"attempts={generated.attempts}"
            )
            raise failure
        _write_call_artifacts(stage_dir, prompt, generated)
        source = generated.code.lstrip("\ufeff")
        # Candidate files are written only after all completeness checks above.
        (stage_dir / "extracted_source.py").write_text(
            source, encoding="utf-8", newline="\n"
        )
        target_path.write_text(source, encoding="utf-8", newline="\n")
        format_valid, block_count = _format_diagnostics(generated.text)
        diagnostics = diagnose_stage_source(stage, source)
        diagnostics["format_valid"] = format_valid
        diagnostics["python_block_count"] = block_count
        diagnostics["empty_source"] = not source.strip()
        result = StageResult(
            schema_version=1,
            stage=stage,
            target=prompt.target_file,
            source_sha256=_sha256_file(target_path),
            stage_prompt_sha256=prompt.sha256,
            generation_contract_sha256=prompt.generation_contract_sha256,
            injected_dependency_hashes=prompt.injected_dependency_hashes,
            finish_reason=generated.finish_reason,
            truncated=generated.truncated,
            format_valid=format_valid,
            python_block_count=block_count,
            diagnostics=diagnostics,
            prompt_tokens=_usage_value(generated.usage, "prompt_tokens", "input_tokens"),
            completion_tokens=_usage_value(
                generated.usage, "completion_tokens", "output_tokens"
            ),
            total_tokens=_usage_value(generated.usage, "total_tokens"),
            elapsed_seconds=elapsed,
            provider=generated.provider,
            requested_model=generated.requested_model,
            response_model=generated.response_model,
            request_id=generated.request_id,
            attempts=generated.attempts,
            attempt_history=[_attempt_summary(item) for item in attempts],
        ).to_dict()
        write_json(stage_dir / "stage_result.json", result)
        completed.append(result)
        status = "diagnostic" if not diagnostics["syntax_valid"] or generated.truncated else "ok"
        progress(f"[generated] {game.slug}/{model.id} {stage} {status}")

    project.assert_safe_structure()
    validation = project.validate().to_dict()
    file_hashes = project.file_hashes()
    project_hash = project.project_sha256()
    manifest = {
        "schema_version": 1,
        "protocol": "staged_project_v1",
        "entrypoint": project.entrypoint,
        "factory": project.factory,
        "files": file_hashes,
        "project_sha256": project_hash,
        "generation_contract_sha256": generation_contract,
        "validation": validation,
    }
    write_json(task_root / "candidate_manifest.json", manifest)
    write_json(
        task_root / "generation_summary.json",
        {
            **_generation_summary(
                task_root=task_root,
                generation_contract=generation_contract,
                completed=completed,
                status="completed",
            ),
            "project_sha256": project_hash,
            "validation": validation,
        },
    )
    previous_failure = task_root / "generation_failure.json"
    if previous_failure.is_file() and resume_generation:
        archive_dir = task_root / "superseded_evidence" / "generation_failures"
        archive_dir.mkdir(parents=True, exist_ok=True)
        stamp = str(int(time.time() * 1_000_000))
        previous_failure.replace(archive_dir / f"generation_failure_{stamp}.json")
    return project


__all__ = [
    "STAGE_ORDER",
    "StageResult",
    "generate_candidate_project",
]
