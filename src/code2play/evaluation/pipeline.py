"""Resumable D1-D4 evaluation for one locked candidate artifact."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import time
import traceback
from typing import Any, Callable

from code2play.execution.candidate_project import CandidateProject

from code2play.evaluation.dimensions.d1.dimension1_executable import evaluate_dimension1
from code2play.evaluation.dimensions.d2 import evaluate_dimension2
from code2play.evaluation.dimensions.d3 import CONFIG_PATH as DEFAULT_D3_CONFIG
from code2play.evaluation.dimensions.d3 import evaluate_d3
from code2play.evaluation.dimensions.d4.semantic_ux import evaluate_dimension4_semantic
from code2play.d4.contracts import (
    assert_round_contract_manifest,
    load_round_contract,
)
from code2play.d4.questions import (
    QUESTION_PACK_DESIGN_VERSION,
    QUESTION_REVIEW_POLICY,
    build_d43_question_pack_single_pass,
)
from code2play.providers.dashscope import JudgeAttemptsExhausted, JudgeRouter
from code2play.execution.protocol_sampling import sample_evaluation_protocol
from code2play.config.project import GameConfig, load_config, normalized_policy_sha256
from code2play.generation.prompt_builder import load_spec
from code2play.execution.protocol_policy import runtime_protocol_descriptor
from code2play.execution.safe_artifacts import redact_text, write_json
from code2play.evaluation.scoring import assemble_result


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _judge_failure_detail(
    stage: str,
    exc: JudgeAttemptsExhausted,
) -> dict[str, Any]:
    return {
        "failure_origin": "judge_or_transport",
        "candidate_failure_proven": False,
        "failure_stage": stage,
        "retryable_stage": stage,
        "error_type": exc.error_type,
        "message": redact_text(exc.error_message),
        **exc.to_dict(),
    }


def _judge_gap_payload(
    stage: str,
    exc: JudgeAttemptsExhausted,
) -> dict[str, Any]:
    return {
        "status": "judge_output_unavailable",
        "candidate_failure_proven": False,
        "judge_failure": _judge_failure_detail(stage, exc),
    }


def _d2_judge_gap_payload(judge_failure: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "judge_output_unavailable",
        "passed": None,
        "total": None,
        "score": None,
        "criteria_scores": {},
        "reasons": {},
        "evidence": {
            "status": "judge_output_unavailable",
            "candidate_failure_proven": False,
            "judge_failure": judge_failure,
        },
        "specialized_items": {},
        "candidate_failure_proven": False,
        "judge_failure": judge_failure,
    }


def _require_project_hash(project: CandidateProject, expected: str, stage: str) -> None:
    actual = project.project_sha256()
    if actual != expected:
        raise ValueError(
            f"Candidate project changed before {stage}: expected {expected}, got {actual}"
        )


def _write_state(path: Path, state: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    write_json(temporary, state)
    for attempt in range(8):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(min(0.05 * (2**attempt), 0.5))


def _run_stage(
    *,
    name: str,
    state: dict[str, Any],
    state_path: Path,
    output_path: Path,
    operation: Callable[[int], dict[str, Any]],
) -> dict[str, Any]:
    record = state.setdefault("stages", {}).setdefault(name, {})
    if record.get("status") == "completed" and output_path.is_file():
        existing = _read_json(output_path)
        if existing.get("status") not in {
            "judge_output_unavailable",
            "completed_with_judge_gap",
            "needs_rescore",
        }:
            return existing

    attempt = int(record.get("attempts", 0)) + 1
    for key in ("error", "error_type", "judge_failure"):
        record.pop(key, None)
    record.update(
        {
            "status": "running",
            "attempts": attempt,
            "started_at": utc_now(),
            "output": str(output_path),
        }
    )
    state["active_stage"] = name
    _write_state(state_path, state)
    try:
        payload = operation(attempt)
        write_json(output_path, payload)
    except BaseException as exc:
        record.update(
            {
                "status": "failed",
                "finished_at": utc_now(),
                "error_type": type(exc).__name__,
                "error": redact_text(str(exc)),
            }
        )
        state["status"] = "failed"
        _write_state(state_path, state)
        error_path = output_path.parent / f"{name}_error_attempt_{attempt:03d}.json"
        write_json(
            error_path,
            {
                "stage": name,
                "attempt": attempt,
                "error_type": type(exc).__name__,
                "error": redact_text(str(exc)),
                "traceback": redact_text(traceback.format_exc()),
                "timestamp": utc_now(),
            },
        )
        raise
    for key in ("error", "error_type", "judge_failure"):
        record.pop(key, None)
    retryable_gap = payload.get("status") in {
        "judge_output_unavailable",
        "completed_with_judge_gap",
        "needs_rescore",
    }
    record.update(
        {
            "status": "needs_rescore" if retryable_gap else "completed",
            "finished_at": utc_now(),
        }
    )
    judge_failure = payload.get("judge_failure")
    if retryable_gap and isinstance(judge_failure, dict):
        record["judge_failure"] = judge_failure
    state["status"] = "running"
    state["active_stage"] = None
    _write_state(state_path, state)
    return payload


def _d3_call(
    *,
    project: CandidateProject,
    evidence_dir: Path,
    region: str,
    judge_config: dict[str, Any],
    judge: Any,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "project": project,
        "run_dir": evidence_dir,
        "region": region,
        "config_path": DEFAULT_D3_CONFIG,
        "include_judges": True,
    }
    if "semantic_judge" in inspect.signature(evaluate_d3).parameters:
        kwargs["semantic_judge"] = judge
    result, tools = evaluate_d3(**kwargs)
    return {"result": result, "tools": tools}


def evaluate_candidate(
    *,
    game: GameConfig,
    model_id: str,
    repetition: int,
    project: CandidateProject | str | Path,
    task_dir: str | Path,
    region: str = "us-east-1",
    judge_config: dict[str, Any] | None = None,
    d2_workers: int = 4,
    sampling_timeout_seconds: int = 45,
    runtime_protocol: dict[str, Any] | None = None,
    experimental_single_model: str | None = None,
    round_dir: str | Path | None = None,
    contract_manifest_sha256: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate one immutable candidate project at resumable stage boundaries."""
    candidate = project if isinstance(project, CandidateProject) else CandidateProject(project)
    task_root = Path(task_dir).resolve()
    evaluation_dir = task_root / "evaluation"
    evaluation_dir.mkdir(parents=True, exist_ok=True)
    state_path = evaluation_dir / "stage_state.json"
    project_hash = candidate.project_sha256()
    active_config = dict(config) if config is not None else load_config()
    active_judge_config = (
        dict(judge_config) if judge_config is not None else dict(active_config["judge"])
    )
    active_runtime_protocol = (
        dict(runtime_protocol)
        if runtime_protocol is not None
        else runtime_protocol_descriptor()
    )
    router = JudgeRouter(active_judge_config, evaluation_dir / "model_calls")
    routed_judge = router.scoring()
    d4_contract: dict[str, Any] | None = None
    d4_contract_path: Path | None = None
    spec = load_spec(game.spec)
    if game.d4_configured:
        if round_dir is None:
            raise ValueError(f"{game.slug}: a locked D4 round directory is required")
        if contract_manifest_sha256 is None:
            raise ValueError(f"{game.slug}: a locked D4 manifest hash is required")
        assert_round_contract_manifest(round_dir, contract_manifest_sha256)
        d4_contract = load_round_contract(
            round_dir,
            game.slug,
            expected_manifest_sha256=contract_manifest_sha256,
            d2_checkpoints=spec["evaluation"]["d2"]["checkpoints"],
        )
        d4_contract_path = Path(round_dir).resolve() / "contracts" / f"{game.slug}.json"
    evaluation_policy = {
        "judge": active_judge_config,
        "judge_policy": "optimized_qwen_single_pass_v1",
        "d1_gate_mode": "contribution_only",
        "protocol_version": 4,
        "runtime_protocol": active_runtime_protocol,
        "d4_contract": (
            {
                "round_id": d4_contract.get("round_id"),
                "version": d4_contract["contract_version"],
                "design_version": d4_contract["design_version"],
                "sha256": d4_contract["contract_sha256"],
                "file_sha256": sha256_file(d4_contract_path),
                "manifest_sha256": contract_manifest_sha256,
                "runtime_question_design_version": (
                    QUESTION_PACK_DESIGN_VERSION
                ),
                "runtime_question_review_policy": QUESTION_REVIEW_POLICY,
            }
            if d4_contract is not None
            else None
        ),
        "experimental_single_model": experimental_single_model,
        "normalized_config_sha256": normalized_policy_sha256(active_config),
    }
    if state_path.is_file():
        state = _read_json(state_path)
        locked = state.get("candidate_project_sha256")
        if locked and locked != project_hash:
            raise ValueError(
                "Candidate project changed after evaluation state was created"
            )
        if state.get("evaluation_policy") != evaluation_policy:
            raise ValueError(
                "Evaluation evidence belongs to a different round or Judge policy; use a new task directory"
            )
    else:
        state = {
            "schema_version": 1,
            "status": "running",
            "active_stage": None,
            "candidate_project_sha256": project_hash,
            "round_id": d4_contract.get("round_id") if d4_contract else None,
            "contract_manifest_sha256": contract_manifest_sha256,
            "evaluation_policy": evaluation_policy,
            "created_at": utc_now(),
            "stages": {},
        }
        _write_state(state_path, state)

    def finish(result: dict[str, Any]) -> dict[str, Any]:
        result["evaluation_policy"] = evaluation_policy
        write_json(task_root / "summary.json", result)
        state.update(
            {
                "status": result["status"],
                "active_stage": None,
                "finished_at": utc_now(),
                "official_total": result["official_total"],
            }
        )
        for key in ("error", "error_type", "failed_at", "failed_stage"):
            state.pop(key, None)
        _write_state(state_path, state)
        return result

    d1_payload = _run_stage(
        name="D1",
        state=state,
        state_path=state_path,
        output_path=evaluation_dir / "d1.json",
        operation=lambda _attempt: (
            _require_project_hash(candidate, project_hash, "D1")
            or evaluate_dimension1(project=candidate)
        ),
    )

    def run_d3(attempt: int) -> dict[str, Any]:
        _require_project_hash(candidate, project_hash, "D3")
        evidence = evaluation_dir / "d3_evidence" / f"attempt_{attempt:03d}"
        evidence.mkdir(parents=True, exist_ok=True)
        return _d3_call(
            project=candidate,
            evidence_dir=evidence,
            region=region,
            judge_config=active_judge_config,
            judge=router.for_role("code_quality"),
        )

    d3_bundle = _run_stage(
        name="D3",
        state=state,
        state_path=state_path,
        output_path=evaluation_dir / "d3.json",
        operation=run_d3,
    )
    d3_payload = d3_bundle["result"]

    # D1 gates official score contributions, not measurement. D2-D4 still run
    # for diagnosis whenever the candidate protocol can produce valid evidence.
    def run_sampling(attempt: int) -> dict[str, Any]:
        _require_project_hash(candidate, project_hash, "D2 sampling")
        evidence = evaluation_dir / "semantic_evidence" / f"sampling_attempt_{attempt:03d}"
        compiler = router.for_role("action_compiler")
        try:
            return sample_evaluation_protocol(
                project=candidate,
                spec_path=game.spec,
                evidence_dir=evidence,
                timeout_sec=sampling_timeout_seconds,
                d2_max_workers=d2_workers,
                checkpoint_compiler=compiler,
            )
        except JudgeAttemptsExhausted as exc:
            return _judge_gap_payload("sampling", exc)

    sample_manifest = _run_stage(
        name="sampling",
        state=state,
        state_path=state_path,
        output_path=evaluation_dir / "sample_manifest.json",
        operation=run_sampling,
    )

    if sample_manifest.get("status") == "judge_output_unavailable":
        judge_failure = sample_manifest.get("judge_failure")
        if not isinstance(judge_failure, dict):
            raise ValueError("Sampling judge gap is missing failure metadata")
        partial = assemble_result(
            game=game.slug,
            model=model_id,
            repetition=repetition,
            candidate_project_sha256=project_hash,
            d4_configured=game.d4_configured,
            d1_detail=d1_payload,
            d2_detail=_d2_judge_gap_payload(judge_failure),
            d3_detail=d3_payload,
            d4_detail=None,
        )
        partial["failure_semantics"] = (
            "Evaluator-side sampling Judge attempts were exhausted; completed "
            "D1/D3 evidence is retained and only sampling will be retried."
        )
        return finish(partial)

    def run_d2(attempt: int) -> dict[str, Any]:
        _require_project_hash(candidate, project_hash, "D2")
        judge = routed_judge
        try:
            result = evaluate_dimension2(
                game_id=game.slug,
                project=candidate,
                spec_path=game.spec,
                sample_manifest=sample_manifest,
                judge=judge,
            )
        except JudgeAttemptsExhausted as exc:
            return _d2_judge_gap_payload(_judge_failure_detail("D2", exc))
        payload = result.to_dict()
        payload["status"] = str(result.evidence.get("status", "completed"))
        return payload

    d2_payload = _run_stage(
        name="D2",
        state=state,
        state_path=state_path,
        output_path=evaluation_dir / "d2.json",
        operation=run_d2,
    )

    d4_payload: dict[str, Any] | None = None
    try:
        if game.d4_configured:
            assert d4_contract is not None
            assert d4_contract_path is not None

            d4_sample_manifest = {
                **sample_manifest,
                "d4_contract_source": "round_locked_manifest",
                "d4_contract_path": str(d4_contract_path.resolve()),
                "d4_contract_version": d4_contract["contract_version"],
                "d4_contract_sha256": d4_contract["contract_sha256"],
                "d4_contract_design_version": d4_contract["design_version"],
                "d4_contract_manifest_sha256": contract_manifest_sha256,
                "d4_compiler": "reused_functionality_compiled_programs",
                "d4_2_checkpoint_selection": "kind_dynamic_only",
                "candidate_received_d4_task_ids": False,
                "candidate_received_d4_contract": False,
            }
            write_json(evaluation_dir / "d4_sample_manifest.json", d4_sample_manifest)

            def run_d4_questions(attempt: int) -> dict[str, Any]:
                _require_project_hash(candidate, project_hash, "D4 questions")
                return build_d43_question_pack_single_pass(
                    d4_contract=d4_contract,
                    d2_checkpoints=spec["evaluation"]["d2"]["checkpoints"],
                    sample_manifest=d4_sample_manifest,
                    candidate_project_sha256=project_hash,
                    generator=router.for_role("question_generation"),
                )

            d4_question_pack = _run_stage(
                name="D4_questions",
                state=state,
                state_path=state_path,
                output_path=evaluation_dir / "d4_question_pack.json",
                operation=run_d4_questions,
            )

            def run_d4(attempt: int) -> dict[str, Any]:
                _require_project_hash(candidate, project_hash, "D4")
                judge = routed_judge
                previous_path = evaluation_dir / "d4.json"
                previous_detail = (
                    _read_json(previous_path) if previous_path.is_file() else None
                )
                return evaluate_dimension4_semantic(
                    spec_path=game.spec,
                    d4_contract=d4_contract,
                    contract_path=d4_contract_path,
                    sample_manifest=d4_sample_manifest,
                    question_pack=d4_question_pack,
                    candidate_project_sha256=project_hash,
                    judge=judge,
                    previous_detail=previous_detail,
                )

            d4_payload = _run_stage(
                name="D4",
                state=state,
                state_path=state_path,
                output_path=evaluation_dir / "d4.json",
                operation=run_d4,
            )
    except BaseException:
        partial = assemble_result(
            game=game.slug,
            model=model_id,
            repetition=repetition,
            candidate_project_sha256=project_hash,
            d4_configured=game.d4_configured,
            d1_detail=d1_payload,
            d2_detail=d2_payload,
            d3_detail=d3_payload,
            d4_detail=None,
        )
        partial["status"] = "failed"
        partial["failure_semantics"] = (
            "D4 evaluator/API/contract compilation failure; D4 remains null and "
            "the failed stage is resumable"
        )
        partial["evaluation_policy"] = evaluation_policy
        write_json(task_root / "summary.json", partial)
        raise

    result = assemble_result(
        game=game.slug,
        model=model_id,
        repetition=repetition,
        candidate_project_sha256=project_hash,
        d4_configured=game.d4_configured,
        d1_detail=d1_payload,
        d2_detail=d2_payload,
        d3_detail=d3_payload,
        d4_detail=d4_payload,
    )
    return finish(result)
