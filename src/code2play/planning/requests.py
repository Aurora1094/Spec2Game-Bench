"""Compile and sample a candidate while planning, but never sending, score calls."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from code2play.execution.candidate_project import CandidateProject
from code2play.d4.contracts import build_round_contracts, load_round_contract
from code2play.d4.questions import build_d43_question_pack_single_pass
from code2play.evaluation.dimensions.d2.protocol_evaluator import (
    BATCH_CHECKPOINT_JUDGE_INSTRUCTIONS,
    DEVIATION_JUDGE_INSTRUCTIONS,
    DIMENSIONS,
    _deviation_prompt,
    _dimension_batch_prompt,
    _partition_dimension_batches,
)
from code2play.evaluation.dimensions.d3.judge import D3_JUDGE_INSTRUCTIONS, build_judge_prompt
from code2play.evaluation.dimensions.d4.semantic_ux import _evaluate_d41, _evaluate_d42, _evaluate_d43
from code2play.providers.dashscope import (
    JudgeRouter,
    ModelRequest,
    RoutedSemanticJudge,
    resolve_judge_route,
    _model_visible_texts,
)
from code2play.execution.protocol_sampling import sample_evaluation_protocol
from code2play.config.project import GameConfig, normalized_policy_sha256
from code2play.generation.prompt_builder import build_stage_prompt, load_spec
from code2play.execution.safe_artifacts import redact_text, write_json


_FORBIDDEN_DIMENSION = re.compile(
    r"(?<![A-Za-z0-9_])D[1-4](?:[._][1-9][0-9]*)?(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_FORBIDDEN_CHECKPOINT = re.compile(
    r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9_]*\.D[1-4](?:\.[0-9]+)+",
    re.IGNORECASE,
)
_FIXED_SCORING_PURPOSES = (
    "d2_specification_deviation",
    "d3_semantic_code_quality",
    "d4_1_artistic_visual_quality",
    "d4_2_batch_D2.2",
    "d4_2_batch_D2.3",
    "d4_2_batch_D2.4",
    "d4_2_batch_D2.5",
    "d4_3_questions_single_pass",
    "d4_3_question_batch",
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _estimate_text_tokens(*values: str) -> int:
    # A transparent provider-independent heuristic: CJK ~= 1 token/codepoint;
    # other text/code ~= 4 characters/token.
    units = 0.0
    for value in values:
        units += sum(1.0 if ord(char) > 127 else 0.25 for char in value)
    return max(1, math.ceil(units))


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()[:24]
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    try:
        from PIL import Image

        with Image.open(path) as image:
            return int(image.width), int(image.height)
    except Exception:
        return 0, 0


def _image_record(path: Path, label: str) -> dict[str, Any]:
    width, height = _png_dimensions(path)
    pixels = width * height
    return {
        "path": str(path.resolve()),
        "label": label,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "width": width,
        "height": height,
        "pixels": pixels,
        # Qwen-VL-family planning heuristic; actual provider accounting wins.
        "estimated_tokens": math.ceil(pixels / 784) if pixels else 0,
    }


class PlanningJudge:
    """Record sanitized model-visible requests and return transient scaffolding.

    The scaffolding exists only to discover dependent request shapes. It is
    never written as a score or included in the plan artifact.
    """

    def __init__(self, judge_config: Mapping[str, Any]) -> None:
        self.judge_config = judge_config
        self.requests: list[dict[str, Any]] = []

    def _record(
        self,
        instructions: str,
        prompt: str,
        images: Sequence[tuple[Path, str]],
        purpose: str,
    ) -> None:
        visible = _model_visible_texts(
            instructions, prompt, *(label for _path, label in images)
        )
        safe_instructions = redact_text(visible[0])
        safe_prompt = redact_text(visible[1])
        labels = visible[2:]
        role = RoutedSemanticJudge._role(purpose)
        route = resolve_judge_route(self.judge_config, role)
        image_records = [
            _image_record(path, label)
            for (path, _old_label), label in zip(images, labels, strict=True)
        ]
        if _FORBIDDEN_DIMENSION.search(safe_instructions + "\n" + safe_prompt):
            raise ValueError("planned model input contains an internal dimension label")
        if _FORBIDDEN_CHECKPOINT.search(safe_instructions + "\n" + safe_prompt):
            raise ValueError("planned model input contains an internal checkpoint id")
        self.requests.append(
            {
                "request_id": purpose,
                "role": role,
                "modality": "vision" if images else "text",
                "provider": route["provider"],
                "model": route["model"],
                "enable_thinking": bool(route.get("enable_thinking", False)),
                "max_output_tokens": int(route["max_output_tokens"]),
                "send": False,
                "status": "planned_not_sent",
                "instructions": safe_instructions,
                "prompt": safe_prompt,
                "instructions_sha256": _sha256_text(safe_instructions),
                "prompt_sha256": _sha256_text(safe_prompt),
                "estimated_text_input_tokens": _estimate_text_tokens(
                    safe_instructions, safe_prompt, *labels
                ),
                "estimated_image_input_tokens": sum(
                    item["estimated_tokens"] for item in image_records
                ),
                "images": image_records,
            }
        )

    @staticmethod
    def _ids(pattern: str, prompt: str) -> list[str]:
        return list(dict.fromkeys(re.findall(pattern, prompt)))

    def json_text(self, instructions: str, prompt: str, purpose: str) -> dict[str, Any]:
        self._record(instructions, prompt, (), purpose)
        if purpose.startswith("d2_dimension_"):
            match = re.fullmatch(
                r"d2_dimension_(D2\.\d)(?:_batch_\d+)?", purpose
            )
            if match is None:
                raise KeyError(f"No planning scaffold for text purpose {purpose!r}")
            dimension = match.group(1)
            ids = self._ids(r'"checkpoint_id"\s*:\s*"([^"]+)"', prompt)
            return {
                "dimension": dimension,
                "results": [
                    {
                        "checkpoint_id": item,
                        "score": 0,
                        "evidence": [],
                        "limitations": [],
                        "rationale": "planning scaffold",
                    }
                    for item in ids
                ],
            }
        if purpose == "d2_specification_deviation":
            return {
                "penalties": {dimension: 0 for dimension in DIMENSIONS},
                "assigned_extras": [],
                "rationale": {dimension: "planning scaffold" for dimension in DIMENSIONS},
            }
        if purpose == "d3_semantic_code_quality":
            return {"scores": {key: 0 for key in (
                "maintainability", "reliability", "security", "efficiency", "conformance"
            )}}
        raise KeyError(f"No planning scaffold for text purpose {purpose!r}")

    def json_vision(
        self,
        instructions: str,
        prompt: str,
        images: Sequence[tuple[Path, str]],
        purpose: str,
    ) -> dict[str, Any]:
        self._record(instructions, prompt, images, purpose)
        if purpose == "d4_1_artistic_visual_quality":
            return {
                "dimension": "D4.1",
                "score": 0,
                "criterion_scores": {key: 0 for key in (
                    "composition_and_hierarchy", "palette_and_contrast",
                    "shape_and_style_consistency", "polish", "dynamic_presentation"
                )},
                "evidence": [], "limitations": [], "rationale": "planning scaffold",
            }
        if purpose.startswith("d4_2_batch_"):
            payload = json.loads(prompt)
            return {"results": [
                {
                    "checkpoint_id": row["checkpoint"]["id"],
                    "faithfulness": 0, "completeness": 0, "timeliness": 0,
                    "evidence": [], "limitations": [], "rationale": "planning scaffold",
                }
                for row in payload["transition_batch"]
            ]}
        if purpose == "d4_3_questions_single_pass":
            payload = json.loads(prompt)
            contexts = payload.get("assigned_source_context", [])
            if not isinstance(contexts, list) or len(contexts) != 2:
                raise ValueError("planning D4.3 prompt has no two fixed source contexts")
            evidence = payload.get("real_evidence_index", [])
            slots = payload.get("source_checkpoint_slots", [])
            selected: list[dict[str, Any]] = []
            if isinstance(evidence, list) and isinstance(slots, list):
                used_hashes: set[str] = set()
                for source in slots:
                    match = next(
                        (
                            item for item in evidence
                            if isinstance(item, dict)
                            and item.get("source_checkpoint_id") == source
                            and item.get("image_sha256") not in used_hashes
                        ),
                        None,
                    )
                    if match is not None:
                        selected.append(match)
                        used_hashes.add(str(match.get("image_sha256")))
            if len(selected) != 2:
                selected = [
                    {
                        "evidence_id": f"planned_evidence_{index + 1:03d}",
                        "source_checkpoint_id": context.get("id", ""),
                    }
                    for index, context in enumerate(contexts)
                ]
            operations = list(payload.get("allowed_operations", []))
            while len(operations) < 2:
                operations.append(f"Operation {len(operations) + 1}")
            return {"questions": [
                {
                    "source_slot": index + 1,
                    "evidence_id": item["evidence_id"],
                    "options": {"A": operations[0], "B": operations[1]},
                    "correct_choice": "A" if index == 0 else "B",
                    "answer_rationale": "Planning-only structure for the dependent request.",
                }
                for index, item in enumerate(selected)
            ]}
        if purpose == "d4_3_question_batch":
            payload = json.loads(prompt)
            return {"answers": [
                {
                    "question_id": row["question"]["id"],
                    "choice": "A", "confidence": 0.0,
                    "evidence_image_ids": [row["image_id"]],
                    "reason": "planning scaffold",
                }
                for row in payload["questions"]
            ]}
        raise KeyError(f"No planning scaffold for vision purpose {purpose!r}")


def _generation_requests(
    game: GameConfig,
    candidate: CandidateProject,
    config: Mapping[str, Any],
) -> list[dict[str, Any]]:
    stage_limits = {
        item["id"]: int(item["max_output_tokens"])
        for item in config["generation"]["stages"]
    }
    requests: list[dict[str, Any]] = []
    for stage in ("state", "game", "rendering", "main"):
        built = build_stage_prompt(
            game_slug=game.slug,
            stage=stage,  # type: ignore[arg-type]
            locked_project=candidate if stage != "state" else None,
            generation_config=config["generation"],
        )
        if _FORBIDDEN_DIMENSION.search(built.text) or _FORBIDDEN_CHECKPOINT.search(built.text):
            raise ValueError(f"generation stage {stage} contains an internal evaluator label")
        request = ModelRequest(
            request_id=f"generation_{stage}",
            role="generation",
            modality="text",
            instructions="",
            prompt=built.text,
            max_output_tokens=stage_limits[stage],
        )
        row = asdict(request)
        row.update({
            "model": "qwen3.7-plus",
            "provider": "alibaba_dashscope",
            "enable_thinking": True,
            "send": False,
            "status": "reconstructed_for_budget_only",
            "prompt_sha256": built.sha256,
            "estimated_text_input_tokens": _estimate_text_tokens(built.text),
            "estimated_image_input_tokens": 0,
        })
        requests.append(row)
    return requests


def _compiler_usage(log_root: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    requests: list[dict[str, Any]] = []
    totals = {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0,
              "cached_tokens": 0, "attempts": 0}
    for raw_input_path in sorted(log_root.rglob("raw_input.json")):
        raw_input = json.loads(raw_input_path.read_text(encoding="utf-8"))
        result_path = raw_input_path.with_name("request_result.json")
        result = (
            json.loads(result_path.read_text(encoding="utf-8"))
            if result_path.is_file() else {}
        )
        result_attempts = result.get("attempts") if isinstance(result, dict) else None
        if isinstance(result_attempts, list):
            usages = [
                item["usage"]
                for item in result_attempts
                if isinstance(item, dict) and isinstance(item.get("usage"), dict)
            ]
            attempts_made = int(result.get("attempts_made") or len(result_attempts))
        else:
            # Legacy flat logs remain readable for old artifacts, but cannot be
            # used as verified compiler cache entries because they lack a parsed
            # response tied to one logical request.
            raw_response_path = raw_input_path.with_name("raw_response.json")
            raw_response = (
                json.loads(raw_response_path.read_text(encoding="utf-8"))
                if raw_response_path.is_file() else {}
            )
            final_usage = raw_response.get("usage", {}) if isinstance(raw_response, dict) else {}
            attempt_usages = raw_input.get("attempt_usages")
            usages = (
                [item for item in attempt_usages if isinstance(item, dict)]
                if isinstance(attempt_usages, list)
                else [final_usage] if isinstance(final_usage, dict) else []
            )
            attempts_made = int(raw_input.get("request_attempts") or 1)

        def usage_total(*names: str) -> int:
            return sum(
                int(next((item.get(name) for name in names if item.get(name) is not None), 0) or 0)
                for item in usages
            )
        current = {
            "input_tokens": usage_total("prompt_tokens", "input_tokens"),
            "output_tokens": usage_total("completion_tokens", "output_tokens"),
            "reasoning_tokens": sum(
                int((item.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
                for item in usages if isinstance(item.get("completion_tokens_details"), dict)
            ),
            "cached_tokens": sum(
                int((item.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
                for item in usages if isinstance(item.get("prompt_tokens_details"), dict)
            ),
            "attempts": attempts_made,
        }
        for key, value in current.items():
            totals[key] += value
        requests.append({
            "request_id": raw_input.get("purpose"),
            "role": "action_compiler",
            "modality": "text",
            "model": raw_input.get("model"),
            "provider": raw_input.get("provider"),
            "enable_thinking": raw_input.get("enable_thinking"),
            "max_output_tokens": raw_input.get("max_output_tokens"),
            "send": True,
            "status": "sent_for_real_sampling",
            "usage": current,
            "artifact_dir": str(raw_input_path.parent.resolve()),
        })
    return requests, totals


def _budget(rows: Sequence[Mapping[str, Any]], *, actual: bool = False) -> dict[str, Any]:
    if actual:
        return {
            "requests": len(rows),
            "text_input_tokens": sum(int(row.get("usage", {}).get("input_tokens", 0)) for row in rows),
            "image_input_tokens": 0,
            "output_tokens": sum(int(row.get("usage", {}).get("output_tokens", 0)) for row in rows),
            "reasoning_tokens": sum(int(row.get("usage", {}).get("reasoning_tokens", 0)) for row in rows),
            "cached_tokens": sum(int(row.get("usage", {}).get("cached_tokens", 0)) for row in rows),
            "basis": "actual_dashscope_usage",
        }
    return {
        "requests": len(rows),
        "text_input_tokens": sum(int(row.get("estimated_text_input_tokens", 0)) for row in rows),
        "image_input_tokens": sum(int(row.get("estimated_image_input_tokens", 0)) for row in rows),
        "output_tokens": sum(int(row.get("max_output_tokens", 0)) for row in rows),
        "basis": "transparent_upper_budget_and_local_token_heuristic",
    }


def run_request_plan(
    *,
    game: GameConfig,
    candidate: CandidateProject,
    run_dir: Path,
    run_id: str | None = None,
    round_dir: Path | None = None,
    round_id: str | None = None,
    config: dict[str, Any],
    input_price_per_million: float | None = None,
    output_price_per_million: float | None = None,
    currency: str = "USD",
) -> dict[str, Any]:
    """Send only compilation requests; sample reality; plan all later calls."""

    root = Path(run_dir).resolve()
    evidence_dir = root / "evidence"
    router = JudgeRouter(config["judge"], root / "model_calls")
    locked_round_dir = (
        Path(round_dir).resolve()
        if round_dir is not None
        else root / "round"
    )
    round_manifest = build_round_contracts(
        locked_round_dir,
        [game],
        config=config,
        generator=router.for_role("contract_generation"),
        round_id=round_id or locked_round_dir.name,
    )
    contract_manifest_sha256 = str(round_manifest["manifest_sha256"])
    sample_manifest = sample_evaluation_protocol(
        project=candidate,
        spec_path=game.spec,
        evidence_dir=evidence_dir,
        timeout_sec=int(config["evaluation"]["sampling_timeout_seconds"]),
        d2_max_workers=int(config["evaluation"]["d2_workers"]),
        checkpoint_compiler=router.for_role("action_compiler"),
    )
    spec = load_spec(game.spec)
    checkpoints = list(spec["evaluation"]["d2"]["checkpoints"])
    trace_by_id = {item["id"]: item for item in sample_manifest["d2"]}
    source = candidate.source_bundle()
    planner = PlanningJudge(config["judge"])
    d2_scoring_purposes: list[str] = []

    for dimension in DIMENSIONS:
        batchable = [
            item
            for item in checkpoints
            if item["dimension"] == dimension
            and "score_rubric" in item
            and trace_by_id[item["id"]].get("status")
            not in {"sampling_failed", "not_run_adapter_contract"}
        ]
        for batch_index, (batch, _prompt_characters) in enumerate(
            _partition_dimension_batches(
                dimension,
                batchable,
                trace_by_id,
                source,
                spec.get("body", ""),
            ),
            start=1,
        ):
            purpose = f"d2_dimension_{dimension}_batch_{batch_index:02d}"
            d2_scoring_purposes.append(purpose)
            planner.json_text(
                BATCH_CHECKPOINT_JUDGE_INSTRUCTIONS,
                _dimension_batch_prompt(
                    dimension,
                    batch,
                    trace_by_id,
                    source,
                    spec.get("body", ""),
                ),
                purpose=purpose,
            )
    planner.json_text(
        DEVIATION_JUDGE_INSTRUCTIONS,
        _deviation_prompt(
            source,
            {"game_description": spec.get("body", ""), "functional_checkpoints": spec["checkpoints"]},
            spec["evaluation"]["d2"],
        ),
        purpose="d2_specification_deviation",
    )
    planner.json_text(
        D3_JUDGE_INSTRUCTIONS,
        build_judge_prompt(source),
        purpose="d3_semantic_code_quality",
    )

    contract = load_round_contract(
        locked_round_dir,
        game.slug,
        expected_manifest_sha256=contract_manifest_sha256,
        d2_checkpoints=checkpoints,
    )
    visual_manifest = {
        **sample_manifest,
        "d4_contract_source": "round_locked_manifest",
        "d4_contract_path": str((locked_round_dir / "contracts" / f"{game.slug}.json").resolve()),
        "d4_contract_version": contract["contract_version"],
        "d4_contract_sha256": contract["contract_sha256"],
        "d4_contract_design_version": contract["design_version"],
        "d4_contract_manifest_sha256": contract_manifest_sha256,
        "d4_compiler": "reused_functionality_compiled_programs",
        "d4_2_checkpoint_selection": "kind_dynamic_only",
        "candidate_received_d4_task_ids": False,
        "candidate_received_d4_contract": False,
    }
    try:
        _evaluate_d41(contract, visual_manifest, planner)
        _evaluate_d42(checkpoints, visual_manifest, planner)
        question_pack = build_d43_question_pack_single_pass(
            d4_contract=contract,
            d2_checkpoints=checkpoints,
            sample_manifest=visual_manifest,
            candidate_project_sha256=candidate.project_sha256(),
            generator=planner,
        )
        _evaluate_d43(contract, question_pack, planner)
    except (StopIteration, ValueError, KeyError):
        # Evidence-dependent calls may be impossible after a real render failure.
        # The fixed logical request slots are added below with an explicit condition.
        pass

    scoring_purposes = [*d2_scoring_purposes, *_FIXED_SCORING_PURPOSES]
    recorded = {row["request_id"]: row for row in planner.requests}
    for purpose in scoring_purposes:
        if purpose in recorded:
            continue
        role = RoutedSemanticJudge._role(purpose)
        route = config["judge"]["routes"][role]
        planner.requests.append({
            "request_id": purpose,
            "role": role,
            "modality": "vision" if role in {
                "artistic_visual", "dynamic_visual", "question_generation", "question_answering"
            } else "text",
            "provider": route["provider"],
            "model": route["model"],
            "enable_thinking": False,
            "max_output_tokens": int(route["max_output_tokens"]),
            "send": False,
            "status": "planned_conditionally_unavailable_real_evidence",
            "estimated_text_input_tokens": 0,
            "estimated_image_input_tokens": 0,
            "images": [],
        })
    purpose_order = {purpose: index for index, purpose in enumerate(scoring_purposes)}
    planner.requests.sort(
        key=lambda row: (purpose_order.get(str(row["request_id"]), len(purpose_order)), str(row["request_id"]))
    )

    generation_requests = _generation_requests(game, candidate, config)
    compiler_requests, compiler_actual = _compiler_usage(root / "model_calls" / "action_compiler")
    generation_budget = _budget(generation_requests)
    compilation_budget = _budget(compiler_requests, actual=True)
    scoring_budget = _budget(planner.requests)
    total = {
        "requests": generation_budget["requests"] + compilation_budget["requests"] + scoring_budget["requests"],
        "requests_sent": compilation_budget["requests"],
        "text_input_tokens": generation_budget["text_input_tokens"] + compilation_budget["text_input_tokens"] + scoring_budget["text_input_tokens"],
        "image_input_tokens": scoring_budget["image_input_tokens"],
        "output_tokens": generation_budget["output_tokens"] + compilation_budget["output_tokens"] + scoring_budget["output_tokens"],
    }
    pricing: dict[str, Any] | None = None
    if input_price_per_million is not None or output_price_per_million is not None:
        if input_price_per_million is None or output_price_per_million is None:
            raise ValueError("both input and output prices are required")
        input_tokens = total["text_input_tokens"] + total["image_input_tokens"]
        pricing = {
            "currency": currency,
            "input_price_per_million": input_price_per_million,
            "output_price_per_million": output_price_per_million,
            "estimated_total": round(
                input_tokens / 1_000_000 * input_price_per_million
                + total["output_tokens"] / 1_000_000 * output_price_per_million,
                6,
            ),
        }

    inventory = [{
        "id": item["id"],
        "status": item.get("status"),
        "state_trace_path": item.get("trace_path"),
        "visual_status": item.get("visual_status"),
        "frame_count": len(item.get("frames", [])),
        "visual_errors": item.get("visual_errors", []),
    } for item in sample_manifest["d2"]]
    request_manifest = {
        "schema_version": 1,
        "status": "planned_not_scored",
        "credentials_saved": False,
        "generation_requests": generation_requests,
        "actual_compiler_requests": compiler_requests,
        "scoring_requests": planner.requests,
    }
    summary = {
        "schema_version": 1,
        "protocol_version": 4,
        "protocol": "optimized_qwen_single_pass_v2",
        "status": "planned_not_scored",
        "game": game.slug,
        "model": "qwen3.7-plus",
        "candidate_project_sha256": candidate.project_sha256(),
        "normalized_config_sha256": normalized_policy_sha256(config),
        "official_total_present": False,
        "formal_summary_written": False,
        "calls": {
            "generation_reconstructed_not_sent": 4,
            "compilation_base_batches": int(
                sample_manifest.get("compiler_parallelism", {}).get(
                    "base_batch_count", 0
                )
            ),
            "compilation_local_repairs": int(
                sample_manifest.get("compiler_parallelism", {}).get(
                    "repair_count", 0
                )
            ),
            "compilation_sent": len(compiler_requests),
            "scoring_constructed_not_sent": len(planner.requests),
        },
        "token_budget": {
            "generation": generation_budget,
            "action_compilation": {**compilation_budget, "usage_totals": compiler_actual},
            "scoring": scoring_budget,
            "total": total,
            "estimation_notes": [
                "CJK text is estimated at one token per codepoint and other text at four characters per token.",
                "Image tokens use ceil(width*height/784) only for planning; provider usage is authoritative.",
                "Planned output is the configured maximum, not a prediction of actual completion length.",
            ],
        },
        "pricing": pricing,
        "artifacts": {
            "request_manifest": str((root / "sanitized_request_manifest.json").resolve()),
            "sample_inventory": str((root / "sample_inventory.json").resolve()),
            "plan_state": str((root / "plan_state.json").resolve()),
            "sample_manifest": sample_manifest.get("manifest_path"),
        },
    }
    plan_state = {
        "schema_version": 1,
        "protocol_version": 4,
        "protocol": "optimized_qwen_single_pass_v2",
        "status": "planned_not_scored",
        "game": game.slug,
        "run_id": run_id or root.name,
        "candidate_project_sha256": candidate.project_sha256(),
        "normalized_config_sha256": normalized_policy_sha256(config),
        "official_total_present": False,
        "formal_summary_written": False,
    }
    write_json(root / "sanitized_request_manifest.json", request_manifest)
    write_json(root / "sample_inventory.json", inventory)
    write_json(root / "plan_state.json", plan_state)
    write_json(root / "plan_summary.json", summary)
    return summary


__all__ = ["PlanningJudge", "run_request_plan"]
