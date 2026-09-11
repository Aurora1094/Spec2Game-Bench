"""Measured workload projections; no requests, prices or scores are invented."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path

from code2play.config.project import game_by_slug, games, models
from code2play.generation.prompt_builder import load_evaluator_checkpoints, load_spec
from code2play.providers.dashscope import resolve_judge_route
from code2play.reporting.tracks import api_usage, inspect_run, number, read_json


def _workload(config, ids):
    checkpoints = dynamic = 0
    for slug in ids:
        rows = load_evaluator_checkpoints(load_spec(game_by_slug(config, slug).spec))
        checkpoints += len(rows)
        dynamic += sum(row["kind"] == "dynamic" for row in rows)
    return {"generation": len(ids), "text_judge": checkpoints,
            "vision_judge": dynamic, "contracts": len(ids)}


def load_prices(path):
    if path is None:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not payload.get("as_of") or not isinstance(payload.get("models"), dict):
        raise ValueError("Price file requires as_of and models; rates are USD per million tokens")
    for model, rate in payload["models"].items():
        for field in ("input_usd_per_million", "output_usd_per_million"):
            if number(rate.get(field)) is None or rate[field] < 0:
                raise ValueError(f"Invalid price for {model}.{field}")
        if "cached_input_usd_per_million" in rate and (number(rate["cached_input_usd_per_million"]) is None or rate["cached_input_usd_per_million"] < 0):
            raise ValueError(f"Invalid cache price for {model}")
    return payload


def project_budget(config, reference_runs, *, price_snapshot=None, round_dir=None):
    prices = (price_snapshot or {}).get("models", {})
    target_ids = [game.slug for game in games(config)]
    target = _workload(config, target_ids)
    target_models = {
        "generation": models(config)[0].model,
        "text_judge": resolve_judge_route(config["judge"], "functionality")["model"],
        "vision_judge": resolve_judge_route(config["judge"], "artistic_visual")["model"],
        "contracts": resolve_judge_route(config["judge"], "contract_generation")["model"],
    }
    samples = defaultdict(list)
    seen_rounds = set()
    excluded = []
    for root in dict.fromkeys(Path(path).resolve() for path in reference_runs):
        report = inspect_run(root)
        state = read_json(root / "run_state.json")
        for task in report.get("tasks", []):
            if task.get("status") != "completed":
                excluded.append({"run_id": root.name, "task_id": task.get("task_id"), "reason": "unfinished task has incomplete workload"})
                continue
            weights = _workload(config, [task["game"]])
            ledger = api_usage(Path(task["task_dir"]), prices)
            if ledger["pending_requests"]:
                excluded.append({"run_id": root.name, "task_id": task.get("task_id"), "reason": "unfinalized API request logs leave usage unknown"})
                continue
            sampling = read_json(Path(task["task_dir"]) / "evaluation/sample_manifest.json")
            judge_skipped = sampling.get("compiler_parallelism", {}).get("status") == "not_run_adapter_contract"
            if judge_skipped:
                excluded.append({"run_id": root.name, "task_id": task.get("task_id"),
                                 "categories": ["text_judge", "vision_judge"],
                                 "reason": "candidate adapter initialization failed; full Judge workload was not executed"})
            for row in ledger["models"]:
                if judge_skipped and row["category"] in {"text_judge", "vision_judge"}:
                    continue
                if row["category"] != "contracts":
                    samples[row["category"]].append((row, weights[row["category"]]))
        if state.get("round_id"):
            shared = root.parent.parent / "rounds" / state["round_id"]
            if shared in seen_rounds:
                continue
            seen_rounds.add(shared)
            manifest = read_json(shared / "contracts/manifest.json")
            for row in api_usage(shared / "contracts", prices)["models"]:
                if row["category"] == "contracts" and manifest.get("games"):
                    samples["contracts"].append((row, len(manifest["games"])))
    shared_manifest = read_json(Path(round_dir) / "contracts/manifest.json") if round_dir else {}
    target["contracts"] = len(set(target_ids) - set(shared_manifest.get("games", [])))
    result = []
    for category, model in target_models.items():
        observed = samples[category]
        weight = sum(w for _, w in observed)
        scale = target[category] / weight if weight else None
        missing_usage = sum(item["missing_usage_attempts"] for item, _ in observed)
        row = {"category": category, "model": model, "workload_units": target[category],
               "reference_units": weight, "input_tokens": None, "output_tokens": None,
               "reference_missing_usage_attempts": missing_usage,
               "image_input_tokens": None, "text_input_tokens": None, "images_sent": None,
               "cost_usd": None, "retry_cost_usd": None, "explicit_resume_cost_usd": None}
        if target[category] == 0:
            row.update(input_tokens=0, output_tokens=0, images_sent=0, cost_usd=0.0)
        elif scale is not None and not missing_usage:
            for field in ("input_tokens", "output_tokens", "cached_input_tokens", "images_sent", "retry_attempts", "explicit_resume_attempts"):
                row[field] = sum(item[field] for item, _ in observed) * scale
            for field in ("image_input_tokens", "text_input_tokens"):
                if all(item[field] is not None for item, _ in observed):
                    row[field] = sum(item[field] for item, _ in observed) * scale
            if all(item["model"] == model and item["cost_usd"] is not None for item, _ in observed):
                for field in ("cost_usd", "retry_cost_usd", "explicit_resume_cost_usd"):
                    row[field] = sum(item[field] for item, _ in observed) * scale
            elif model in prices:
                rate = prices[model]
                cached = row["cached_input_tokens"]
                row["cost_usd"] = ((row["input_tokens"] - cached) * rate["input_usd_per_million"]
                                   + cached * rate.get("cached_input_usd_per_million", rate["input_usd_per_million"])
                                   + row["output_tokens"] * rate["output_usd_per_million"]) / 1_000_000
        result.append(row)
    caps = sum(int(stage["max_output_tokens"]) for stage in config["generation"]["stages"])
    return {"status": "estimated_from_measurements" if samples else "needs_reference_measurements",
            "selection": config["selection"], "candidate_count": len(target_ids),
            "normal_generation_calls": 4 * len(target_ids),
            "generation_output_cap": caps * len(target_ids),
            "generation_two_attempt_output_cap": 2 * caps * len(target_ids),
            "human_item_count": 10 * len(target_ids), "categories": result,
            "total_estimated_usd": sum(row["cost_usd"] for row in result) if all(row["cost_usd"] is not None for row in result) else None,
            "prices_as_of": (price_snapshot or {}).get("as_of"), "excluded_samples": excluded,
            "method": "Generation per candidate; text Judge per checkpoint; vision Judge per dynamic checkpoint; shared contracts per instance, once per round. Retries and explicit resumes are included in observed consumption.",
            "limitations": ["Pilot-based extrapolation is not a spending limit: prompt size, evidence and batching vary by instance and model.",
                            "Output caps are limits, not expected usage. Later explicit regeneration cycles are additional.",
                            "Provider image tokens are included in input tokens; unavailable image/text splits remain null."]}
