"""Candidate-level D4.3 visual questions with deterministic evidence binding."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from code2play.d4.contracts import (
    CONTRACT_GENERATOR_MODEL,
    CONTRACT_VALIDATOR_MODELS,
    D43_QUESTION_COUNT,
    D43_QUESTION_TEXT,
    RUNTIME_QUESTION_POLICY,
)
from code2play.d4.visual_difference import (
    VISUAL_DIFFERENCE_POLICY,
    analyze_visual_difference,
    select_materially_distinct_frames,
)
from code2play.execution.safe_artifacts import redact_text
from code2play.providers.dashscope import SemanticJudge


QUESTION_PACK_SCHEMA_VERSION = 2
QUESTION_PACK_DESIGN_VERSION = "d4_qwen37_dynamic_fixed_binding_target_aware_v3"
QUESTION_REVIEW_POLICY = "single_qwen_generation_with_fixed_local_binding_target_aware_v5"
EVIDENCE_SELECTION_POLICY = "deterministic_material_pair_declared_active_target_v3"
MAX_D43_EVIDENCE_IMAGES = 12
MIN_REVIEW_CONFIDENCE = 0.7
_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_CONTROL_TOKEN_PATTERN = re.compile(
    r"\b(?:[A-Z]|[1-9]|space|left|right|up|down|enter|escape)\b",
    re.IGNORECASE,
)

GENERATOR_INSTRUCTIONS = """
You create exactly two evaluator-only multiple-choice question records from
the two supplied screenshots of one generated game. The candidate source is
not provided. The evaluator has already assigned image one to question one and
image two to question two. Do not select, name, swap, or change evidence.
Return one JSON object containing exactly two questions. Each question must
contain options A and B and a correct_choice. Both options must be concrete
legal game-level operations, and exactly one must be visibly and strategically
best for the fixed target. A target-specific contract may distinguish
operations by target even when they share one physical control; preserve that
distinction and use the supplied descriptions exactly. A legal target that is
not currently visible may be used only as a distractor, never as an empty,
background, waiting, restart, or other no-op action. Do not use lifecycle-only
or unavailable operations. Every rationale must be English.
Use the operation strings from the supplied allowed_operations list exactly.
The two options must be distinct; never repeat the same operation, even when
the screenshot suggests that one operation is clearly preferable.
    """.strip()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def question_pack_sha256(pack: Mapping[str, Any]) -> str:
    payload = dict(pack)
    payload.pop("question_pack_sha256", None)
    return _sha(_canonical(payload))


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _english(value: Any, label: str) -> str:
    result = _nonempty(value, label)
    if _CJK_PATTERN.search(result):
        raise ValueError(f"{label} must be in English")
    return result


def _operation_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().rstrip(".")).casefold()


def _operation_aliases(
    allowed_operations: Sequence[str],
) -> tuple[dict[str, str], list[str]]:
    """Expand grouped keyboard descriptions into concrete, deterministic choices."""

    aliases: dict[str, str] = {}
    concrete: list[str] = []
    for raw_operation in allowed_operations:
        operation = str(raw_operation)
        aliases.setdefault(_operation_key(operation), operation)
        active_verb: str | None = None
        for segment in operation.split(","):
            prefix = re.split(r"\b(?:to|while)\b", segment, maxsplit=1, flags=re.IGNORECASE)[0]
            verb_match = re.search(r"\b(press|hold)\b", prefix, flags=re.IGNORECASE)
            if verb_match is not None:
                active_verb = verb_match.group(1).casefold()
            if active_verb is None:
                continue
            for match in _CONTROL_TOKEN_PATTERN.finditer(prefix):
                token = match.group(0)
                label = token.upper() if len(token) == 1 else token.title()
                canonical = f"{active_verb} {label}"
                aliases.setdefault(_operation_key(canonical), canonical)
                if canonical not in concrete:
                    concrete.append(canonical)
    return aliases, concrete


def _question_operations(
    allowed_operations: Sequence[str],
    operation_policy: Mapping[str, Any] | None = None,
) -> list[str]:
    if (
        isinstance(operation_policy, Mapping)
        and operation_policy.get("mode") == "target_specific"
    ):
        policy_operations = operation_policy.get("operations")
        if isinstance(policy_operations, list):
            descriptions = [
                str(item.get("description"))
                for item in policy_operations
                if isinstance(item, Mapping)
                and str(item.get("description") or "").strip()
            ]
            if len(descriptions) == len(policy_operations):
                return descriptions
    _aliases, concrete = _operation_aliases(allowed_operations)
    return concrete or [str(operation) for operation in allowed_operations]


def _normalize_options(
    value: Any,
    label: str,
    allowed_operations: Sequence[str],
    operation_policy: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    if not isinstance(value, Mapping) or list(value) != ["A", "B"]:
        raise ValueError(f"{label} must contain exactly ordered choices A and B")
    options = {key: _english(value[key], f"{label}.{key}") for key in ("A", "B")}
    if options["A"] == options["B"]:
        raise ValueError(f"{label} choices must differ")
    if (
        isinstance(operation_policy, Mapping)
        and operation_policy.get("mode") == "target_specific"
    ):
        allowed = {
            _operation_key(str(operation)): str(operation)
            for operation in allowed_operations
        }
    else:
        allowed, _concrete = _operation_aliases(allowed_operations)
    normalized: dict[str, str] = {}
    for key, operation in options.items():
        canonical = allowed.get(_operation_key(operation))
        if canonical is None:
            raise ValueError(f"{label}.{key} is not one of the contract operations")
        normalized[key] = canonical
    if normalized["A"] == normalized["B"]:
        raise ValueError(f"{label} choices must differ after normalization")
    return normalized


def _file_sha256(path: Path) -> str:
    return _sha(path.read_bytes())


def _even_indices(length: int, limit: int) -> list[int]:
    if length <= limit:
        return list(range(length))
    if limit == 1:
        return [0]
    return sorted({round(index * (length - 1) / (limit - 1)) for index in range(limit)})


def _public_evidence(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item[key]
        for key in (
            "evidence_id", "source_checkpoint_id", "case", "phase",
            "relative_time_seconds", "snapshot", "image_sha256", "evidence_sha256",
        )
    }


def _target_specific_target_tokens(
    operation_policy: Mapping[str, Any] | None,
) -> list[tuple[str, ...]]:
    """Return the authored target classes used to recognize live evidence."""

    if not isinstance(operation_policy, Mapping) or operation_policy.get("mode") != "target_specific":
        return []
    operations = operation_policy.get("operations")
    if not isinstance(operations, list):
        return []
    targets: list[tuple[str, ...]] = []
    for operation in operations:
        if not isinstance(operation, Mapping):
            continue
        tokens = tuple(
            token
            for token in re.split(r"[^a-z0-9]+", str(operation.get("target", "")).casefold())
            if token
        )
        if tokens and tokens not in targets:
            targets.append(tokens)
    return targets


def _frame_has_identifiable_active_target(
    frame: Mapping[str, Any],
    operation_policy: Mapping[str, Any] | None,
) -> bool:
    """Require target-specific question evidence to describe a visible target.

    The D4.2 frame and its snapshot are captured from the same adapter state.
    For game-authored target-specific policies, a snapshot must therefore name
    one authoritative target class and indicate that it is live.  This avoids
    turning empty holes, waiting states, or restart screens into D4.3 prompts
    without imposing a state schema on other games.
    """

    targets = _target_specific_target_tokens(operation_policy)
    if not targets:
        return True
    snapshot = frame.get("snapshot")
    if not isinstance(snapshot, Mapping):
        return False
    try:
        text = json.dumps(snapshot, ensure_ascii=False, sort_keys=True).casefold()
    except (TypeError, ValueError):
        return False
    tokens = set(re.findall(r"[a-z0-9]+", text))
    has_target = any(all(token in tokens for token in target) for target in targets)
    if not has_target:
        return False
    # Accept common adapter state representations for a currently rendered
    # target while rejecting explicit inactive or hidden states.
    inactive = (
        '"visible": false',
        '"is_visible": false',
        '"active": false',
        '"is_active": false',
        '"exists": false',
        '"status": "hidden"',
        '"status": "inactive"',
        '"status": "waiting"',
    )
    if any(marker in text for marker in inactive):
        return False
    live_markers = (
        '"visible": true',
        '"is_visible": true',
        '"active": true',
        '"is_active": true',
        '"exists": true',
        "current_mole",
        "current_target",
        "active_mole",
        "active_target",
    )
    return any(marker in text for marker in live_markers)


def build_d43_evidence_pool(d4_contract: Mapping[str, Any], sample_manifest: Mapping[str, Any]) -> dict[str, Any]:
    source_slots = list(d4_contract["d4_3"]["source_checkpoint_ids"])
    records = {str(record.get("id")): record for record in sample_manifest.get("d4_2", []) if isinstance(record, Mapping)}
    unique_sources = list(dict.fromkeys(source_slots))
    per_source_limit = max(2, MAX_D43_EVIDENCE_IMAGES // max(1, len(unique_sources)))
    evidence: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for source_id in unique_sources:
        record = records.get(source_id)
        if record is None:
            failures.append({"source_checkpoint_id": source_id, "reason": "missing_d4_2_record", "candidate_failure_proven": False})
            continue
        frames = [
            frame for frame in record.get("frames", [])
            if isinstance(frame, Mapping) and isinstance(frame.get("path"), str)
            and isinstance(frame.get("snapshot"), Mapping) and Path(frame["path"]).is_file()
        ]
        if _target_specific_target_tokens(d4_contract.get("operation_policy")):
            frames = [
                frame
                for frame in frames
                if _frame_has_identifiable_active_target(
                    frame,
                    d4_contract.get("operation_policy"),
                )
            ]
            if not frames:
                failures.append(
                    {
                        "source_checkpoint_id": source_id,
                        "reason": "no_identifiable_active_target_frame",
                        "candidate_failure_proven": False,
                    }
                )
                continue
        if record.get("status") != "completed" or not frames:
            failures.append({"source_checkpoint_id": source_id, "reason": str(record.get("status", "no_valid_frames")), "candidate_failure_proven": False})
            continue
        distinct = select_materially_distinct_frames(frames)
        for frame_index in _even_indices(len(distinct), per_source_limit):
            frame = distinct[frame_index]
            path = Path(str(frame["path"])).resolve()
            stable = {
                "source_checkpoint_id": source_id,
                "case": str(frame.get("case", "")),
                "phase": str(frame.get("phase", "")),
                "relative_time_seconds": float(frame.get("offset_seconds", 0.0)),
                "snapshot": frame.get("snapshot"),
                "image_sha256": _file_sha256(path),
            }
            evidence.append({"evidence_id": f"evidence_{len(evidence) + 1:03d}", **stable, "path": str(path), "evidence_sha256": _sha(_canonical(stable))})
    slot_counts = {str(index + 1): sum(item["source_checkpoint_id"] == source_id for item in evidence) for index, source_id in enumerate(source_slots)}
    slot_evidence = [[item for item in evidence if item["source_checkpoint_id"] == source_id] for source_id in source_slots]
    pair_analyses = [
        {"first_evidence_id": first["evidence_id"], "second_evidence_id": second["evidence_id"], **analyze_visual_difference(first["path"], second["path"])}
        for first in slot_evidence[0] for second in slot_evidence[1]
        if first["evidence_id"] != second["evidence_id"]
    ] if len(slot_evidence) == 2 else []
    material_pairs = [item for item in pair_analyses if item.get("materially_different") is True]
    if all(slot_evidence) and not material_pairs:
        failures.append({
            "source_checkpoint_ids": source_slots,
            "reason": "insufficient_materially_distinct_images",
            "visual_difference_policy": VISUAL_DIFFERENCE_POLICY,
            "failure_origin": "indeterminate_visual_evidence",
            "candidate_failure_proven": False,
        })
    status = "usable" if len(evidence) >= D43_QUESTION_COUNT and all(count > 0 for count in slot_counts.values()) and bool(material_pairs) else "candidate_evidence_unavailable"
    return {
        "status": status,
        "source_checkpoint_ids": source_slots,
        "slot_evidence_counts": slot_counts,
        "evidence": evidence,
        "evidence_pool_sha256": _sha(_canonical([_public_evidence(item) for item in evidence])),
        "visual_difference_policy": VISUAL_DIFFERENCE_POLICY,
        "material_evidence_pairs": material_pairs,
        "candidate_failures": failures,
    }


def select_best_material_pair(evidence_pool: Mapping[str, Any]) -> dict[str, Any] | None:
    if evidence_pool.get("status") != "usable":
        return None
    source_slots = list(evidence_pool.get("source_checkpoint_ids", []))
    if len(source_slots) != D43_QUESTION_COUNT:
        return None
    by_id = {str(item.get("evidence_id")): item for item in evidence_pool.get("evidence", []) if isinstance(item, Mapping)}
    ranked: list[tuple[tuple[Any, ...], Mapping[str, Any]]] = []
    for pair in evidence_pool.get("material_evidence_pairs", []):
        if not isinstance(pair, Mapping):
            continue
        first = by_id.get(str(pair.get("first_evidence_id")))
        second = by_id.get(str(pair.get("second_evidence_id")))
        if not first or not second or first.get("source_checkpoint_id") != source_slots[0] or second.get("source_checkpoint_id") != source_slots[1] or first.get("image_sha256") == second.get("image_sha256"):
            continue
        ranked.append(((-float(pair.get("changed_pixel_fraction", 0.0)), -float(pair.get("difference_span_fraction", 0.0)), str(first["evidence_id"]), str(second["evidence_id"])), pair))
    if not ranked:
        return None
    _rank, analysis = min(ranked, key=lambda item: item[0])
    first = by_id[str(analysis["first_evidence_id"])]
    second = by_id[str(analysis["second_evidence_id"])]
    return {
        "selection_policy": EVIDENCE_SELECTION_POLICY,
        "considered_material_pair_count": len(ranked),
        "evidence": [dict(first), dict(second)],
        "selected_evidence_ids": [first["evidence_id"], second["evidence_id"]],
        "selected_image_sha256": [first["image_sha256"], second["image_sha256"]],
        "visual_difference_analysis": dict(analysis),
    }


def _bound_images(evidence: Sequence[Mapping[str, Any]]) -> list[tuple[Path, str]]:
    return [
        (Path(str(item["path"])), f"Assigned image {index + 1}: " + json.dumps({"case": item.get("case"), "phase": item.get("phase"), "snapshot": item.get("snapshot")}, ensure_ascii=False))
        for index, item in enumerate(evidence)
    ]


def _question_prompt(d4_contract: Mapping[str, Any], checkpoints: Sequence[Mapping[str, Any]], source_slots: Sequence[str]) -> str:
    by_id = {str(item.get("id")): item for item in checkpoints}
    source_text = []
    for index, source_id in enumerate(source_slots):
        row = by_id.get(source_id, {})
        source_text.append({"question_number": index + 1, **{key: row[key] for key in ("item", "objective", "initial_state", "trigger", "expected_transition") if key in row}})
    return json.dumps({
        "target": d4_contract["target"],
        "allowed_operations": _question_operations(
            d4_contract["allowed_operations"],
            d4_contract.get("operation_policy"),
        ),
        "operation_policy": d4_contract.get("operation_policy"),
        "fixed_public_question": D43_QUESTION_TEXT,
        "assigned_source_context": source_text,
        "binding_rule": "The first supplied image is permanently bound to question 1 and the second to question 2.",
        "required_shape": {"questions": [{"options": {"A": "operation", "B": "operation"}, "correct_choice": "A", "answer_rationale": "visible rationale"}, {"options": {"A": "operation", "B": "operation"}, "correct_choice": "B", "answer_rationale": "visible rationale"}]},
    }, ensure_ascii=False, separators=(",", ":"))


def _normalize_questions(
    value: Any,
    selected_evidence: Sequence[Mapping[str, Any]],
    source_slots: Sequence[str],
    allowed_operations: Sequence[str],
    operation_policy: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(value, Mapping) or not isinstance(value.get("questions"), list) or len(value["questions"]) != D43_QUESTION_COUNT:
        raise ValueError("questions must contain exactly two items")
    result: list[dict[str, Any]] = []
    for index, (raw, evidence) in enumerate(zip(value["questions"], selected_evidence, strict=True)):
        if not isinstance(raw, Mapping):
            raise ValueError(f"questions[{index}] must be an object")
        options = _normalize_options(
            raw.get("options"),
            f"questions[{index}].options",
            allowed_operations,
            operation_policy,
        )
        correct = _nonempty(raw.get("correct_choice"), f"questions[{index}].correct_choice").upper()
        if correct not in options:
            raise ValueError(f"questions[{index}] answer is not an option")
        result.append({
            "id": f"d4_question_{index + 1:02d}",
            "source_slot": index + 1,
            "source_checkpoint_id": source_slots[index],
            "evidence_id": evidence["evidence_id"],
            "evidence_sha256": evidence["evidence_sha256"],
            "image_sha256": evidence["image_sha256"],
            "question": D43_QUESTION_TEXT,
            "options": options,
            "correct_choice": correct,
            "answer_rationale": _english(raw.get("answer_rationale"), f"questions[{index}].answer_rationale"),
        })
    return result


def _base_pack(contract: Mapping[str, Any], sample_manifest: Mapping[str, Any], candidate_project_sha256: str, pool: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": QUESTION_PACK_SCHEMA_VERSION,
        "design_version": QUESTION_PACK_DESIGN_VERSION,
        "game_slug": contract["game_slug"],
        "candidate_project_sha256": candidate_project_sha256,
        "contract_version": contract["contract_version"],
        "contract_sha256": contract["contract_sha256"],
        "sample_manifest_sha256": _sha(_canonical(sample_manifest)),
        "evidence_pool_sha256": pool["evidence_pool_sha256"],
        "source_checkpoint_ids": pool["source_checkpoint_ids"],
        "evidence": pool["evidence"],
        "candidate_failures": pool["candidate_failures"],
    }


def build_d43_question_pack_single_pass(*, d4_contract: Mapping[str, Any], d2_checkpoints: Sequence[Mapping[str, Any]], sample_manifest: Mapping[str, Any], candidate_project_sha256: str, generator: SemanticJudge, model: str = CONTRACT_GENERATOR_MODEL) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{64}", candidate_project_sha256):
        raise ValueError("candidate_project_sha256 must be a SHA256")
    if model != CONTRACT_GENERATOR_MODEL:
        raise ValueError("D4.3 question generation must use qwen3.7-plus")
    if not isinstance(d4_contract.get("allowed_operations"), list):
        raise ValueError("D4.3 question generation requires contract operations")
    pool = build_d43_evidence_pool(d4_contract, sample_manifest)
    base = _base_pack(d4_contract, sample_manifest, candidate_project_sha256, pool)
    if pool["status"] != "usable":
        pack = {**base, "status": "candidate_evidence_unavailable", "questions": [], "provenance": {"runtime_question_policy": RUNTIME_QUESTION_POLICY, "question_review_policy": QUESTION_REVIEW_POLICY, "generation_status": "not_run_candidate_evidence_unavailable", "generator_model": model, "local_validation": True, "semantic_call_count": 0}, "candidate_failure_proven": False}
        pack["question_pack_sha256"] = question_pack_sha256(pack)
        return pack
    selection = select_best_material_pair(pool)
    if selection is None:
        pack = {**base, "status": "candidate_evidence_unavailable", "questions": [], "candidate_failure_proven": False, "provenance": {"runtime_question_policy": RUNTIME_QUESTION_POLICY, "question_review_policy": QUESTION_REVIEW_POLICY, "generation_status": "not_run_deterministic_pair_unavailable", "generator_model": model, "local_validation": True, "semantic_call_count": 0}}
        pack["question_pack_sha256"] = question_pack_sha256(pack)
        return pack
    selected = selection["evidence"]
    prompt = _question_prompt(d4_contract, d2_checkpoints, pool["source_checkpoint_ids"])

    def validate_generated(value: dict[str, Any]) -> dict[str, Any]:
        _normalize_questions(
            value,
            selected,
            pool["source_checkpoint_ids"],
            d4_contract["allowed_operations"],
            d4_contract.get("operation_policy"),
        )
        return value

    try:
        method = getattr(generator, "json_vision_validated", None)
        if callable(method):
            raw = method(
                GENERATOR_INSTRUCTIONS,
                prompt,
                _bound_images(selected),
                "d4_3_questions_single_pass",
                validator=validate_generated,
            )
        else:
            raw = generator.json_vision(
                GENERATOR_INSTRUCTIONS,
                prompt,
                _bound_images(selected),
                "d4_3_questions_single_pass",
            )
        questions = _normalize_questions(
            raw,
            selected,
            pool["source_checkpoint_ids"],
            d4_contract["allowed_operations"],
            d4_contract.get("operation_policy"),
        )
    except Exception as exc:
        pack = {**base, "status": "judge_output_unavailable", "questions": [], "selected_evidence_binding": selection, "candidate_failure_proven": False, "judge_failure": {"failure_origin": "judge_or_transport", "candidate_failure_proven": False, "error_type": type(exc).__name__, "message": redact_text(str(exc)), "retryable_stage": "visual_question_generation"}, "provenance": {"runtime_question_policy": RUNTIME_QUESTION_POLICY, "question_review_policy": QUESTION_REVIEW_POLICY, "generation_status": "judge_output_unavailable", "generator_model": model, "local_validation": True, "semantic_call_count": 1, "technical_attempt_limit": 2}}
        pack["question_pack_sha256"] = question_pack_sha256(pack)
        return pack
    pack = {**base, "status": "completed", "questions": questions, "selected_evidence_binding": selection, "candidate_failure_proven": False, "provenance": {"runtime_question_policy": RUNTIME_QUESTION_POLICY, "question_review_policy": QUESTION_REVIEW_POLICY, "generation_status": "accepted_by_local_validation", "generator_model": model, "local_validation": True, "semantic_call_count": 1, "valid_result_count": 1, "technical_attempt_limit": 2, "model_selected_evidence": False, "input_image_count": 2}}
    pack["question_pack_sha256"] = question_pack_sha256(pack)
    return pack


def build_d43_question_pack(*, d4_contract: Mapping[str, Any], d2_checkpoints: Sequence[Mapping[str, Any]], sample_manifest: Mapping[str, Any], candidate_project_sha256: str, generator: SemanticJudge, **_: Any) -> dict[str, Any]:
    return build_d43_question_pack_single_pass(d4_contract=d4_contract, d2_checkpoints=d2_checkpoints, sample_manifest=sample_manifest, candidate_project_sha256=candidate_project_sha256, generator=generator)


def validate_d43_question_pack(pack: Mapping[str, Any], *, d4_contract: Mapping[str, Any], sample_manifest: Mapping[str, Any], candidate_project_sha256: str) -> dict[str, Any]:
    if pack.get("schema_version") != QUESTION_PACK_SCHEMA_VERSION or pack.get("design_version") != QUESTION_PACK_DESIGN_VERSION:
        raise ValueError("D4.3 question pack schema/design is invalid")
    if pack.get("game_slug") != d4_contract.get("game_slug") or pack.get("candidate_project_sha256") != candidate_project_sha256 or pack.get("contract_version") != d4_contract.get("contract_version") or pack.get("contract_sha256") != d4_contract.get("contract_sha256"):
        raise ValueError("D4.3 question pack identity mismatch")
    pool = build_d43_evidence_pool(d4_contract, sample_manifest)
    if pack.get("evidence_pool_sha256") != pool["evidence_pool_sha256"] or pack.get("evidence") != pool["evidence"] or pack.get("source_checkpoint_ids") != pool["source_checkpoint_ids"]:
        raise ValueError("D4.3 question evidence binding drifted")
    status = pack.get("status")
    if status == "completed":
        if pool["status"] != "usable":
            raise ValueError("completed question pack lacks usable evidence")
        selection = select_best_material_pair(pool)
        if pack.get("selected_evidence_binding") != selection:
            raise ValueError("D4.3 selected evidence binding is not deterministic")
        expected = _normalize_questions(
            pack,
            selection["evidence"],
            pool["source_checkpoint_ids"],
            d4_contract["allowed_operations"],
            d4_contract.get("operation_policy"),
        )
        if pack.get("questions") != expected:
            raise ValueError("D4.3 questions are not canonical")
        provenance = pack.get("provenance")
        if not isinstance(provenance, Mapping) or provenance.get("generator_model") != CONTRACT_GENERATOR_MODEL or provenance.get("generation_status") != "accepted_by_local_validation" or provenance.get("local_validation") is not True or provenance.get("semantic_call_count") != 1:
            raise ValueError("D4.3 provenance is not the Qwen local-validation policy")
    elif status == "judge_output_unavailable":
        if pool["status"] != "usable" or pack.get("questions") != [] or pack.get("candidate_failure_proven") is not False:
            raise ValueError("invalid judge-output-unavailable pack")
    elif status == "candidate_evidence_unavailable":
        if pack.get("questions") != [] or pack.get("candidate_failure_proven") is not False:
            raise ValueError("invalid candidate-evidence-unavailable pack")
    else:
        raise ValueError("D4.3 question pack status is invalid")
    if pack.get("question_pack_sha256") != question_pack_sha256(pack):
        raise ValueError("D4.3 question pack SHA256 is invalid")
    return dict(pack)


__all__ = [
    "CONTRACT_GENERATOR_MODEL", "CONTRACT_VALIDATOR_MODELS", "D43_QUESTION_COUNT", "D43_QUESTION_TEXT",
    "EVIDENCE_SELECTION_POLICY", "MAX_D43_EVIDENCE_IMAGES", "MIN_REVIEW_CONFIDENCE",
    "QUESTION_PACK_DESIGN_VERSION", "QUESTION_PACK_SCHEMA_VERSION", "QUESTION_REVIEW_POLICY",
    "build_d43_evidence_pool", "build_d43_question_pack", "build_d43_question_pack_single_pass",
    "question_pack_sha256", "select_best_material_pair", "validate_d43_question_pack",
]
