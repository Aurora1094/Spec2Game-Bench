"""Four-call staged-project candidate generation and resumable evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
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
from code2play.providers.dashscope import GenerationResult, generate_stage_source
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


def _stage_config(generation_config: Mapping[str, Any], stage: str) -> dict[str, Any]:
    stages = generation_config.get("stages")
    if not isinstance(stages, list):
        raise ValueError("generation.stages must be a list")
    matches = [item for item in stages if isinstance(item, Mapping) and item.get("id") == stage]
    if len(matches) != 1:
        raise ValueError(f"generation stage {stage!r} must appear exactly once")
    return dict(matches[0])


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
    progress: Callable[[str], None] = print,
    generate: Callable[..., GenerationResult] = generate_stage_source,
) -> CandidateProject:
    """Generate and lock all four files; code diagnostics never trigger retries."""

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
        stage_policy = _stage_config(generation_config, stage)
        started = time.perf_counter()
        try:
            generated = generate(
                model,
                prompt.text,
                region=str(config["region"]),
                max_output_tokens=int(stage_policy["max_output_tokens"]),
                temperature=float(generation_config["temperature"]),
                attempts=int(generation_config["attempts"]),
                retry_delays_seconds=list(generation_config["retry_delays_seconds"]),
            )
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
        _write_call_artifacts(stage_dir, prompt, generated)
        source = generated.code.lstrip("\ufeff")
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
        ).to_dict()
        write_json(stage_dir / "stage_result.json", result)
        completed.append(result)
        status = "diagnostic" if not diagnostics["syntax_valid"] or generated.truncated else "ok"
        progress(f"[generated] {game.slug}/{model.id} {stage} {status}")

    project.assert_safe_structure()
    validation = project.validate().to_dict()
    file_hashes = project.file_hashes()
    project_hash = project.project_sha256()
    totals = {
        key: sum(int(item.get(key) or 0) for item in completed)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
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
            "schema_version": 1,
            "status": "completed",
            "protocol": "staged_project_v1",
            "project_sha256": project_hash,
            "generation_contract_sha256": generation_contract,
            "stage_order": list(STAGE_ORDER),
            "stages": completed,
            "usage_totals": totals,
            "validation": validation,
        },
    )
    return project


__all__ = ["STAGE_ORDER", "StageResult", "generate_candidate_project"]
