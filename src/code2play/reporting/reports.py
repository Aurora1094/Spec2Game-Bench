"""Deterministic JSON, CSV, and Markdown reports for Code2Play-Bench.

The reporting layer consumes the current pipeline result schema. Reporting
never invents a score: absent and not-configured values stay
``None``/blank/``—``.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import csv
import json
import math
from pathlib import Path
import statistics
from typing import Any, Iterable, Mapping, Sequence

from code2play.execution.safe_artifacts import redact_text, sanitize


REPORT_SCHEMA_VERSION = 2
JUDGE_POLICY = "openrouter_gpt56_terra_candidate_judge_v1"
JUDGE_MODEL = "openrouter/qwen/qwen3.7-plus"
JUDGE_MODE = "single_valid_response"
JUDGE_TEMPERATURE = 0.0
CSV_FIELDS = (
    "dimension",
    "subdimension",
    "item_id",
    "item",
    "score",
    "max_score",
    "normalized_score",
    "penalty",
    "status",
    "detail",
)

D1_LABELS = {
    "python_syntax_correct": "Python syntax",
    "dependency_initialization_complete": "pygame import and initialization",
    "window_creation": "Window and Surface creation",
    "event_handling_mechanism": "Event polling",
    "short_runtime_stable": "Stable runtime",
    "process_controllability": "Clean QUIT exit",
}
D2_KEYS = ("D2.1", "D2.2", "D2.3", "D2.4", "D2.5")
D3_LABELS = {
    "maintainability": "Maintainability and structure",
    "reliability": "Reliability and defect risk",
    "security": "Safety and task constraints",
    "efficiency": "Efficiency and resource discipline",
    "conformance": "Python conventions and readability",
}
D4_CRITERIA = (
    "composition_and_hierarchy",
    "palette_and_contrast",
    "shape_and_style_consistency",
    "polish",
    "dynamic_presentation",
)
MULTI_RUN_SCORE_FIELDS = (
    "d1_score",
    "d2_score",
    "d3_score",
    "d4_score",
    "final_score",
)


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _jsonable(value.to_dict())
    return str(value)


def _mapping(value: Any) -> dict[str, Any]:
    value = _jsonable(value)
    return value if isinstance(value, dict) else {}


def _first_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        result = _mapping(value)
        if result:
            return result
    return {}


_CURRENT_DIMENSIONS = frozenset({"D1", "D2", "D3", "D4"})
_LEGACY_RESULT_KEYS = frozenset(
    {
        "game_id",
        "model_id",
        "final_score",
        "scores",
        "aggregate",
        "executable",
        "functionality",
        "code_quality",
        "ux",
        "D1",
        "D2",
        "D3",
        "D4",
        "pilot_judge_policy",
    }
)
_LEGACY_MATRIX_KEYS = _LEGACY_RESULT_KEYS - {"final_score"}


def validate_current_report(result: Mapping[str, Any]) -> dict[str, Any]:
    """Reject pre-Code2Play-Bench report shapes at the reporting boundary."""

    normalized = _mapping(result)
    if normalized.get("schema_version") != 1:
        raise ValueError("Report schema_version is not the current version")
    legacy = sorted(set(normalized) & _LEGACY_RESULT_KEYS)
    if legacy:
        raise ValueError("Legacy report fields are not accepted: " + ", ".join(legacy))
    task = _mapping(normalized.get("task"))
    required_task = {"game", "model", "repetition", "candidate_project_sha256"}
    missing_task = sorted(required_task - set(task))
    if missing_task:
        raise ValueError("Current report task is missing: " + ", ".join(missing_task))
    dimensions = _mapping(normalized.get("dimensions"))
    if set(dimensions) != _CURRENT_DIMENSIONS:
        raise ValueError("Current report must contain exactly D1-D4 dimensions")
    if "official_total" not in normalized:
        raise ValueError("Current report is missing official_total")
    evaluation_policy = _mapping(normalized.get("evaluation_policy"))
    if "pilot_judge_policy" in evaluation_policy:
        raise ValueError("Legacy pilot_judge_policy is not accepted")
    if not str(evaluation_policy.get("judge_policy") or "").strip():
        raise ValueError("Current report is missing evaluation_policy.judge_policy")
    if not _mapping(evaluation_policy.get("judge")):
        raise ValueError("Current report is missing evaluation_policy.judge")
    return normalized


def _validate_current_matrix_record(
    record: Mapping[str, Any], *, require_task_id: bool = True
) -> dict[str, Any]:
    normalized = _mapping(record)
    required = {"game", "model", "repetition", "status"}
    if require_task_id:
        required.add("task_id")
    missing = sorted(required - set(normalized))
    if missing:
        raise ValueError("Current matrix record is missing: " + ", ".join(missing))
    legacy = sorted(set(normalized) & _LEGACY_MATRIX_KEYS)
    if legacy:
        raise ValueError("Legacy matrix fields are not accepted: " + ", ".join(legacy))
    return normalized


def _judge_provenance(result: Mapping[str, Any]) -> dict[str, Any]:
    evaluation_policy = _mapping(result.get("evaluation_policy"))
    judge = _mapping(evaluation_policy.get("judge"))
    routes = _mapping(judge.get("routes"))
    routed_models = sorted(
        {
            str(_mapping(route).get("model"))
            for route in routes.values()
            if _mapping(route).get("model")
        }
    )
    return {
        "policy": (
            judge.get("policy")
            or evaluation_policy.get("judge_policy")
            or JUDGE_POLICY
        ),
        "model": " + ".join(routed_models) if routed_models else JUDGE_MODEL,
        "mode": judge.get("aggregation") or JUDGE_MODE,
        "temperature": judge.get("temperature", JUDGE_TEMPERATURE),
    }


def _dimension(result: Mapping[str, Any], key: str) -> dict[str, Any]:
    dimensions = _mapping(result.get("dimensions"))
    return _mapping(dimensions.get(key))


def _number(value: Any) -> float | int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else round(number, 6)


def _ratio(score: Any, maximum: Any) -> float | None:
    score_number = _number(score)
    maximum_number = _number(maximum)
    if score_number is None or maximum_number in (None, 0):
        return None
    return round(float(score_number) / float(maximum_number), 6)


def _row(
    dimension: str,
    subdimension: str,
    item_id: str,
    item: str,
    score: Any,
    maximum: Any,
    *,
    normalized: Any = None,
    penalty: Any = None,
    status: Any = "completed",
    detail: Any = None,
) -> dict[str, Any]:
    score_value = _number(score)
    max_value = _number(maximum)
    normalized_value = _number(normalized)
    if normalized_value is None:
        normalized_value = _ratio(score_value, max_value)
    if detail is None:
        detail_text = ""
    elif isinstance(detail, str):
        detail_text = detail
    else:
        detail_text = json.dumps(_jsonable(detail), ensure_ascii=False, sort_keys=True)
    return {
        "dimension": dimension,
        "subdimension": subdimension,
        "item_id": str(item_id),
        "item": str(item),
        "score": score_value,
        "max_score": max_value,
        "normalized_score": normalized_value,
        "penalty": _number(penalty),
        "status": str(status or "unknown"),
        "detail": detail_text,
    }


def _aggregate_score(dimension: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    score = dimension.get("score")
    maximum: Any = dimension.get("max_score")
    if score is not None and maximum is None:
        maximum = 100
    normalized = dimension.get("score_normalized")
    if normalized is None:
        normalized = _ratio(score, maximum)
    return score, maximum, normalized


def _d1_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    d1 = _dimension(result, "D1")
    detail = _mapping(d1.get("detail")) or d1
    aggregate, maximum, normalized = _aggregate_score(d1)
    status = d1.get("status", "completed" if aggregate is not None else "not_run")
    rows = [_row("D1", "aggregate", "D1", "Deterministic executability", aggregate, maximum, normalized=normalized, status=status)]
    indicators = _mapping(detail.get("indicators"))
    order = detail.get("step_order")
    ordered = [str(item[0] if isinstance(item, (list, tuple)) else item) for item in order] if isinstance(order, list) else list(D1_LABELS)
    for index, key in enumerate(ordered, start=1):
        value = indicators.get(key)
        rows.append(_row("D1", "pipeline_step", f"D1.{index}", D1_LABELS.get(key, key), value, 1, status="completed" if value is not None else status, detail={"indicator": key}))
    return rows


def _d2_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    d2 = _dimension(result, "D2")
    detail = _mapping(d2.get("detail")) or d2
    aggregate, maximum, normalized = _aggregate_score(d2)
    status = d2.get("status") or _mapping(detail.get("evidence")).get("status") or ("completed" if aggregate is not None else "not_run")
    rows = [_row("D2", "aggregate", "D2", "Functional correctness", aggregate, maximum, normalized=normalized, status=status)]
    evidence = _mapping(detail.get("evidence"))
    checkpoints = detail.get("checkpoint_results") or evidence.get("checkpoint_results") or []
    if isinstance(checkpoints, list):
        for checkpoint in checkpoints:
            checkpoint = _mapping(checkpoint)
            if not checkpoint:
                continue
            checkpoint_id = checkpoint.get("id", "checkpoint")
            dimension = str(checkpoint.get("dimension", ""))
            rows.append(_row("D2", dimension, str(checkpoint_id), str(checkpoint.get("item") or checkpoint.get("objective") or checkpoint_id), checkpoint.get("earned", checkpoint.get("score")), checkpoint.get("possible", checkpoint.get("max_score", 2)), status=checkpoint.get("status", "completed"), detail={"kind": checkpoint.get("kind"), "trace_path": checkpoint.get("trace_path"), "component_scores": checkpoint.get("component_scores")}))
    raw = _mapping(detail.get("raw_dimension_scores") or evidence.get("raw_dimension_scores"))
    adjusted = _mapping(detail.get("criteria_scores"))
    penalties = _mapping(detail.get("deviation_penalties_0_to_3") or evidence.get("deviation_penalties_0_to_3"))
    for key in D2_KEYS:
        value = adjusted.get(key)
        raw_value = raw.get(key)
        rows.append(_row("D2", key, f"{key}.required", f"{key} required checkpoint score", raw_value, 1, status="completed" if raw_value is not None else status))
        rows.append(_row("D2", key, f"{key}.penalty", f"{key} specification-deviation penalty", None, None, penalty=penalties.get(key), status="completed" if penalties.get(key) is not None else status, detail={"penalty_scale": "0-3"}))
        rows.append(_row("D2", key, f"{key}.aggregate", f"{key} adjusted score", value, 1, penalty=penalties.get(key), status="completed" if value is not None else status, detail={"required_score": raw_value, "formula": "max(0, required - penalty/3)"}))
    return rows


def _d3_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    d3 = _dimension(result, "D3")
    detail = _mapping(d3.get("detail")) or d3
    aggregate, maximum, normalized = _aggregate_score(d3)
    status = d3.get("status", "completed" if aggregate is not None else "not_run")
    rows = [_row("D3", "aggregate", "D3", "Code quality", aggregate, maximum or 100, normalized=normalized, status=status, detail={"critical_security_risk": detail.get("critical_security_risk"), "cap_applied": detail.get("security_cap_applied", detail.get("cap_applied")), "score_before_security_cap": detail.get("score_before_security_cap")})]
    tools = _mapping(detail.get("tools"))
    tool_scores = _mapping(tools.get("indicator_scores"))
    tool_caps = _mapping(tools.get("indicator_max_scores"))
    tool_percentages = _mapping(tools.get("indicator_percentages"))
    fusion = _mapping(detail.get("fusion"))
    semantic = _mapping(detail.get("semantic_judge"))
    semantic_percentages = _mapping(semantic.get("criterion_scores"))
    semantic_contributions = _mapping(fusion.get("judge_points"))
    fused = _mapping(detail.get("indicator_scores") or fusion.get("indicator_scores"))
    dimension_caps = _mapping(detail.get("indicator_max_scores") or fusion.get("indicator_max_scores"))
    default_tool_caps = {"maintainability": 20, "reliability": 15, "security": 12, "efficiency": 10, "conformance": 13}
    default_semantic_caps = {"maintainability": 10, "reliability": 10, "security": 3, "efficiency": 5, "conformance": 2}
    judge_model = _judge_provenance(result)["model"]
    for key, label in D3_LABELS.items():
        tool_value = tool_scores.get(key)
        tool_cap = tool_caps.get(key, default_tool_caps[key])
        rows.append(_row("D3", key, f"D3.{key}.tool", f"{label} — deterministic tools", tool_value, tool_cap, normalized=tool_percentages.get(key) / 100 if _number(tool_percentages.get(key)) is not None else None, status=tools.get("status", status)))
        semantic_percentage = semantic_percentages.get(key)
        semantic_value = semantic_contributions.get(key)
        rows.append(_row("D3", key, f"D3.{key}.semantic", f"{label} — {judge_model} semantic judge", semantic_value, default_semantic_caps[key], normalized=float(semantic_percentage) / 100.0 if _number(semantic_percentage) is not None else None, status=semantic.get("status", status), detail={"semantic_percentage": semantic_percentage, "panel": semantic.get("judge_panel")}))
        fused_value = fused.get(key)
        rows.append(_row("D3", key, f"D3.{key}.fused", f"{label} — fused", fused_value, dimension_caps.get(key, default_tool_caps[key] + default_semantic_caps[key]), status=status))
    return rows


def _d4_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    d4 = _dimension(result, "D4")
    detail = _mapping(d4.get("detail")) or d4
    aggregate, maximum, normalized = _aggregate_score(d4)
    status = d4.get("status") or ("completed" if aggregate is not None else "not_configured" if d4 else "not_run")
    rows = [_row("D4", "aggregate", "D4", "Visual and interaction experience", aggregate, maximum, normalized=normalized, status=status)]
    if status == "not_configured":
        return rows
    d41 = _mapping(detail.get("d4_1_artistic_visual_quality"))
    d42 = _mapping(detail.get("d4_2_feedback_fidelity"))
    d43 = _mapping(detail.get("d4_3_goal_interaction_inferability"))
    rows.append(_row("D4", "D4.1", "D4.1", "Artistic visual quality", d41.get("score"), d41.get("max_score", 2), status=d41.get("status", status)))
    criteria = _mapping(d41.get("criterion_scores"))
    for criterion in D4_CRITERIA:
        rows.append(_row("D4", "D4.1", f"D4.1.{criterion}", criterion.replace("_", " "), criteria.get(criterion), 2, status=d41.get("status", status)))
    rows.append(_row("D4", "D4.2", "D4.2", "Feedback fidelity", d42.get("score"), d42.get("max_score", 5), status=d42.get("status", status)))
    transitions = d42.get("transitions", [])
    if isinstance(transitions, list):
        for transition in transitions:
            transition = _mapping(transition)
            transition_id = str(transition.get("id", "transition"))
            components = _mapping(transition.get("component_scores"))
            rows.append(_row("D4", "D4.2", transition_id, transition_id, transition.get("score"), transition.get("max_score", 5), status=transition.get("status", status)))
            for component in ("faithfulness", "completeness", "timeliness"):
                rows.append(_row("D4", "D4.2", f"{transition_id}.{component}", f"{transition_id} {component}", components.get(component), 5, status=transition.get("status", status)))
    rows.append(_row("D4", "D4.3", "D4.3", "Goal and interaction inferability", d43.get("score"), d43.get("max_score", 5), status=d43.get("status", status)))
    questions = d43.get("questions", [])
    if isinstance(questions, list):
        for question in questions:
            question = _mapping(question)
            question_id = str(question.get("id", "question"))
            rows.append(_row("D4", "D4.3", question_id, question_id, question.get("score"), question.get("max_score", 5), status=question.get("status", status), detail={"predicted_choice": question.get("predicted_choice"), "correct_choice": question.get("correct_choice"), "correct": question.get("correct")}))
    return rows


def score_item_rows(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Flatten every available score item without coercing missing values to zero."""
    normalized = _mapping(result)
    return _d1_rows(normalized) + _d2_rows(normalized) + _d3_rows(normalized) + _d4_rows(normalized)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(_jsonable(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]], fields: Sequence[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: "" if row.get(field) is None else row.get(field) for field in fields})


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value).replace("|", "\\|").replace("\n", " ")


def _score_and_status(row: Mapping[str, Any], prefix: str) -> str:
    score = _fmt(row.get(f"{prefix}_score"))
    status = row.get(f"{prefix}_status")
    return f"{score} ({_fmt(status)})" if status else score


def _task_identity(result: Mapping[str, Any]) -> dict[str, Any]:
    task = _mapping(result.get("task"))
    return {
        "game": task.get("game") or result.get("game"),
        "model": task.get("model") or result.get("model"),
        "repetition": task.get("repetition", result.get("repetition", 1)),
        "status": result.get("status"),
    }


def _final_score(result: Mapping[str, Any]) -> Any:
    if result.get("status") == "needs_rescore":
        return None
    return result.get("official_total")


def _d4_contract_provenance(value: Mapping[str, Any]) -> dict[str, Any]:
    evaluation_policy = _mapping(value.get("evaluation_policy"))
    contract = _mapping(evaluation_policy.get("d4_contract"))
    if contract:
        return {
            "version": contract.get("version"),
            "design_version": contract.get("design_version"),
            "sha256": contract.get("sha256"),
            "file_sha256": contract.get("file_sha256"),
            "path": contract.get("path"),
        }
    # Batch matrix records use the execution-layer contract descriptor shape.
    contract = _mapping(value.get("d4_contract"))
    return {
        "version": contract.get("contract_version"),
        "design_version": contract.get("design_version"),
        "sha256": contract.get("contract_sha256"),
        "file_sha256": contract.get("file_sha256"),
        "path": contract.get("path"),
    }


def _scorecard_markdown(result: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> str:
    identity = _task_identity(result)
    task = _mapping(result.get("task"))
    d4_contract = _d4_contract_provenance(result)
    judge = _judge_provenance(result)
    lines = [
        "# Code2Play-Bench scorecard",
        "",
        f"- Game: {_fmt(identity['game'])}",
        f"- Candidate model: {_fmt(identity['model'])}",
        f"- Repetition: {_fmt(identity['repetition'])}",
        f"- Task status: {_fmt(identity['status'])}",
        f"- Official final score: {_fmt(_final_score(result))}",
        f"- Candidate project SHA256: {_fmt(task.get('candidate_project_sha256'))}",
        f"- Judge policy: {judge['policy']}",
        f"- Judge model: {judge['model']}",
        f"- Judge mode: {judge['mode']}",
        f"- Judge temperature: {judge['temperature']}",
        f"- D4 contract version: {_fmt(d4_contract['version'])}",
        f"- D4 contract SHA256: {_fmt(d4_contract['sha256'])}",
        f"- D4 contract file SHA256: {_fmt(d4_contract['file_sha256'])}",
        f"- D4 contract path: {_fmt(d4_contract['path'])}",
        "",
        "A dash means the value is unavailable; it is never interpreted as zero.",
        *(
            [
                "This task has a retryable judge gap. No official total is published; "
                "completed dimension evidence is retained for stage-only rescore."
            ]
            if identity["status"] == "needs_rescore"
            else []
        ),
        "",
        "| Dimension | Subdimension | Item ID | Label | Score | Max | Normalized | Penalty | Status |",
        "|---|---|---|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                _fmt(row.get(field))
                for field in (
                    "dimension",
                    "subdimension",
                    "item_id",
                    "item",
                    "score",
                    "max_score",
                    "normalized_score",
                    "penalty",
                    "status",
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def write_task_reports(task_dir: Path | str, result: Mapping[str, Any]) -> dict[str, str]:
    """Write current reports and a non-scoring human-review evidence sidecar."""
    destination = Path(task_dir)
    destination.mkdir(parents=True, exist_ok=True)
    normalized_result = validate_current_report(result)
    if normalized_result.get("status") == "needs_rescore":
        normalized_result["official_total"] = None
        normalized_result["report_semantics"] = (
            "retryable_judge_gap_not_candidate_zero"
        )
    candidate_manifest = _optional_json(destination / "candidate_manifest.json")
    generation_summary = _optional_json(destination / "generation_summary.json")
    candidate_root = destination / "candidate"
    source_metrics: dict[str, Any] = {}
    if candidate_root.is_dir():
        for filename in ("state.py", "game.py", "rendering.py", "main.py"):
            path = candidate_root / filename
            if path.is_file():
                text = path.read_text(encoding="utf-8-sig", errors="replace")
                source_metrics[filename] = {
                    "lines": len(text.splitlines()),
                    "bytes": len(text.encode("utf-8")),
                }
    normalized_result["candidate_project"] = {
        "manifest": candidate_manifest,
        "source_metrics": source_metrics,
        "total_lines": sum(item["lines"] for item in source_metrics.values()),
    }
    normalized_result["generation"] = generation_summary
    try:
        from code2play.human_review.artifacts import build_human_evidence

        human_manifest = build_human_evidence(destination, normalized_result)
        normalized_result["human_review"] = {
            "status": human_manifest["status"],
            "schema_version": human_manifest["schema_version"],
            "item_count": human_manifest["item_count"],
            "rateable_item_count": human_manifest["rateable_item_count"],
            "cannot_rate_item_count": human_manifest["cannot_rate_item_count"],
            "manifest": "evaluation/human_review/source/manifest.json",
            "automatic_scores_modified": False,
        }
    except BaseException as exc:
        # Human evidence is an audit sidecar. Its failure must be visible but
        # must never rewrite or invalidate the already-computed official score.
        normalized_result["human_review"] = {
            "status": "human_evidence_build_failed",
            "error_type": type(exc).__name__,
            "error": redact_text(str(exc)),
            "automatic_scores_modified": False,
        }
    rows = score_item_rows(normalized_result)
    summary_path = destination / "summary.json"
    csv_path = destination / "score_items.csv"
    markdown_path = destination / "scorecard.md"
    _write_json(summary_path, normalized_result)
    _write_csv(csv_path, rows, CSV_FIELDS)
    markdown_path.write_text(_scorecard_markdown(normalized_result, rows), encoding="utf-8")
    return {
        "summary_json": str(summary_path),
        "score_items_csv": str(csv_path),
        "scorecard_md": str(markdown_path),
        "human_evidence_manifest": str(
            destination / "evaluation" / "human_review" / "source" / "manifest.json"
        ),
    }


def _optional_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return _mapping(value)


def write_failure_reports(
    run_dir: Path | str,
    task_records: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    """Write complete audit summaries for every failed matrix slot."""

    destination = Path(run_dir)
    reports: list[dict[str, str]] = []
    for raw_record in task_records:
        record = _mapping(raw_record)
        if record.get("status") != "failed" or not record.get("task_id"):
            continue
        task_id = str(record["task_id"])
        from code2play.config.project import task_storage_dir
        task_dir = Path(record["task_dir"]) if record.get("task_dir") else task_storage_dir(destination, task_id)
        failure = _optional_json(task_dir / "failure.json") or record
        task_state = _optional_json(task_dir / "run_state.json")
        evaluation_state = _optional_json(task_dir / "evaluation" / "stage_state.json")
        d1 = _optional_json(task_dir / "evaluation" / "d1.json")
        d3_bundle = _optional_json(task_dir / "evaluation" / "d3.json")
        d3 = _first_mapping(d3_bundle.get("result"), d3_bundle)

        known_artifacts = [
            "candidate_manifest.json",
            "generation_summary.json",
            "failure.json",
            "run_state.json",
            "evaluation/stage_state.json",
            "evaluation/d1.json",
            "evaluation/d3.json",
        ]
        artifacts = [
            path
            for path in known_artifacts
            if (task_dir / Path(path)).is_file()
        ]
        semantic_root = task_dir / "evaluation" / "semantic_evidence"
        sampling_attempts = (
            sorted(path.name for path in semantic_root.glob("sampling_attempt_*"))
            if semantic_root.is_dir()
            else []
        )
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "status": "failed",
            "task_id": task_id,
            "game": record.get("game"),
            "model": record.get("model"),
            "repetition": record.get("repetition"),
            "terminal_failure": bool(
                failure.get("terminal_failure", record.get("terminal_failure"))
            ),
            "candidate_locked": failure.get("candidate_locked"),
            "candidate_project_sha256": failure.get("project_sha256"),
            "failed_stage": failure.get("stage"),
            "error_type": failure.get("error_type", record.get("error_type")),
            "error": failure.get("error", record.get("error")),
            "traceback": failure.get("traceback"),
            "partial_diagnostics": {
                "D1": {
                    "status": "completed" if d1 else "not_available",
                    "score": d1.get("score"),
                    "gate_pass": d1.get("gate_pass"),
                },
                "D3": {
                    "status": d3.get("status", "not_available"),
                    "score": d3.get("score"),
                    "tool_diagnostic_score": d3.get("tool_diagnostic_score"),
                },
                "D2": {"status": "not_completed_candidate_protocol_failure"},
                "D4": {"status": "not_completed_candidate_protocol_failure"},
            },
            "artifacts": artifacts,
            "sampling_attempts": sampling_attempts,
            "task_state": task_state,
            "evaluation_state": evaluation_state,
        }
        try:
            from code2play.human_review.artifacts import build_human_evidence

            human_manifest = build_human_evidence(
                task_dir,
                {
                    "task": {
                        "game": report.get("game"),
                        "model": report.get("model"),
                        "repetition": report.get("repetition"),
                        "candidate_project_sha256": report.get(
                            "candidate_project_sha256"
                        ),
                    }
                },
            )
            report["human_review"] = {
                "status": human_manifest["status"],
                "manifest": "evaluation/human_review/source/manifest.json",
                "item_count": human_manifest["item_count"],
                "automatic_scores_modified": False,
            }
            artifacts.append("evaluation/human_review/source/manifest.json")
        except BaseException as exc:
            report["human_review"] = {
                "status": "human_evidence_build_failed",
                "error_type": type(exc).__name__,
                "error": redact_text(str(exc)),
                "automatic_scores_modified": False,
            }
        report_path = task_dir / "failure_report.json"
        markdown_path = task_dir / "failure_report.md"
        _write_json(report_path, sanitize(report))

        diagnostics = report["partial_diagnostics"]
        error_text = redact_text(str(report.get("error") or "Unavailable"))
        traceback_text = redact_text(str(report.get("traceback") or "Unavailable"))
        lines = [
            "# Failed task report",
            "",
            f"- Task: `{task_id}`",
            f"- Game: `{_fmt(report.get('game'))}`",
            f"- Model: `{_fmt(report.get('model'))}`",
            f"- Failed stage: `{_fmt(report.get('failed_stage'))}`",
            f"- Terminal candidate failure: `{str(report['terminal_failure']).lower()}`",
            f"- Candidate locked: `{str(bool(report.get('candidate_locked'))).lower()}`",
            f"- Candidate project SHA256: `{_fmt(report.get('candidate_project_sha256'))}`",
            "",
            "## Root cause",
            "",
            f"Error type: `{_fmt(report.get('error_type'))}`",
            "",
            "```text",
            error_text,
            "```",
            "",
            "## Partial diagnostics",
            "",
            "| Dimension | Status | Score |",
            "|---|---|---:|",
            f"| D1 | {_fmt(diagnostics['D1']['status'])} | {_fmt(diagnostics['D1']['score'])} |",
            f"| D2 | {_fmt(diagnostics['D2']['status'])} | {_fmt(None)} |",
            f"| D3 | {_fmt(diagnostics['D3']['status'])} | {_fmt(diagnostics['D3']['score'])} |",
            f"| D4 | {_fmt(diagnostics['D4']['status'])} | {_fmt(None)} |",
            "",
            "## Evidence",
            "",
            *[f"- `{path}`" for path in artifacts],
            *[f"- `evaluation/semantic_evidence/{name}`" for name in sampling_attempts],
            "",
            "## Traceback",
            "",
            "```text",
            traceback_text,
            "```",
        ]
        markdown_path.write_text(
            redact_text("\n".join(lines) + "\n"),
            encoding="utf-8",
        )
        reports.append(
            {
                "task_id": task_id,
                "failure_report_json": str(report_path),
                "failure_report_md": str(markdown_path),
            }
        )
    return reports


def _task_record(record: Any, run_dir: Path | None = None) -> dict[str, Any]:
    item = _mapping(record)
    task_dir = item.get("task_dir")
    if task_dir is None and run_dir is not None and item.get("task_id"):
        from code2play.config.project import task_storage_dir
        task_dir = str(task_storage_dir(run_dir, str(item["task_id"])))
    result = _first_mapping(item.get("result"), item.get("summary"))
    if not result and task_dir:
        summary_path = Path(str(task_dir)) / "summary.json"
        if summary_path.is_file():
            try:
                result = _mapping(json.loads(summary_path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                result = {}
    result = result or item
    if "dimensions" in result:
        result = validate_current_report(result)
    elif not _mapping(item.get("result")) and not _mapping(item.get("summary")):
        _validate_current_matrix_record(item)
    else:
        raise ValueError("Batch report input is not a current result or matrix record")
    identity = _task_identity(result)
    task = _mapping(item.get("task"))
    for field in ("game", "model", "repetition", "status"):
        if identity.get(field) is None and item.get(field) is not None:
            identity[field] = item.get(field)
        if identity.get(field) is None and task.get(field) is not None:
            identity[field] = task.get(field)
    dimensions = {key: _dimension(result, key) for key in ("D1", "D2", "D3", "D4")}
    d4_contract = _d4_contract_provenance(result)
    if not any(d4_contract.values()):
        d4_contract = _d4_contract_provenance(item)
    judge = _judge_provenance(result)
    flat: dict[str, Any] = {
        **identity,
        **{key: item.get(key) for key in ("track", "instance_id", "family_slug", "variant_id")},
        "judge_policy": judge["policy"],
        "judge_model": judge["model"],
        "judge_mode": judge["mode"],
        "judge_temperature": judge["temperature"],
        "d4_contract_version": d4_contract["version"],
        "d4_contract_design_version": d4_contract["design_version"],
        "d4_contract_sha256": d4_contract["sha256"],
        "d4_contract_file_sha256": d4_contract["file_sha256"],
        "d4_contract_path": d4_contract["path"],
        "final_score": _number(_final_score(result)),
        "task_dir": task_dir or result.get("task_dir"),
    }
    for key, dimension in dimensions.items():
        score, maximum, normalized = _aggregate_score(dimension)
        flat[f"{key.lower()}_score"] = _number(score)
        flat[f"{key.lower()}_max_score"] = _number(maximum)
        flat[f"{key.lower()}_normalized"] = _number(normalized)
        flat[f"{key.lower()}_status"] = dimension.get("status")
    return {"record": item, "result": result, "flat": flat}


BATCH_CSV_FIELDS = (
    "track", "instance_id", "family_slug", "variant_id",
    "game", "model", "repetition", "status", "judge_policy", "judge_model",
    "judge_mode", "judge_temperature",
    "d4_contract_version", "d4_contract_design_version",
    "d4_contract_sha256", "d4_contract_file_sha256", "d4_contract_path",
    "d1_score", "d1_max_score", "d1_normalized", "d1_status",
    "d2_score", "d2_max_score", "d2_normalized", "d2_status",
    "d3_score", "d3_max_score", "d3_normalized", "d3_status",
    "d4_score", "d4_max_score", "d4_normalized", "d4_status",
    "final_score", "task_dir",
)


def write_batch_reports(run_dir: Path | str, task_records: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Write the complete batch matrix as ``matrix.json/csv/md``."""
    destination = Path(run_dir)
    destination.mkdir(parents=True, exist_ok=True)
    normalized = [_task_record(record, destination) for record in task_records]
    batch_judge = (
        _judge_provenance(normalized[0]["result"])
        if normalized
        else {
            "policy": JUDGE_POLICY,
            "model": JUDGE_MODEL,
            "mode": JUDGE_MODE,
            "temperature": JUDGE_TEMPERATURE,
        }
    )
    matrix_json = destination / "matrix.json"
    matrix_csv = destination / "matrix.csv"
    matrix_md = destination / "matrix.md"
    contracts = {
        str(item["flat"].get("game")): {
            "version": item["flat"].get("d4_contract_version"),
            "design_version": item["flat"].get("d4_contract_design_version"),
            "contract_sha256": item["flat"].get("d4_contract_sha256"),
            "file_sha256": item["flat"].get("d4_contract_file_sha256"),
            "path": item["flat"].get("d4_contract_path"),
        }
        for item in normalized
        if item["flat"].get("game")
        and item["flat"].get("d4_contract_sha256")
    }
    payload = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "judge_policy": batch_judge["policy"],
        "judge_model": batch_judge["model"],
        "judge_mode": batch_judge["mode"],
        "judge_temperature": batch_judge["temperature"],
        "d4_contracts": contracts,
        "task_count": len(normalized),
        "completed_count": sum(1 for item in normalized if item["flat"].get("status") == "completed"),
        "matrix": [item["flat"] for item in normalized],
        "tasks": [
            {
                "state": item["record"],
                "summary": item["result"] if item["result"] is not item["record"] else None,
            }
            for item in normalized
        ],
    }
    _write_json(matrix_json, payload)
    rows = [item["flat"] for item in normalized]
    _write_csv(matrix_csv, rows, BATCH_CSV_FIELDS)
    lines = [
        "# Code2Play-Bench matrix",
        "",
        f"- Judge policy: {batch_judge['policy']}",
        f"- Judge model: {batch_judge['model']}",
        f"- Judge mode: {batch_judge['mode']}",
        f"- Judge temperature: {batch_judge['temperature']}",
        f"- Round-locked D4 contracts: {len(contracts)} game assets",
        "",
        "A dash means unavailable; each instance uses its own round-locked contract.",
        "",
        "| Game | Model | Rep | Status | D4 contract | D1 (status) | D2 (status) | D3 (status) | D4 (status) | Final |",
        "|---|---|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        values = [
            _fmt(row.get("game")),
            _fmt(row.get("model")),
            _fmt(row.get("repetition")),
            _fmt(row.get("status")),
            (
                f"{_fmt(row.get('d4_contract_version'))}:"
                f"{_fmt(row.get('d4_contract_sha256'))}"
            ),
            _score_and_status(row, "d1"),
            _score_and_status(row, "d2"),
            _score_and_status(row, "d3"),
            _score_and_status(row, "d4"),
            _fmt(row.get("final_score")),
        ]
        lines.append("| " + " | ".join(values) + " |")
    matrix_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"matrix_json": str(matrix_json), "matrix_csv": str(matrix_csv), "matrix_md": str(matrix_md)}


def _add_statistics(
    row: dict[str, Any],
    field: str,
    values: Sequence[float],
) -> None:
    row[f"{field}_n"] = len(values)
    row[f"{field}_mean"] = (
        round(statistics.mean(values), 6) if values else None
    )
    row[f"{field}_stdev"] = (
        round(statistics.stdev(values), 6) if len(values) >= 2 else None
    )
    row[f"{field}_min"] = round(min(values), 6) if values else None
    row[f"{field}_max"] = round(max(values), 6) if values else None


def _panel_records(value: Any, *, policy: str | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            if (
                (policy is None or item.get("policy") == policy)
                and isinstance(item.get("purpose"), str)
                and isinstance(item.get("decision"), str)
            ):
                records.append(_mapping(item))
                return
            for child in item.values():
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)

    visit(value)
    return records


def _load_task_summary(run_dir: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    raw_task_dir = row.get("task_dir")
    if not isinstance(raw_task_dir, str) or not raw_task_dir.strip():
        return {}
    task_dir = Path(raw_task_dir)
    if not task_dir.is_absolute():
        task_dir = run_dir / task_dir
    summary_path = task_dir / "summary.json"
    if not summary_path.is_file():
        return {}
    try:
        return _mapping(json.loads(summary_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return {}


def _panel_dimension(purpose: str) -> str:
    lowered = purpose.lower()
    if lowered.startswith("d2_"):
        return "D2"
    if lowered.startswith("d3_"):
        return "D3"
    if lowered.startswith("d4_"):
        return "D4"
    return "other"


def _panel_flash_failure(record: Mapping[str, Any]) -> bool:
    if _mapping(record.get("flash_errors")):
        return True
    rule = str(_mapping(record.get("disagreement")).get("rule", ""))
    return rule in {"flash_call_or_schema_failure", "flash_schema_failure"}


def _panel_score_disagreement(record: Mapping[str, Any]) -> bool:
    if _panel_flash_failure(record):
        return False
    metrics = _mapping(record.get("disagreement"))
    for key in (
        "absolute_delta",
        "overall_absolute_delta",
        "mean_absolute_delta",
    ):
        value = _number(metrics.get(key))
        if value is not None and float(value) > 0:
            return True
    for key in (
        "absolute_deltas",
        "criterion_absolute_deltas",
        "component_absolute_deltas",
    ):
        values = _mapping(metrics.get(key))
        if any(
            _number(value) is not None and float(_number(value)) > 0
            for value in values.values()
        ):
            return True
    differences = _mapping(metrics.get("component_differences"))
    if any(value is True for value in differences.values()):
        return True
    left_choice = metrics.get("left_choice")
    right_choice = metrics.get("right_choice")
    if left_choice is not None and right_choice is not None:
        return str(left_choice) != str(right_choice)
    return (
        record.get("decision") == "sol_arbitration"
        and not _panel_flash_failure(record)
    )


def _judge_summary_row(
    scope_type: str,
    scope_value: str,
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    total = len(records)
    score_disagreements = sum(_panel_score_disagreement(item) for item in records)
    sol_arbitrations = sum(
        item.get("decision") == "sol_arbitration" for item in records
    )
    flash_failures = sum(
        item.get("decision") == "sol_arbitration"
        and _panel_flash_failure(item)
        for item in records
    )
    semantic_calls = sum(
        int(_number(item.get("semantic_call_count")) or 0) for item in records
    )
    return {
        "scope_type": scope_type,
        "scope_value": scope_value,
        "decision_count": total,
        "score_disagreement_count": score_disagreements,
        "score_disagreement_rate": (
            round(score_disagreements / total, 6) if total else None
        ),
        "sol_arbitration_count": sol_arbitrations,
        "sol_arbitration_rate": (
            round(sol_arbitrations / total, 6) if total else None
        ),
        "flash_failure_arbitration_count": flash_failures,
        "semantic_call_count": semantic_calls,
    }


def _mean_stdev(row: Mapping[str, Any], field: str) -> str:
    mean = _fmt(row.get(f"{field}_mean"))
    stdev = _fmt(row.get(f"{field}_stdev"))
    return f"{mean} +/- {stdev}"


def write_multi_run_reports(
    output_dir: Path | str,
    run_dirs: Sequence[Path | str],
) -> dict[str, str]:
    """Combine independent runs without mixing their task evidence."""

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    if any(_optional_json(Path(root) / "run_state.json").get("selection") for root in run_dirs):
        from code2play.reporting.tracks import combined_report
        target = destination / "track_comparison.json"
        _write_json(target, combined_report([Path(root) for root in run_dirs]))
        return {"track_comparison_json": str(target)}
    combined_rows: list[dict[str, Any]] = []
    run_summaries: list[dict[str, Any]] = []
    panel_records: list[dict[str, Any]] = []
    for raw_run_dir in run_dirs:
        run_dir = Path(raw_run_dir).resolve()
        matrix_path = run_dir / "matrix.json"
        if not matrix_path.is_file():
            raise FileNotFoundError(f"Missing batch matrix: {matrix_path}")
        payload = json.loads(matrix_path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != REPORT_SCHEMA_VERSION:
            raise ValueError(f"Batch matrix uses an unsupported report schema: {matrix_path}")
        matrix = payload.get("matrix")
        if not isinstance(matrix, list):
            raise ValueError(f"Batch matrix is malformed: {matrix_path}")
        for row in matrix:
            if not isinstance(row, Mapping):
                raise ValueError(f"Batch matrix contains a non-object row: {matrix_path}")
            _validate_current_matrix_record(row, require_task_id=False)
        run_rows = [
            {"run_id": run_dir.name, **_mapping(row)}
            for row in matrix
            if isinstance(row, Mapping)
        ]
        combined_rows.extend(run_rows)
        for row in run_rows:
            summary = _load_task_summary(run_dir, row)
            summary_policy = str(_judge_provenance(summary)["policy"] or "")
            for panel in _panel_records(summary, policy=summary_policy or None):
                panel_records.append(
                    {
                        "run_id": run_dir.name,
                        "game": row.get("game"),
                        "model": row.get("model"),
                        "dimension": _panel_dimension(str(panel.get("purpose"))),
                        **panel,
                    }
                )
        run_summaries.append(
            {
                "run_id": run_dir.name,
                "run_dir": str(run_dir),
                "task_count": len(run_rows),
                "completed_count": sum(
                    row.get("status") == "completed" for row in run_rows
                ),
                "failed_count": sum(
                    row.get("status") == "failed" for row in run_rows
                ),
                "matrix_json": str(matrix_path),
            }
        )

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in combined_rows:
        key = (str(row.get("game")), str(row.get("model")))
        grouped.setdefault(key, []).append(row)

    aggregate_rows: list[dict[str, Any]] = []
    for (game, model), rows in sorted(grouped.items()):
        aggregate: dict[str, Any] = {
            "game": game,
            "model": model,
            "run_count": len(rows),
            "completed_count": sum(row.get("status") == "completed" for row in rows),
            "failed_count": sum(row.get("status") == "failed" for row in rows),
        }
        for field in MULTI_RUN_SCORE_FIELDS:
            values = [
                float(value)
                for row in rows
                if (value := _number(row.get(field))) is not None
            ]
            _add_statistics(aggregate, field, values)
        aggregate_rows.append(aggregate)

    model_run_groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in combined_rows:
        key = (str(row.get("model")), str(row.get("run_id")))
        model_run_groups.setdefault(key, []).append(row)
    model_rows: list[dict[str, Any]] = []
    for model in sorted({key[0] for key in model_run_groups}):
        all_rows = [
            row for row in combined_rows if str(row.get("model")) == model
        ]
        model_row: dict[str, Any] = {
            "model": model,
            "run_count": len(
                {str(row.get("run_id")) for row in all_rows}
            ),
            "task_count": len(all_rows),
            "completed_count": sum(
                row.get("status") == "completed" for row in all_rows
            ),
            "failed_count": sum(
                row.get("status") == "failed" for row in all_rows
            ),
        }
        for field in MULTI_RUN_SCORE_FIELDS:
            task_values = [
                float(value)
                for row in all_rows
                if (value := _number(row.get(field))) is not None
            ]
            run_means = []
            for (group_model, _run_id), rows in model_run_groups.items():
                if group_model != model:
                    continue
                values = [
                    float(value)
                    for row in rows
                    if (value := _number(row.get(field))) is not None
                ]
                if values:
                    run_means.append(statistics.mean(values))
            model_row[f"{field}_task_n"] = len(task_values)
            _add_statistics(model_row, field, run_means)
        model_rows.append(model_row)

    judge_rows = [_judge_summary_row("overall", "all", panel_records)]
    for dimension in sorted(
        {str(item.get("dimension")) for item in panel_records}
    ):
        judge_rows.append(
            _judge_summary_row(
                "dimension",
                dimension,
                [
                    item
                    for item in panel_records
                    if str(item.get("dimension")) == dimension
                ],
            )
        )
    for model in sorted({str(item.get("model")) for item in panel_records}):
        judge_rows.append(
            _judge_summary_row(
                "model",
                model,
                [
                    item
                    for item in panel_records
                    if str(item.get("model")) == model
                ],
            )
        )
    for run_id in sorted({str(item.get("run_id")) for item in panel_records}):
        judge_rows.append(
            _judge_summary_row(
                "run",
                run_id,
                [
                    item
                    for item in panel_records
                    if str(item.get("run_id")) == run_id
                ],
            )
        )

    active_policies = sorted(
        {
            str(row.get("judge_policy"))
            for row in combined_rows
            if isinstance(row.get("judge_policy"), str) and row["judge_policy"].strip()
        }
    )
    combined_policy = (
        active_policies[0]
        if len(active_policies) == 1
        else "mixed: " + ", ".join(active_policies)
        if active_policies
        else JUDGE_POLICY
    )
    combined_json = destination / "combined_runs.json"
    combined_csv = destination / "combined_matrix.csv"
    aggregate_csv = destination / "aggregate.csv"
    aggregate_md = destination / "aggregate.md"
    model_csv = destination / "model_summary.csv"
    judge_csv = destination / "judge_panel_summary.csv"
    summary_md = destination / "summary.md"
    _write_json(
        combined_json,
        {
            "schema_version": 2,
            "judge_policy": combined_policy,
            "judge_policies": active_policies,
            "run_count": len(run_summaries),
            "task_count": len(combined_rows),
            "runs": run_summaries,
            "aggregate": aggregate_rows,
            "model_summary": model_rows,
            "judge_panel_summary": judge_rows,
            "matrix": combined_rows,
        },
    )
    combined_fields = ("run_id", *BATCH_CSV_FIELDS)
    _write_csv(combined_csv, combined_rows, combined_fields)
    aggregate_fields = (
        "game",
        "model",
        "run_count",
        "completed_count",
        "failed_count",
        *[
            f"{field}_{suffix}"
            for field in MULTI_RUN_SCORE_FIELDS
            for suffix in ("n", "mean", "stdev", "min", "max")
        ],
    )
    _write_csv(aggregate_csv, aggregate_rows, aggregate_fields)
    model_fields = (
        "model",
        "run_count",
        "task_count",
        "completed_count",
        "failed_count",
        *[
            name
            for field in MULTI_RUN_SCORE_FIELDS
            for name in (
                f"{field}_task_n",
                f"{field}_n",
                f"{field}_mean",
                f"{field}_stdev",
                f"{field}_min",
                f"{field}_max",
            )
        ],
    )
    _write_csv(model_csv, model_rows, model_fields)
    judge_fields = (
        "scope_type",
        "scope_value",
        "decision_count",
        "score_disagreement_count",
        "score_disagreement_rate",
        "sol_arbitration_count",
        "sol_arbitration_rate",
        "flash_failure_arbitration_count",
        "semantic_call_count",
    )
    _write_csv(judge_csv, judge_rows, judge_fields)
    lines = [
        "# Code2Play-Bench multi-run aggregate",
        "",
        f"- Judge policy: {combined_policy}",
        f"- Independent runs: {len(run_summaries)}",
        f"- Matrix records: {len(combined_rows)}",
        "",
        "| Game | Model | Completed | Failed | D1 mean | D2 mean | D3 mean | D4 mean | Final mean | Final stdev |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in aggregate_rows:
        lines.append(
            "| "
            + " | ".join(
                _fmt(row.get(field))
                for field in (
                    "game",
                    "model",
                    "completed_count",
                    "failed_count",
                    "d1_score_mean",
                    "d2_score_mean",
                    "d3_score_mean",
                    "d4_score_mean",
                    "final_score_mean",
                    "final_score_stdev",
                )
            )
            + " |"
        )
    aggregate_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary_lines = [
        "# Code2Play-Bench multi-run summary",
        "",
        f"- Judge policy: {combined_policy}",
        f"- Independent runs: {len(run_summaries)}",
        f"- Completed matrix records: "
        f"{sum(row.get('status') == 'completed' for row in combined_rows)}"
        f"/{len(combined_rows)}",
        "- D4 and official totals cover all 15 games using each round's locked contract.",
        "- Model standard deviations are computed across three independent "
        "per-run game means.",
        "",
        "## Candidate model summary",
        "",
        "| Model | Completed | D1 mean +/- sd | D2 mean +/- sd | "
        "D3 mean +/- sd | D4 mean +/- sd | Final mean +/- sd |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in model_rows:
        summary_lines.append(
            "| "
            + " | ".join(
                (
                    _fmt(row.get("model")),
                    _fmt(row.get("completed_count")),
                    _mean_stdev(row, "d1_score"),
                    _mean_stdev(row, "d2_score"),
                    _mean_stdev(row, "d3_score"),
                    _mean_stdev(row, "d4_score"),
                    _mean_stdev(row, "final_score"),
                )
            )
            + " |"
        )
    summary_lines.extend(
        [
            "",
            "## Judge consistency",
            "",
            "| Scope | Decisions | Score disagreements | Disagreement rate | "
            "Sol arbitrations | Sol rate | Flash failure arbitrations |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in judge_rows:
        summary_lines.append(
            "| "
            + " | ".join(
                (
                    f"{_fmt(row.get('scope_type'))}:"
                    f"{_fmt(row.get('scope_value'))}",
                    _fmt(row.get("decision_count")),
                    _fmt(row.get("score_disagreement_count")),
                    _fmt(row.get("score_disagreement_rate")),
                    _fmt(row.get("sol_arbitration_count")),
                    _fmt(row.get("sol_arbitration_rate")),
                    _fmt(row.get("flash_failure_arbitration_count")),
                )
            )
            + " |"
        )
    summary_md.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    return {
        "combined_runs_json": str(combined_json),
        "combined_matrix_csv": str(combined_csv),
        "aggregate_csv": str(aggregate_csv),
        "aggregate_md": str(aggregate_md),
        "model_summary_csv": str(model_csv),
        "judge_panel_summary_csv": str(judge_csv),
        "summary_md": str(summary_md),
    }


__all__ = [
    "score_item_rows",
    "validate_current_report",
    "write_task_reports",
    "write_failure_reports",
    "write_batch_reports",
    "write_multi_run_reports",
]
