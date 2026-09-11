"""Track-specific coverage, family-weighted scores, and measured API consumption."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any, Mapping, Sequence

from code2play.config.project import task_storage_dir
from code2play.execution.safe_artifacts import write_json


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def elapsed(start, end):
    try:
        return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    except (ValueError, TypeError):
        return None


def api_usage(root: Path, prices: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Read each physical attempt once, including failed and resumed cycles.

    OpenRouter cost is authoritative when supplied. Otherwise a caller may pass
    a dated price snapshot with input/output/cached_input_usd_per_million. Missing
    usage or image-token breakdowns stay unknown rather than becoming free usage.
    """
    rows = []
    pending_requests = 0
    for raw_path in root.rglob("raw_input.json"):
        meta = read_json(raw_path)
        result = read_json(raw_path.with_name("request_result.json"))
        attempts = result.get("attempts")
        if not isinstance(attempts, list):
            outputs = sorted(raw_path.parent.glob("raw_response_attempt_*.json"))
            if not outputs and raw_path.with_name("raw_response.json").exists():
                outputs = [raw_path.with_name("raw_response.json")]
            attempts = [{"attempt": i, "usage": read_json(path).get("usage")} for i, path in enumerate(outputs, 1)]
        recorded = {int(item["attempt"]) for item in attempts}
        error_indices = {int(path.stem.rsplit("_", 1)[1]) for path in raw_path.parent.glob("attempt_error_*.json")}
        made = set(range(1, int(result.get("attempts_made", 0)) + 1)) | error_indices
        attempts = [*attempts, *({"attempt": n, "usage": None} for n in sorted(made - recorded))]
        if not attempts and not result:
            pending_requests += 1
        role = str(meta.get("role") or "judge")
        visual_role = role in {"artistic_visual", "dynamic_visual", "question_generation", "question_answering"}
        category = "contracts" if role == "contract_generation" else "vision_judge" if visual_role or meta.get("images") else "text_judge"
        for attempt in attempts:
            rows.append({"model": meta.get("model"), "category": category, "role": role,
                         "usage": attempt.get("usage"), "retry": int(attempt.get("attempt", 1)) > 1,
                         "image_count": len(meta.get("images") or []), "source": str(raw_path.parent)})
    for path in root.rglob("call_metadata.json"):
        if not path.parent.name.startswith("attempt_") or not path.parent.parent.name.startswith("cycle_"):
            continue
        meta = read_json(path)
        rows.append({"model": meta.get("requested_model"), "category": "generation", "role": "generation",
                     "usage": meta.get("usage"), "retry": path.parent.name != "attempt_001",
                     "explicit_resume": path.parent.parent.name != "cycle_001", "source": str(path.parent)})
    groups = {}
    for row in rows:
        key = (row["category"], row["model"])
        group = groups.setdefault(key, {"category": key[0], "model": key[1], "attempts": 0,
                    "retry_attempts": 0, "explicit_resume_attempts": 0, "missing_usage_attempts": 0,
                    "input_tokens": 0, "output_tokens": 0, "cached_input_tokens": 0,
                    "reasoning_tokens": 0, "images_sent": 0, "known_cost_usd": 0.0,
                    "unpriced_attempts": 0, "retry_cost_usd": 0.0, "explicit_resume_cost_usd": 0.0,
                    "image_input_tokens": 0, "text_input_tokens": None, "_image_tokens_complete": True})
        group["attempts"] += 1
        group["retry_attempts"] += bool(row.get("retry"))
        group["explicit_resume_attempts"] += bool(row.get("explicit_resume"))
        group["images_sent"] += row.get("image_count", 0)
        usage = row.get("usage")
        if not isinstance(usage, dict) or not usage:
            group["missing_usage_attempts"] += 1
            group["unpriced_attempts"] += 1
            group["_image_tokens_complete"] = False
            continue
        input_tokens = usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0
        output_tokens = usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0
        detail = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
        cached = detail.get("cached_tokens", 0) or 0
        group["input_tokens"] += input_tokens
        group["output_tokens"] += output_tokens
        group["cached_input_tokens"] += cached
        if row.get("image_count"):
            image_tokens = number(detail.get("image_tokens"))
            if image_tokens is None or not 0 <= image_tokens <= input_tokens:
                group["_image_tokens_complete"] = False
            else:
                group["image_input_tokens"] += image_tokens
        group["reasoning_tokens"] += (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) or 0
        cost = number(usage.get("cost"))
        rate = (prices or {}).get(row["model"])
        if cost is None and rate:
            cost = ((input_tokens - cached) * rate["input_usd_per_million"]
                    + cached * rate.get("cached_input_usd_per_million", rate["input_usd_per_million"])
                    + output_tokens * rate["output_usd_per_million"]) / 1_000_000
        if cost is None:
            group["unpriced_attempts"] += 1
        else:
            group["known_cost_usd"] += cost
            if row.get("retry"):
                group["retry_cost_usd"] += cost
            if row.get("explicit_resume"):
                group["explicit_resume_cost_usd"] += cost
    for group in groups.values():
        group["cost_usd"] = group["known_cost_usd"] if not group["unpriced_attempts"] else None
        image_complete = group.pop("_image_tokens_complete")
        if group["category"] == "vision_judge":
            if image_complete:
                group["text_input_tokens"] = group["input_tokens"] - group["image_input_tokens"]
            else:
                group["image_input_tokens"] = None
        else:
            group["image_input_tokens"] = 0
            group["text_input_tokens"] = group["input_tokens"]
    return {"models": list(groups.values()), "attempts": len(rows), "pending_requests": pending_requests,
            "known_cost_usd": sum(group["known_cost_usd"] for group in groups.values()),
            "cost_complete": not pending_requests and all(not group["unpriced_attempts"] for group in groups.values()),
            "image_accounting": "Images are included in provider input tokens; a separate image/text token split is unavailable unless the provider supplies it."}


def inspect_run(run_dir: str | Path, state: Mapping[str, Any] | None = None) -> dict[str, Any]:
    root = Path(run_dir)
    state = dict(state) if state is not None else read_json(root / "run_state.json")
    if not state:
        manual = read_json(root / "manual_evaluation.json")
        if manual:
            return {"run_id": root.name, "status": "manual_evaluation", "selection": manual.get("selection") or {"track": "historical", "scope": "untracked"},
                    "official_score": None, "tasks": [read_json(path) for path in (root / "tasks").glob("*/summary.json")]}
        raise ValueError(f"No run state found: {root}")
    selection = state.get("selection") or {"track": "historical", "scope": "untracked"}
    counts = Counter(item.get("status", "pending") for item in state.get("matrix", []))
    records = []
    for item in state.get("matrix", []):
        task = Path(item["task_dir"]) if item.get("task_dir") else task_storage_dir(root, item["task_id"])
        summary = read_json(task / "summary.json")
        task_state = read_json(task / "run_state.json")
        record = {**item, "task_dir": str(task), "candidate_dir": str(task / "candidate"),
                  "evidence_dir": str(task / "evaluation/semantic_evidence"),
                  "official_total": number(summary.get("official_total", item.get("official_total"))),
                  "dimensions": {dim: number((summary.get("dimensions", {}).get(dim) or {}).get("score")) for dim in ("D1", "D2", "D3", "D4")},
                  "elapsed_seconds": elapsed(task_state.get("created_at", item.get("started_at")), task_state.get("finished_at", item.get("finished_at")))}
        if item.get("status") != "completed":
            record["official_total"] = None
        records.append(record)
    expected_ids = selection.get("suite_instance_ids", [])
    ids = [row.get("instance_id", row.get("game")) for row in records]
    complete = (selection.get("scope") == "complete" and ids == expected_ids
                and len(ids) == selection.get("expected_count")
                and all(row["official_total"] is not None for row in records))
    families = defaultdict(list)
    for row in records:
        families[row.get("family_slug", row["game"])].append(row)
    variants_per_family = 10 if selection.get("track") == "full150" else 1
    complete = complete and len(families) == 15 and all(
        len(rows) == variants_per_family and len({row.get("variant_id", "base") for row in rows}) == variants_per_family
        for rows in families.values()
    )
    aggregate = None
    dimensions = {dim: None for dim in ("D1", "D2", "D3", "D4")}
    if complete:
        aggregate = mean(mean(row["official_total"] for row in family) for family in families.values())
        for dim in dimensions:
            if all(row["dimensions"][dim] is not None for row in records):
                dimensions[dim] = mean(mean(row["dimensions"][dim] for row in family) for family in families.values())
    robustness = []
    if selection.get("track") == "full150":
        for family, rows in families.items():
            base = next((row["official_total"] for row in rows if row.get("variant_id") == "base"), None)
            variants = [row for row in rows if row.get("variant_id") != "base"]
            variant_mean = mean(row["official_total"] for row in variants) if len(variants) == 9 and all(row["official_total"] is not None for row in variants) else None
            robustness.append({"family_slug": family, "base_score": base, "variant_mean": variant_mean,
                               "variant_minus_base": variant_mean - base if base is not None and variant_mean is not None else None})
    variation_types = defaultdict(list)
    for family in families.values():
        base = next((row["official_total"] for row in family if row.get("variant_id") == "base"), None)
        for row in family:
            if base is not None and row["official_total"] is not None:
                for kind in row.get("variation_types", []):
                    variation_types[kind].append(row["official_total"] - base)
    complete_robustness = len(robustness) == 15 and all(row["base_score"] is not None and row["variant_mean"] is not None for row in robustness)
    robustness_summary = {
        "base_mean": mean(row["base_score"] for row in robustness) if complete_robustness else None,
        "variant_mean": mean(row["variant_mean"] for row in robustness) if complete_robustness else None,
        "mean_delta": mean(row["variant_minus_base"] for row in robustness) if complete_robustness else None,
        "complete_family_pairs": sum(row["variant_minus_base"] is not None for row in robustness),
    }
    locked = state.get("policy_descriptor", {}).get("locked_policy", {})
    cohort = {key: locked.get(key) for key in ("judge", "generation", "evaluation", "runtime_protocol", "instance_data")}
    cohort.update(track=selection["track"], contract_manifest_sha256=state.get("contract_manifest_sha256"))
    return {"run_id": state.get("run_id", root.name), "status": state.get("status"),
            "selection": selection, "model": state.get("selected_model"),
            "cohort_sha256": hashlib.sha256(json.dumps(cohort, sort_keys=True, default=str).encode()).hexdigest(),
            "planned_count": len(records), "counts": dict(counts),
            "scored_count": sum(row["official_total"] is not None for row in records),
            "coverage": sum(row["official_total"] is not None for row in records) / len(records) if records else 0,
            "eligible_for_ranking": complete, "official_score": aggregate, "dimensions": dimensions,
            "elapsed_seconds": elapsed(state.get("created_at"), state.get("finished_at")),
            "robustness": robustness, "robustness_summary": robustness_summary,
            "variation_type_analysis": {kind: {"available_pairs": len(values), "mean_delta": mean(values)} for kind, values in variation_types.items()},
            "variation_type_note": "Descriptive available pairs; an instance may carry multiple types. Incomplete pairs are counted, not treated as zero.",
            "tasks": records}


def write_track_report(run_dir: Path, state: Mapping[str, Any]):
    result = inspect_run(run_dir, state)
    result["api_usage"] = api_usage(run_dir)
    write_json(run_dir / "track_report.json", result)
    return result


def combined_report(run_dirs: Sequence[Path]):
    groups = defaultdict(list)
    historical = []
    for root in run_dirs:
        report = inspect_run(root)
        if report["selection"]["track"] == "historical":
            historical.append(report)
        else:
            groups[(report["selection"]["track"], report.get("cohort_sha256"))].append(report)
    return {"groups": [{"track": track, "cohort_sha256": cohort,
                         "leaderboard": sorted([run for run in runs if run.get("eligible_for_ranking")], key=lambda r: -r["official_score"]),
                         "incomplete_or_subset_runs": [run for run in runs if not run.get("eligible_for_ranking")]}
                        for (track, cohort), runs in groups.items()], "historical_runs": historical}
