"""Build auditable evidence sidecars for human review.

The automatic score remains authoritative and is never modified here.  This
module turns the exact source/trace/image inputs used by semantic judges into a
content-addressed evidence package, then exports a separate, identity-blind
questionnaire package.  Private mappings and answer keys never enter the
public directory.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import secrets
from typing import Any, Iterable, Mapping

from code2play.evaluation.dimensions.d2.protocol_evaluator import (
    DIMENSION_NAMES,
    _compact_trace_for_judge,
)
from code2play.config.project import game_by_slug, load_config
from code2play.d4.contracts import load_round_contract
from code2play.generation.prompt_builder import load_spec
from code2play.execution.safe_artifacts import sanitize, write_json
from code2play.human_review.policy import (
    HUMAN_REVIEW_CONSTRUCT_COUNTS,
    HUMAN_REVIEW_DESIGN_ID,
    HUMAN_REVIEW_ITEM_COUNT,
    human_review_game_policy,
    load_human_review_policy,
)


SCHEMA_VERSION = 1
SOURCE_RELATIVE = Path("evaluation/human_review/source")
SOURCE_FILES = ("state.py", "game.py", "rendering.py", "main.py")
SOURCE_TERMS = ("AST", "代码", "对象", "结构", "配置", "容器", "常量")
CODE_QUALITY_LABELS = {
    "maintainability": "Maintainability and structure",
    "reliability": "Reliability and defect risk",
    "security": "Safety and offline-task constraints",
    "efficiency": "Efficiency and resource discipline",
    "conformance": "Python conventions and readability",
}
CONSTRUCTION_COUNTS = {
    "d2_anchor_items": 5,
    "d41_overall_items": 1,
    "d42_anchor_items": 2,
    "d43_action_items": 1,
    "d43_validity_items": 1,
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, dict) else {}


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            sanitize(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_suffix(path: Path) -> str:
    suffix = path.suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix) else ".bin"


class _Assets:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.records: dict[str, dict[str, Any]] = {}

    def add_bytes(
        self,
        data: bytes,
        *,
        suffix: str,
        media_type: str,
        label: str,
    ) -> str:
        sha = _sha256_bytes(data)
        asset_id = f"asset-{sha[:16]}"
        relative = Path("assets") / "sha256" / sha[:2] / f"{sha}{suffix}"
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file():
            target.write_bytes(data)
        # An asset is content-addressed and can legitimately be reused in several
        # transitions or screenshot positions.  Keep the first generic asset label
        # stable; use-site context belongs on the questionnaire item reference.
        if asset_id not in self.records:
            self.records[asset_id] = {
                "asset_id": asset_id,
                "path": relative.as_posix(),
                "sha256": sha,
                "bytes": len(data),
                "media_type": media_type,
                "label": label,
            }
        return asset_id

    def add_file(self, path: str | Path, *, label: str) -> str | None:
        source = Path(path)
        if not source.is_file():
            return None
        suffix = _safe_suffix(source)
        media_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".json": "application/json",
            ".py": "text/x-python",
            ".txt": "text/plain",
        }.get(suffix, "application/octet-stream")
        return self.add_bytes(
            source.read_bytes(), suffix=suffix, media_type=media_type, label=label
        )

    def add_json(self, value: Any, *, label: str) -> str:
        return self.add_bytes(
            _canonical_bytes(value),
            suffix=".json",
            media_type="application/json",
            label=label,
        )


def _line_numbered_source(task_dir: Path, assets: _Assets) -> list[str]:
    result: list[str] = []
    for filename in SOURCE_FILES:
        path = task_dir / "candidate" / filename
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        numbered = "\n".join(
            f"{line_no:05d} | {line}"
            for line_no, line in enumerate(text.splitlines(), start=1)
        ) + "\n"
        asset_id = assets.add_bytes(
            numbered.encode("utf-8"),
            suffix=".txt",
            media_type="text/plain",
            label=f"Anonymous candidate source: {filename}, with line numbers",
        )
        result.append(asset_id)
    return result


def _item_id(candidate_sha: str, internal_ref: str) -> str:
    digest = hashlib.sha256(
        f"{candidate_sha}:{HUMAN_REVIEW_DESIGN_ID}:{internal_ref}".encode("utf-8")
    ).hexdigest()
    return f"human-{digest[:20]}"


def _scale(
    kind: str,
    values: Iterable[Any],
    anchors: Mapping[str, str],
) -> dict[str, Any]:
    return {"kind": kind, "allowed_values": list(values), "anchors": dict(anchors)}


SCALE_0_2 = _scale(
    "ordinal_integer",
    (0, 1, 2),
    {
        "0": "No direct support, contradicted, or evidence is unusable.",
        "1": "Partially supported; a material requirement is missing or unclear.",
        "2": "Fully and directly supported by the supplied evidence.",
    },
)
SCALE_DEVIATION = _scale(
    "ordinal_integer",
    (0, 1, 2, 3),
    {
        "0": "No substantive extra or incompatible mechanism.",
        "1": "Minor isolated extra behavior with little effect.",
        "2": "One complete extra system or clear mechanism-level divergence.",
        "3": "Multiple extra systems or a major task-changing divergence.",
    },
)
SCALE_0_5 = _scale(
    "ordinal_integer",
    (0, 1, 2, 3, 4, 5),
    {
        "0": "No evaluable support, absent, opposite, corrupted, or unintelligible.",
        "1": "Very poor; severe defects dominate.",
        "2": "Weak; recognizable but materially incomplete or ambiguous.",
        "3": "Adequate; main requirement met with noticeable weaknesses.",
        "4": "Strong; convincing with only minor defects.",
        "5": "Excellent; unambiguous, complete, timely, and polished.",
    },
)
SCALE_0_100 = _scale(
    "continuous_integer",
    range(0, 101),
    {
        "0": "No usable evidence or wholly unacceptable.",
        "50": "Mixed quality with material weaknesses.",
        "75": "Generally sound with limited weaknesses.",
        "100": "Exceptional; no material weakness found.",
    },
)
SCALE_VALIDITY = _scale(
    "categorical",
    ("valid", "ambiguous", "insufficient_evidence"),
    {
        "valid": "The bound image clearly supports exactly one option.",
        "ambiguous": (
            "Multiple options may be plausible, or the question is not stated "
            "clearly enough."
        ),
        "insufficient_evidence": (
            "The provided image does not contain enough evidence to answer."
        ),
    },
)


def _base_item(
    *,
    candidate_sha: str,
    internal_ref: str,
    construct: str,
    label: str,
    instruction: str,
    scale: Mapping[str, Any],
    evidence: Mapping[str, Any],
    rateability: str = "rateable",
    cannot_rate_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "human_item_id": _item_id(candidate_sha, internal_ref),
        "construct": construct,
        "label": label,
        "instruction": instruction,
        "scale": dict(scale),
        "evidence": dict(evidence),
        "rateability": rateability,
        "cannot_rate_reason": cannot_rate_reason,
        "_private": {"internal_ref": internal_ref},
    }


def _resolve_existing(path_value: Any, task_dir: Path) -> Path | None:
    if not path_value:
        return None
    path = Path(str(path_value))
    candidates = [path]
    if not path.is_absolute():
        candidates.extend((task_dir / path, task_dir / "evaluation" / path))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _latest_raw_input(task_dir: Path, role: str) -> dict[str, Any]:
    root = task_dir / "evaluation" / "model_calls" / role
    candidates = sorted(root.rglob("raw_input.json")) if root.is_dir() else []
    for path in reversed(candidates):
        value = _read_json(path)
        if value:
            return value
    return {}


def _locked_contract_from_run_state(
    task_dir: Path, game_slug: str
) -> tuple[Path, str | None] | None:
    """Recover a round contract before D4 sampling has written its manifest."""

    state = _read_json(task_dir / "run_state.json")
    descriptor = state.get("policy_descriptor")
    descriptor = descriptor if isinstance(descriptor, Mapping) else {}
    contract = descriptor.get("d4_contract")
    contract = contract if isinstance(contract, Mapping) else {}
    if contract.get("configured") is not True or contract.get("status") != "locked":
        return None
    round_id = str(contract.get("round_id") or "")
    if not round_id or Path(round_id).name != round_id or round_id in {".", ".."}:
        raise ValueError("Run-state D4 contract has an invalid round ID")
    if task_dir.parent.name != "tasks" or len(task_dir.parents) < 4:
        return None
    if task_dir.parents[2].name != "runs":
        return None
    workspace_root = task_dir.parents[3]
    contract_path = workspace_root / "rounds" / round_id / "contracts" / f"{game_slug}.json"
    manifest_sha256 = contract.get("manifest_sha256")
    return contract_path, str(manifest_sha256) if manifest_sha256 else None


def _load_context(
    task_dir: Path,
    result: Mapping[str, Any] | None,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    summary = dict(result or {}) or _read_json(task_dir / "summary.json")
    task = summary.get("task") if isinstance(summary.get("task"), dict) else {}
    game_slug = str(task.get("game") or "")
    if not game_slug:
        state = _read_json(task_dir / "run_state.json")
        state_task = state.get("task") if isinstance(state.get("task"), dict) else {}
        game_slug = str(state_task.get("game") or "")
    if not game_slug:
        raise ValueError("Cannot determine game from task artifacts")
    config = load_config(config_path) if config_path else load_config()
    game = game_by_slug(config, game_slug)
    spec = load_spec(game.spec)
    checkpoints = spec["evaluation"]["d2"]["checkpoints"]
    # Round contracts are external and normally recorded in the D4 sample
    # manifest. Before sampling is complete, recover the same locked contract
    # from the task's run state and workspace-relative round path.
    d4_sample_manifest = _read_json(task_dir / "evaluation" / "d4_sample_manifest.json")
    d4_contract_path = d4_sample_manifest.get("d4_contract_path")
    expected_manifest = d4_sample_manifest.get("d4_contract_manifest_sha256")
    if isinstance(d4_contract_path, str) and d4_contract_path.strip():
        contract_path = Path(d4_contract_path).expanduser()
        if not contract_path.is_absolute():
            contract_path = (task_dir / contract_path).resolve()
        else:
            contract_path = contract_path.resolve()
    else:
        recovered = _locked_contract_from_run_state(task_dir, game_slug)
        if recovered is None:
            raise ValueError("Human evidence requires a round-locked D4 contract path")
        contract_path, expected_manifest = recovered
        contract_path = contract_path.resolve()
    if contract_path.name != f"{game_slug}.json" or contract_path.parent.name != "contracts":
        raise ValueError("Round-locked D4 contract path is not game-scoped")
    round_root = contract_path.parent.parent
    d4_contract = load_round_contract(
        round_root,
        game_slug,
        expected_manifest_sha256=(str(expected_manifest) if expected_manifest else None),
        d2_checkpoints=checkpoints,
    )
    checkpoint_by_id = {str(item["id"]): item for item in checkpoints}
    candidate_sha = str(
        task.get("candidate_project_sha256")
        or _read_json(task_dir / "candidate_manifest.json").get("project_sha256")
        or ""
    )
    if not re.fullmatch(r"[0-9a-f]{64}", candidate_sha):
        digest = hashlib.sha256()
        for filename in SOURCE_FILES:
            path = task_dir / "candidate" / filename
            if path.is_file():
                digest.update(filename.encode("utf-8"))
                digest.update(path.read_bytes())
        candidate_sha = digest.hexdigest()
    return {
        "summary": summary,
        "task": task,
        "config": config,
        "game": game,
        "spec": spec,
        "d4_contract": d4_contract,
        "d4_contract_path": contract_path,
        "checkpoints": checkpoints,
        "checkpoint_by_id": checkpoint_by_id,
        "candidate_sha": candidate_sha,
    }


def _build_functionality_items(
    task_dir: Path,
    context: Mapping[str, Any],
    assets: _Assets,
    source_assets: list[str],
    anchor_ids: Iterable[str],
) -> list[dict[str, Any]]:
    d2 = _read_json(task_dir / "evaluation" / "d2.json")
    evidence = d2.get("evidence") if isinstance(d2.get("evidence"), dict) else {}
    results = evidence.get("checkpoint_results") if isinstance(evidence, dict) else []
    by_id = context["checkpoint_by_id"]
    source_visible_by_id: dict[str, bool] = {}
    for dimension in DIMENSION_NAMES:
        group = [
            checkpoint
            for checkpoint in context["checkpoints"]
            if checkpoint.get("dimension") == dimension
        ]
        for start in range(0, len(group), 8):
            batch = group[start : start + 8]
            batch_has_source = any(
                any(term in str(checkpoint.get("detection_method") or "") for term in SOURCE_TERMS)
                for checkpoint in batch
            )
            for checkpoint in batch:
                source_visible_by_id[str(checkpoint.get("id"))] = batch_has_source
    raw_results = results if isinstance(results, list) else []
    results_by_id = {
        str(raw.get("id") or ""): raw
        for raw in raw_results if isinstance(raw, dict)
    }
    items: list[dict[str, Any]] = []
    for anchor_index, checkpoint_id in enumerate(anchor_ids, start=1):
        raw = results_by_id.get(checkpoint_id)
        checkpoint = by_id[checkpoint_id]
        trace_path = _resolve_existing(raw.get("trace_path"), task_dir) if raw else None
        trace = _read_json(trace_path) if trace_path else {}
        trace_asset = (
            assets.add_json(
                _compact_trace_for_judge(trace),
                label=(
                    "Compact state/action trace for preregistered criterion "
                    f"{anchor_index}"
                ),
            )
            if trace
            else None
        )
        method = str(checkpoint.get("detection_method") or "")
        include_source = source_visible_by_id.get(
            checkpoint_id, any(term in method for term in SOURCE_TERMS)
        )
        asset_ids = [
            *([trace_asset] if trace_asset else []),
            *(source_assets if include_source else []),
        ]
        sampling_status = str(trace.get("status") or "")
        if raw is None or not trace:
            rateability = "cannot_rate"
            cannot_rate_reason = "checkpoint_evidence_unavailable"
        elif sampling_status in {"sampling_failed", "not_run_adapter_contract"}:
            rateability = "cannot_rate"
            cannot_rate_reason = "candidate_execution_evidence_unavailable"
        else:
            rateability = "rateable"
            cannot_rate_reason = None
        public_checkpoint = {
            key: checkpoint.get(key)
            for key in (
                "item",
                "objective",
                "initial_state",
                "trigger",
                "expected_transition",
                "detection_method",
                "score_rubric",
            )
            if checkpoint.get(key) is not None
        }
        dimension = str(checkpoint.get("dimension") or "")
        item = _base_item(
            candidate_sha=context["candidate_sha"],
            internal_ref=f"functionality:{checkpoint_id}",
            construct="functional_behavior",
            label=f"{DIMENSION_NAMES.get(dimension, 'Functional behavior')} — {checkpoint.get('item', 'criterion')}",
            instruction=(
                "Apply the supplied 0/1/2 rubric using only the criterion, compact "
                "state/action trace, and source files when present. Distinguish an "
                "action-program limitation from a candidate failure."
            ),
            scale=SCALE_0_2,
            evidence={
                "criterion": public_checkpoint,
                "asset_ids": asset_ids,
                "source_was_visible_to_llm": include_source,
                "sampling_program": trace.get("compiled_program"),
            },
            rateability=rateability,
            cannot_rate_reason=cannot_rate_reason,
        )
        item["_private"].update(
            {
                "checkpoint_id": checkpoint_id,
                "automatic_score": raw.get("earned") if raw else None,
                "automatic_max_score": raw.get("possible") if raw else None,
                "automatic_judge_output": raw.get("judge_output") if raw else None,
            }
        )
        items.append(item)
    return items


def _build_deviation_items(
    context: Mapping[str, Any], source_assets: list[str], d2: Mapping[str, Any]
) -> list[dict[str, Any]]:
    evidence = d2.get("evidence") if isinstance(d2.get("evidence"), dict) else {}
    penalties = evidence.get("deviation_penalties_0_to_3", {}) if isinstance(evidence, dict) else {}
    judge_output = evidence.get("deviation_judge_output") if isinstance(evidence, dict) else None
    specification = {
        "game_description": context["spec"].get("body", ""),
        "functional_criteria": [
            {
                key: checkpoint.get(key)
                for key in ("item", "objective", "initial_state", "trigger", "expected_transition")
                if checkpoint.get(key) is not None
            }
            for checkpoint in context["checkpoints"]
        ],
    }
    items: list[dict[str, Any]] = []
    for dimension, name in DIMENSION_NAMES.items():
        item = _base_item(
            candidate_sha=context["candidate_sha"],
            internal_ref=f"specification_deviation:{dimension}",
            construct="specification_deviation",
            label=f"Out-of-spec behavior — {name}",
            instruction=(
                "Identify implemented mechanics outside or incompatible with the supplied "
                "functional specification. Do not penalize harmless implementation details, "
                "visual decoration, operating menus, or code-quality choices. Assign each "
                "extra mechanism to only one category."
            ),
            scale=SCALE_DEVIATION,
            evidence={"specification": specification, "asset_ids": source_assets},
            rateability="rateable" if source_assets else "cannot_rate",
            cannot_rate_reason=None if source_assets else "candidate_source_unavailable",
        )
        item["_private"].update(
            {
                "dimension": dimension,
                "automatic_penalty": penalties.get(dimension) if isinstance(penalties, dict) else None,
                "automatic_judge_output": judge_output,
            }
        )
        items.append(item)
    return items


def _build_code_quality_items(
    context: Mapping[str, Any], source_assets: list[str], task_dir: Path
) -> list[dict[str, Any]]:
    d3 = _read_json(task_dir / "evaluation" / "d3.json")
    result = d3.get("result") if isinstance(d3.get("result"), dict) else d3
    semantic = result.get("semantic_judge") if isinstance(result, dict) else {}
    scores = semantic.get("criterion_scores", {}) if isinstance(semantic, dict) else {}
    descriptions = {
        "maintainability": "Responsibility boundaries, cohesion/coupling, change locality, abstraction discipline, and understandable state architecture.",
        "reliability": "State consistency, lifecycle, update ordering, edge cases, mutation safety, and semantic defect risk.",
        "security": "Indirect dangerous behavior, unnecessary external access, and compliance with an offline pygame task.",
        "efficiency": "Avoidable repeated work, hotspots, collection growth, resource lifetime, caching, and per-frame work.",
        "conformance": "Semantic naming, readable organization, useful comments, magic-value clarity, and understandable control flow.",
    }
    items: list[dict[str, Any]] = []
    for criterion, label in CODE_QUALITY_LABELS.items():
        item = _base_item(
            candidate_sha=context["candidate_sha"],
            internal_ref=f"code_quality:{criterion}",
            construct="semantic_code_quality",
            label=label,
            instruction=(
                descriptions[criterion]
                + " Score semantic quality only; do not recompute formatter, complexity, "
                "security-linter, or AST tool checks. Cite file and line numbers."
            ),
            scale=SCALE_0_100,
            evidence={"asset_ids": source_assets},
            rateability="rateable" if source_assets else "cannot_rate",
            cannot_rate_reason=None if source_assets else "candidate_source_unavailable",
        )
        item["_private"].update(
            {
                "criterion": criterion,
                "automatic_score": scores.get(criterion) if isinstance(scores, dict) else None,
                "automatic_judge_output": semantic,
            }
        )
        items.append(item)
    return items


def _art_image_assets(
    task_dir: Path,
    assets: _Assets,
    sampled_images: list[Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    raw_input = _latest_raw_input(task_dir, "artistic_visual")
    asset_ids: list[str] = []
    image_refs: list[dict[str, Any]] = []
    first_position_by_asset: dict[str, int] = {}
    for index, image in enumerate(raw_input.get("images", []), start=1):
        if not isinstance(image, dict):
            continue
        asset_id = assets.add_file(
            image.get("path", ""), label="Art-review screenshot"
        )
        if asset_id:
            sample = (
                sampled_images[index - 1]
                if index <= len(sampled_images) and isinstance(sampled_images[index - 1], dict)
                else {}
            )
            first_position = first_position_by_asset.get(asset_id)
            image_ref = {
                "asset_id": asset_id,
                "sequence_index": index,
                "sequence_id": sample.get("sequence_id"),
                "relative_time_seconds": sample.get("relative_time_seconds"),
                "duplicate_content": first_position is not None,
                "duplicate_of_sequence_index": first_position,
            }
            asset_ids.append(asset_id)
            image_refs.append(image_ref)
            first_position_by_asset.setdefault(asset_id, index)
    return asset_ids, image_refs


def _build_art_items(
    context: Mapping[str, Any], task_dir: Path, assets: _Assets, d4: Mapping[str, Any]
) -> list[dict[str, Any]]:
    d41 = d4.get("d4_1_artistic_visual_quality")
    d41 = d41 if isinstance(d41, dict) else {}
    sampled_images = d41.get("sampled_images", [])
    sampled_images = sampled_images if isinstance(sampled_images, list) else []
    image_assets, image_refs = _art_image_assets(
        task_dir, assets, sampled_images
    )
    rateable = bool(image_assets)
    scores = d41.get("criterion_scores", {})
    item = _base_item(
        candidate_sha=context["candidate_sha"],
        internal_ref="artistic_visual:overall",
        construct="artistic_visual_quality",
        label="Overall visual quality",
        instruction=(
            "Assess the overall visual quality across the complete supplied screenshot set. "
            "Consider composition, contrast, style consistency, polish, and dynamic "
            "presentation together. Do not score gameplay correctness, goal clarity, "
            "difficulty, novelty, or fun. Cite asset IDs."
        ),
        scale=SCALE_0_5,
        evidence={
            "asset_ids": image_assets,
            "image_refs": image_refs,
            "sample_seed": d41.get("sample_seed"),
            "sample_size": d41.get("sample_size"),
            "screenshot_index": sampled_images,
        },
        rateability="rateable" if rateable else "cannot_rate",
        cannot_rate_reason=None if rateable else "visual_evidence_unavailable",
    )
    item["_private"].update(
        {
            "automatic_score": d41.get("score"),
            "automatic_component_scores": scores if isinstance(scores, dict) else {},
            "automatic_judge_output": d41.get("judge_output"),
        }
    )
    return [item]


def _selected_frame_assets(
    frames: list[Any], assets: _Assets
) -> tuple[list[str], list[dict[str, Any]]]:
    if not frames:
        return [], []
    selected_indices = sorted({0, len(frames) // 2, len(frames) - 1})
    asset_ids: list[str] = []
    frame_refs: list[dict[str, Any]] = []
    first_position_by_asset: dict[str, int] = {}
    for sequence_index, frame_index in enumerate(selected_indices, start=1):
        frame = frames[frame_index]
        if not isinstance(frame, dict):
            continue
        asset_id = assets.add_file(
            frame.get("path", ""),
            label="Dynamic transition frame",
        )
        if asset_id:
            first_position = first_position_by_asset.get(asset_id)
            frame_ref = {
                "asset_id": asset_id,
                "sequence_index": sequence_index,
                "source_frame_index": frame_index + 1,
                "phase": frame.get("phase"),
                "relative_time_seconds": frame.get("offset_seconds"),
                "case": frame.get("case"),
                "duplicate_content": first_position is not None,
                "duplicate_of_sequence_index": first_position,
            }
            asset_ids.append(asset_id)
            frame_refs.append(frame_ref)
            first_position_by_asset.setdefault(asset_id, sequence_index)
    return asset_ids, frame_refs


def _build_dynamic_items(
    context: Mapping[str, Any],
    assets: _Assets,
    d4: Mapping[str, Any],
    anchor_ids: Iterable[str],
) -> list[dict[str, Any]]:
    d42 = d4.get("d4_2_feedback_fidelity")
    d42 = d42 if isinstance(d42, dict) else {}
    transitions = d42.get("transitions") if isinstance(d42.get("transitions"), list) else []
    transitions_by_id = {
        str(transition.get("id") or ""): transition
        for transition in transitions
        if isinstance(transition, dict) and str(transition.get("id") or "")
    }
    result: list[dict[str, Any]] = []
    for transition_index, checkpoint_id in enumerate(anchor_ids, start=1):
        transition = transitions_by_id.get(checkpoint_id)
        checkpoint = context["checkpoint_by_id"][checkpoint_id]
        frame_assets, frame_refs = _selected_frame_assets(
            (
                transition.get("frames", [])
                if isinstance(transition, Mapping)
                and isinstance(transition.get("frames"), list)
                else []
            ),
            assets,
        )
        rateable = (
            transition is not None
            and bool(frame_assets)
            and transition.get("status") != "visual_evidence_unavailable"
        )
        component_scores = transition.get("component_scores", {}) if transition else {}
        public_checkpoint = {
            key: checkpoint.get(key)
            for key in ("item", "objective", "initial_state", "trigger", "expected_transition")
            if checkpoint.get(key) is not None
        }
        item = _base_item(
            candidate_sha=context["candidate_sha"],
            internal_ref=f"dynamic_visual:{checkpoint_id}:overall",
            construct="dynamic_visual_feedback",
            label=f"Overall dynamic feedback — transition {transition_index}",
            instruction=(
                "Compare the chronological images with the textual transition and the "
                "evaluator-compiled action program. Give one integrated score for whether "
                "the visible feedback is faithful, complete, and timely. Report an "
                "action-program limitation separately."
            ),
            scale=SCALE_0_5,
            evidence={
                "criterion": public_checkpoint,
                "compiled_action_program": transition.get("compiled_program") if transition else None,
                "asset_ids": frame_assets,
                "frame_refs": frame_refs,
                "image_order": "chronological",
            },
            rateability="rateable" if rateable else "cannot_rate",
            cannot_rate_reason=None if rateable else "visual_evidence_unavailable",
        )
        item["_private"].update(
            {
                "checkpoint_id": checkpoint_id,
                "automatic_score": transition.get("score") if transition else None,
                "automatic_component_scores": (
                    component_scores if isinstance(component_scores, dict) else {}
                ),
                "automatic_judge_output": transition.get("judge_output") if transition else None,
            }
        )
        result.append(item)
    return result


def _build_question_items(
    context: Mapping[str, Any],
    task_dir: Path,
    assets: _Assets,
    d4: Mapping[str, Any],
    question_slot: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pack = _read_json(task_dir / "evaluation" / "d4_question_pack.json")
    d43 = d4.get("d4_3_goal_interaction_inferability")
    d43 = d43 if isinstance(d43, dict) else {}
    automatic_by_id = {
        str(item.get("id")): item
        for item in d43.get("questions", [])
        if isinstance(item, dict)
    }
    evidence_by_id = {
        str(item.get("evidence_id")): item
        for item in pack.get("evidence", [])
        if isinstance(item, dict)
    }
    questions = pack.get("questions") if isinstance(pack.get("questions"), list) else []
    result: list[dict[str, Any]] = []
    answer_keys: dict[str, Any] = {}
    selected_question = (
        questions[question_slot - 1]
        if question_slot > 0
        and len(questions) >= question_slot
        and isinstance(questions[question_slot - 1], dict)
        else None
    )
    if selected_question is None:
        raw_failures = (
            pack.get("candidate_failures")
            if isinstance(pack.get("candidate_failures"), list)
            else []
        )
        reason_codes = sorted(
            {
                str(failure.get("reason"))
                for failure in raw_failures
                if isinstance(failure, Mapping) and failure.get("reason")
            }
        )
        failure_origins = sorted(
            {
                str(failure.get("failure_origin"))
                for failure in raw_failures
                if isinstance(failure, Mapping) and failure.get("failure_origin")
            }
        )
        availability = {
            "status": str(pack.get("status") or "question_pack_unavailable"),
            "reason_codes": reason_codes or ["question_pack_unavailable"],
            "failure_origins": failure_origins or ["unknown"],
            "candidate_failure_proven": bool(raw_failures)
            and all(
                isinstance(failure, Mapping)
                and bool(failure.get("candidate_failure_proven"))
                for failure in raw_failures
            ),
        }
        for kind in ("validity", "answer"):
            item = _base_item(
                candidate_sha=context["candidate_sha"],
                internal_ref=f"visual_question:{question_slot}:{kind}:unavailable",
                construct=(
                    "visual_question_validity"
                    if kind == "validity"
                    else "visual_question_answer"
                ),
                label=(
                    f"Visual question {question_slot} — evidence validity"
                    if kind == "validity"
                    else f"Visual question {question_slot} — action choice"
                ),
                instruction=(
                    "This run could not construct a grounded visual question from "
                    "candidate evidence. This item is recorded as not rateable and "
                    "does not by itself indicate a candidate rendering failure."
                ),
                scale=(
                    SCALE_VALIDITY
                    if kind == "validity"
                    else _scale("categorical", ("A", "B"), {})
                ),
                evidence={"availability": availability, "asset_ids": []},
                rateability="cannot_rate",
                cannot_rate_reason="visual_question_evidence_unavailable",
            )
            result.append(item)
        return result, answer_keys
    for index, question in ((question_slot, selected_question),):
        question_id = str(question.get("id") or f"question_{index}")
        evidence = evidence_by_id.get(str(question.get("evidence_id")), {})
        asset_id = assets.add_file(
            evidence.get("path", ""), label=f"Visual-question image {index}"
        )
        asset_ids = [asset_id] if asset_id else []
        public_question = {
            "question": question.get("question"),
            "options": question.get("options"),
        }
        validity = _base_item(
            candidate_sha=context["candidate_sha"],
            internal_ref=f"visual_question_validity:{question_id}",
            construct="visual_question_validity",
            label=f"Visual question {index} — evidence validity",
            instruction=(
                "Decide whether the question can be answered using only the bound image "
                "and whether the evidence supports exactly one option. Do not answer "
                "the action choice yet."
            ),
            scale=SCALE_VALIDITY,
            evidence={"question": public_question, "asset_ids": asset_ids},
            rateability="rateable" if asset_ids else "cannot_rate",
            cannot_rate_reason=None if asset_ids else "question_image_unavailable",
        )
        validity["_private"].update(
            {"question_id": question_id, "source_checkpoint_id": question.get("source_checkpoint_id")}
        )
        result.append(validity)
        answer = _base_item(
            candidate_sha=context["candidate_sha"],
            internal_ref=f"visual_question_answer:{question_id}",
            construct="visual_question_answer",
            label=f"Visual question {index} — action choice",
            instruction=(
                "Use only the game objective, available physical controls, question, "
                "options, and bound image. Choose A or B and enter confidence from 0 to 1."
            ),
            scale=_scale("categorical", ("A", "B"), {"A": "Choose option A.", "B": "Choose option B."}),
            evidence={
                "game_target": context["d4_contract"].get("target"),
                "available_physical_operations": context["d4_contract"].get(
                    "allowed_operations", []
                ),
                "question": public_question,
                "asset_ids": asset_ids,
            },
            rateability="rateable" if asset_ids else "cannot_rate",
            cannot_rate_reason=None if asset_ids else "question_image_unavailable",
        )
        automatic = automatic_by_id.get(question_id, {})
        answer["_private"].update(
            {
                "question_id": question_id,
                "correct_choice": question.get("correct_choice"),
                "answer_rationale": question.get("answer_rationale"),
                "automatic_answer": automatic.get("predicted_choice"),
                "automatic_judge_output": automatic.get("judge_output"),
            }
        )
        answer_keys[answer["human_item_id"]] = {
            "correct_choice": question.get("correct_choice"),
            "answer_rationale": question.get("answer_rationale"),
            "question_id": question_id,
        }
        result.append(answer)
    return result, answer_keys


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(sanitize(dict(row)), ensure_ascii=False, sort_keys=True, default=str) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def build_human_evidence(
    task_dir: str | Path,
    result: Mapping[str, Any] | None = None,
    *,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build/rebuild the private source-of-truth evidence sidecar for one task."""

    task_root = Path(task_dir).resolve()
    context = _load_context(task_root, result, config_path)
    output = task_root / SOURCE_RELATIVE
    output.mkdir(parents=True, exist_ok=True)
    assets = _Assets(output)
    source_assets = _line_numbered_source(task_root, assets)
    d4 = _read_json(task_root / "evaluation" / "d4.json")
    review_policy = human_review_game_policy(
        context["config"], context["game"].slug
    )
    items = [
        *_build_functionality_items(
            task_root,
            context,
            assets,
            source_assets,
            review_policy["d2_anchor_ids"],
        ),
        *_build_art_items(context, task_root, assets, d4),
        *_build_dynamic_items(
            context,
            assets,
            d4,
            review_policy["d42_anchor_ids"],
        ),
    ]
    question_items, answer_keys = _build_question_items(
        context,
        task_root,
        assets,
        d4,
        review_policy["d43_question_slot"],
    )
    items.extend(question_items)
    counts = Counter(str(item["construct"]) for item in items)
    if len(items) != HUMAN_REVIEW_ITEM_COUNT or dict(counts) != HUMAN_REVIEW_CONSTRUCT_COUNTS:
        raise RuntimeError(
            "human-review ten-item construction is invalid: "
            f"items={len(items)}, counts={dict(sorted(counts.items()))}"
        )
    _write_jsonl(output / "items.private.jsonl", items)
    write_json(output / "asset_index.json", {"schema_version": 1, "assets": list(assets.records.values())})
    write_json(output / "answer_keys.private.json", {"schema_version": 1, "answer_keys": answer_keys})
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "status": "human_evidence_ready",
        "automatic_scores_modified": False,
        "questionnaire_design_id": review_policy["design_id"],
        "questionnaire_policy_sha256": review_policy["policy_sha256"],
        "items_per_game": review_policy["items_per_game"],
        "construction_counts": CONSTRUCTION_COUNTS,
        "included_dimensions": ["D2", "D4"],
        "candidate_project_sha256": context["candidate_sha"],
        "game": context["game"].slug,
        "task_model": context["task"].get("model"),
        "item_count": len(items),
        "rateable_item_count": sum(item["rateability"] == "rateable" for item in items),
        "cannot_rate_item_count": sum(item["rateability"] == "cannot_rate" for item in items),
        "counts_by_construct": dict(sorted(counts.items())),
        "asset_count": len(assets.records),
        "interfaces": {
            "private_items": "items.private.jsonl",
            "private_answer_keys": "answer_keys.private.json",
            "asset_index": "asset_index.json",
            "content_addressed_assets": "assets/sha256/<prefix>/<sha256>.<ext>",
        },
        "evidence_policy": {
            "automatic_result_is_unchanged": True,
            "cannot_rate_is_not_zero": True,
            "source_and_trace_visibility_matches_llm_when_recorded": True,
            "visual_frames_match_llm_selection": True,
        },
    }
    write_json(output / "manifest.json", manifest)
    manifest["manifest_path"] = str((output / "manifest.json").resolve())
    return manifest


MODEL_ID_RE = re.compile(
    r"(?i)\b(?:qwen|dashscope|alibaba|openai|gpt|gemini|google|grok|xai|"
    r"deepseek|kimi|moonshot|glm|zhipu|mistral|anthropic|claude)[A-Za-z0-9_.+-]*\b"
)
INTERNAL_ID_RE = re.compile(
    r"(?i)\b(?:[a-z0-9_]+\.)?D[1-4](?:\.\d+){0,2}\b"
)
PUBLIC_CHECKPOINT_ID_RE = re.compile(
    r"(?i)\b[a-z][a-z0-9_]*\.D2\.[1-5]\.\d{2}\b"
)
ABSOLUTE_PATH_RE = re.compile(
    r"(?i)(?:[A-Z]:[\\/][^\r\n\"']+|"
    r"/(?!\d+(?:/\d+)+\b)(?:[^\s/]+/)+[^\s]+)"
)
BLIND_DROP_KEYS = {
    "_private",
    "checkpoint_id",
    "source_checkpoint_id",
    "dimension",
    "model",
    "provider",
    "policy",
    "run_id",
    "task_id",
    "source_jsonl",
    "trace_path",
    "compiled_program",
    "d4_contract",
}


def _blind_text(value: str, identity_terms: Iterable[str]) -> str:
    text = value
    for term in sorted({str(term) for term in identity_terms if term}, key=len, reverse=True):
        text = re.sub(re.escape(term), "[MODEL_ID_REDACTED]", text, flags=re.IGNORECASE)
    text = MODEL_ID_RE.sub("[MODEL_ID_REDACTED]", text)
    text = INTERNAL_ID_RE.sub("[INTERNAL_ITEM_ID]", text)
    text = ABSOLUTE_PATH_RE.sub("[PATH_REDACTED]", text)
    return text


def _blind_value(value: Any, identity_terms: Iterable[str]) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _blind_value(item, identity_terms)
            for key, item in value.items()
            if str(key) not in BLIND_DROP_KEYS
        }
    if isinstance(value, list):
        return [_blind_value(item, identity_terms) for item in value]
    if isinstance(value, str):
        return _blind_text(value, identity_terms)
    return value


def _public_item(
    item: Mapping[str, Any], blind_id: str, identity_terms: Iterable[str]
) -> dict[str, Any]:
    return _blind_value(
        {**{key: value for key, value in item.items() if key != "_private"}, "blind_candidate_id": blind_id},
        identity_terms,
    )


def _response_row(item: Mapping[str, Any], blind_id: str) -> dict[str, Any]:
    response: dict[str, Any] = {
        "schema_version": 1,
        "blind_candidate_id": blind_id,
        "human_item_id": item["human_item_id"],
        "construct": item["construct"],
        "rater_id": None,
        "cannot_rate": item.get("rateability") != "rateable",
        "cannot_rate_reason": item.get("cannot_rate_reason"),
        "rating": None,
        "confidence": None,
        "reason_codes": [],
        "cited_asset_ids": [],
        "comment": "",
    }
    return response


def _source_manifest_matches_policy(
    source_root: Path,
    source_manifest: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> bool:
    return (
        source_manifest.get("questionnaire_design_id") == policy.get("design_id")
        and source_manifest.get("questionnaire_policy_sha256")
        == policy.get("policy_sha256")
        and source_manifest.get("item_count") == HUMAN_REVIEW_ITEM_COUNT
        and source_manifest.get("counts_by_construct") == HUMAN_REVIEW_CONSTRUCT_COUNTS
        and (source_root / "items.private.jsonl").is_file()
        and (source_root / "asset_index.json").is_file()
        and (source_root / "answer_keys.private.json").is_file()
    )


def export_blind_bundle(
    task_dir: str | Path,
    output_dir: str | Path,
    *,
    blind_id: str | None = None,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    """Export one public questionnaire bundle and a separate private mapping."""

    task_root = Path(task_dir).resolve()
    source_root = task_root / SOURCE_RELATIVE
    config = load_config(config_path) if config_path else load_config()
    current_policy = load_human_review_policy(config)
    source_manifest = _read_json(source_root / "manifest.json")
    if not _source_manifest_matches_policy(source_root, source_manifest, current_policy):
        build_human_evidence(task_root, config_path=config_path)
        source_manifest = _read_json(source_root / "manifest.json")
    source_asset_index = _read_json(source_root / "asset_index.json")
    raw_items = [
        json.loads(line)
        for line in (source_root / "items.private.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    identity = blind_id or f"candidate-{secrets.token_hex(6)}"
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{2,63}", identity) is None:
        raise ValueError("blind-id must contain 3-64 safe ASCII filename characters")
    root = Path(output_dir).resolve()
    public_root = root / "public" / identity
    private_root = root / "private"
    if public_root.exists() or (private_root / f"{identity}.json").exists():
        raise FileExistsError(f"Blind export already exists for {identity}")
    public_root.mkdir(parents=True)
    private_root.mkdir(parents=True, exist_ok=True)
    identity_terms = [str(source_manifest.get("task_model") or "")]
    public_assets = _Assets(public_root)
    asset_id_map: dict[str, str] = {}
    for record in source_asset_index.get("assets", []):
        if not isinstance(record, dict):
            continue
        source_path = source_root / Path(str(record.get("path") or ""))
        if not source_path.is_file():
            continue
        data = source_path.read_bytes()
        media_type = str(record.get("media_type") or "application/octet-stream")
        suffix = _safe_suffix(source_path)
        if media_type == "application/json":
            try:
                data = _canonical_bytes(
                    _blind_value(json.loads(data.decode("utf-8")), identity_terms)
                )
            except (UnicodeDecodeError, json.JSONDecodeError):
                data = _blind_text(data.decode("utf-8", errors="replace"), identity_terms).encode("utf-8")
        elif media_type.startswith("text/"):
            data = _blind_text(data.decode("utf-8", errors="replace"), identity_terms).encode("utf-8")
        new_id = public_assets.add_bytes(
            data,
            suffix=suffix,
            media_type=media_type,
            label=_blind_text(str(record.get("label") or "Evidence asset"), identity_terms),
        )
        asset_id_map[str(record.get("asset_id"))] = new_id
    def remap_asset_ids(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: remap_asset_ids(item) for key, item in value.items()}
        if isinstance(value, list):
            return [remap_asset_ids(item) for item in value]
        if isinstance(value, str):
            return asset_id_map.get(value, value)
        return value
    public_items = [
        remap_asset_ids(_public_item(item, identity, identity_terms)) for item in raw_items
    ]
    write_json(
        public_root / "asset_index.json",
        {"schema_version": 1, "assets": list(public_assets.records.values())},
    )
    _write_jsonl(public_root / "items.jsonl", public_items)
    _write_jsonl(
        public_root / "response_template.jsonl",
        (_response_row(item, identity) for item in public_items),
    )
    items_sha = _sha256_file(public_root / "items.jsonl")
    assets_sha = _sha256_file(public_root / "asset_index.json")
    counts_by_construct = dict(
        sorted(Counter(str(item["construct"]) for item in public_items).items())
    )
    public_manifest = {
        "schema_version": SCHEMA_VERSION,
        "bundle_type": "blind_human_questionnaire",
        "blind_candidate_id": identity,
        "questionnaire_design_id": source_manifest.get("questionnaire_design_id"),
        "questionnaire_policy_sha256": source_manifest.get(
            "questionnaire_policy_sha256"
        ),
        "items_per_game": source_manifest.get("items_per_game"),
        "construction_counts": source_manifest.get("construction_counts"),
        "counts_by_construct": counts_by_construct,
        "included_dimensions": source_manifest.get("included_dimensions"),
        "item_count": len(public_items),
        "rateable_item_count": sum(item["rateability"] == "rateable" for item in public_items),
        "cannot_rate_item_count": sum(item["rateability"] == "cannot_rate" for item in public_items),
        "items_sha256": items_sha,
        "asset_index_sha256": assets_sha,
        "interfaces": {
            "questionnaire_items": "items.jsonl",
            "response_template": "response_template.jsonl",
            "asset_index": "asset_index.json",
            "assets": "assets/sha256/<prefix>/<sha256>.<ext>",
        },
        "response_contract": {
            "one_row_per_human_item_id": True,
            "rating_must_follow_item_scale": True,
            "confidence_range": [0.0, 1.0],
            "cannot_rate_is_distinct_from_zero": True,
            "cited_assets_must_exist_in_asset_index": True,
        },
        "blinding": {
            "candidate_model_hidden": True,
            "judge_model_hidden": True,
            "automatic_scores_hidden": True,
            "judge_outputs_hidden": True,
            "run_and_task_ids_hidden": True,
            "visual_question_answer_keys_hidden": True,
        },
    }
    write_json(public_root / "manifest.json", public_manifest)
    source_answer_keys = _read_json(source_root / "answer_keys.private.json")
    game_policy = current_policy["games"].get(str(source_manifest.get("game") or ""), {})
    private_mapping = {
        "schema_version": SCHEMA_VERSION,
        "blind_candidate_id": identity,
        "questionnaire_design_id": source_manifest.get("questionnaire_design_id"),
        "questionnaire_policy_sha256": source_manifest.get(
            "questionnaire_policy_sha256"
        ),
        "human_review_anchor_policy": game_policy,
        "task_dir": str(task_root),
        "game": source_manifest.get("game"),
        "candidate_project_sha256": source_manifest.get("candidate_project_sha256"),
        "candidate_model": source_manifest.get("task_model"),
        "human_item_mapping": {
            item["human_item_id"]: item.get("_private", {}) for item in raw_items
        },
        "answer_keys": source_answer_keys.get("answer_keys", {}),
        "public_manifest_sha256": _sha256_file(public_root / "manifest.json"),
    }
    write_json(private_root / f"{identity}.json", private_mapping)
    validation = validate_blind_bundle(public_root)
    return {
        "status": "exported" if validation["status"] == "passed" else "failed_validation",
        "blind_candidate_id": identity,
        "public_bundle": str(public_root),
        "private_mapping": str(private_root / f"{identity}.json"),
        "validation": validation,
    }


def _has_absolute_path(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_has_absolute_path(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_absolute_path(item) for item in value)
    if not isinstance(value, str):
        return False
    return bool(re.match(r"^[A-Za-z]:[\\/]", value) or value.startswith("/"))


def validate_blind_bundle(bundle_dir: str | Path) -> dict[str, Any]:
    """Validate hashes, paths, response coverage, and structured-field blinding."""

    root = Path(bundle_dir).resolve()
    errors: list[str] = []
    manifest = _read_json(root / "manifest.json")
    asset_index = _read_json(root / "asset_index.json")
    items_path = root / "items.jsonl"
    response_path = root / "response_template.jsonl"
    if not manifest:
        errors.append("manifest.json is missing or invalid")
    elif manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("manifest schema_version is invalid")
    if manifest.get("questionnaire_design_id") is not None:
        if manifest.get("questionnaire_design_id") != HUMAN_REVIEW_DESIGN_ID:
            errors.append("manifest questionnaire_design_id is invalid")
        if not re.fullmatch(
            r"[0-9a-f]{64}", str(manifest.get("questionnaire_policy_sha256") or "")
        ):
            errors.append("manifest questionnaire_policy_sha256 is invalid")
        if manifest.get("items_per_game") != HUMAN_REVIEW_ITEM_COUNT:
            errors.append("manifest items_per_game is invalid")
        if manifest.get("construction_counts") != CONSTRUCTION_COUNTS:
            errors.append("manifest construction_counts is invalid")
        if manifest.get("included_dimensions") != ["D2", "D4"]:
            errors.append("manifest included_dimensions is invalid")
    if manifest.get("bundle_type") != "blind_human_questionnaire":
        errors.append("manifest bundle_type is invalid")
    if not asset_index:
        errors.append("asset_index.json is missing or invalid")
    elif asset_index.get("schema_version") != SCHEMA_VERSION:
        errors.append("asset_index schema_version is invalid")
    if not items_path.is_file():
        errors.append("items.jsonl is missing")
    if not response_path.is_file():
        errors.append("response_template.jsonl is missing")
    items: list[dict[str, Any]] = []
    responses: list[dict[str, Any]] = []
    try:
        if items_path.is_file():
            raw_items = [
                json.loads(line)
                for line in items_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            for index, value in enumerate(raw_items, start=1):
                if isinstance(value, dict):
                    items.append(value)
                else:
                    errors.append(f"items.jsonl row {index} is not an object")
        if response_path.is_file():
            raw_responses = [
                json.loads(line)
                for line in response_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            for index, value in enumerate(raw_responses, start=1):
                if isinstance(value, dict):
                    responses.append(value)
                else:
                    errors.append(f"response_template.jsonl row {index} is not an object")
    except json.JSONDecodeError as exc:
        errors.append(f"JSONL parse error: {exc}")
    if items_path.is_file() and manifest.get("items_sha256") != _sha256_file(items_path):
        errors.append("items.jsonl SHA256 mismatch")
    if (root / "asset_index.json").is_file() and manifest.get("asset_index_sha256") != _sha256_file(root / "asset_index.json"):
        errors.append("asset_index.json SHA256 mismatch")
    forbidden = {
        "_private", "automatic_score", "automatic_penalty", "automatic_judge_output",
        "automatic_max_score", "automatic_answer", "correct_choice", "answer_rationale",
        "candidate_model", "judge_model", "judge_output", "judge_rationale",
        "answer_key", "answer_keys", "task_dir", "run_id", "task_id",
        "checkpoint_id", "source_checkpoint_id", "dimension", "source_jsonl",
        "trace_path", "compiled_program", "d4_contract", "contract_sha256",
        "candidate_project_sha256", "manifest_sha256", "input_sha256",
    }
    def walk_keys(value: Any) -> set[str]:
        if isinstance(value, dict):
            return set(value) | set().union(*(walk_keys(item) for item in value.values()), set())
        if isinstance(value, list):
            return set().union(*(walk_keys(item) for item in value), set())
        return set()
    leaked_keys = sorted(walk_keys([manifest, items, responses, asset_index]) & forbidden)
    if leaked_keys:
        errors.append("forbidden structured fields: " + ", ".join(leaked_keys))
    public_values = [manifest, items, responses, asset_index]
    if any(_has_absolute_path(value) for value in public_values):
        errors.append("public bundle contains an absolute path")
    def text_values(value: Any) -> Iterable[str]:
        if isinstance(value, dict):
            for item in value.values():
                yield from text_values(item)
        elif isinstance(value, list):
            for item in value:
                yield from text_values(item)
        elif isinstance(value, str):
            yield value
    public_text = "\n".join(text_values(public_values))
    if MODEL_ID_RE.search(public_text):
        errors.append("public bundle contains a model identity token")
    if PUBLIC_CHECKPOINT_ID_RE.search(public_text):
        errors.append("public bundle contains an internal checkpoint identifier")
    expected_item_fields = {
        "schema_version", "blind_candidate_id", "human_item_id", "construct",
        "label", "instruction", "scale", "evidence", "rateability",
        "cannot_rate_reason",
    }
    expected_response_fields = {
        "schema_version", "blind_candidate_id", "human_item_id", "construct",
        "rater_id", "cannot_rate", "cannot_rate_reason", "rating", "confidence",
        "reason_codes", "cited_asset_ids", "comment",
    }
    manifest_identity = manifest.get("blind_candidate_id")
    if not isinstance(manifest_identity, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{2,63}", manifest_identity
    ):
        errors.append("manifest blind_candidate_id is invalid")
    for index, item in enumerate(items, start=1):
        missing = sorted(expected_item_fields - set(item))
        if missing:
            errors.append(f"item {index} is missing fields: {', '.join(missing)}")
        if item.get("schema_version") != SCHEMA_VERSION:
            errors.append(f"item {index} schema_version is invalid")
        if item.get("blind_candidate_id") != manifest_identity:
            errors.append(f"item {index} blind candidate ID mismatch")
        if not isinstance(item.get("human_item_id"), str) or not re.fullmatch(
            r"human-[0-9a-f]{20}", str(item.get("human_item_id"))
        ):
            errors.append(f"item {index} human_item_id is invalid")
        if not isinstance(item.get("construct"), str) or not item.get("construct"):
            errors.append(f"item {index} construct is invalid")
        if not isinstance(item.get("scale"), dict):
            errors.append(f"item {index} scale is invalid")
        else:
            scale = item["scale"]
            allowed_values = scale.get("allowed_values")
            anchors = scale.get("anchors")
            if (
                not isinstance(scale.get("kind"), str)
                or not isinstance(allowed_values, list)
                or not allowed_values
                or not isinstance(anchors, dict)
            ):
                errors.append(f"item {index} scale shape is invalid")
        if not isinstance(item.get("evidence"), dict):
            errors.append(f"item {index} evidence is invalid")
        if item.get("rateability") not in {"rateable", "cannot_rate"}:
            errors.append(f"item {index}: invalid rateability")
        if item.get("rateability") == "cannot_rate" and not str(
            item.get("cannot_rate_reason") or ""
        ).strip():
            errors.append(f"item {index}: cannot_rate requires a reason")
    for index, response in enumerate(responses, start=1):
        missing = sorted(expected_response_fields - set(response))
        if missing:
            errors.append(f"response {index} is missing fields: {', '.join(missing)}")
        if response.get("schema_version") != SCHEMA_VERSION:
            errors.append(f"response {index} schema_version is invalid")
        if response.get("blind_candidate_id") != manifest_identity:
            errors.append(f"response {index} blind candidate ID mismatch")
        if not isinstance(response.get("cannot_rate"), bool):
            errors.append(f"response {index} cannot_rate must be boolean")
        if not isinstance(response.get("reason_codes"), list):
            errors.append(f"response {index} reason_codes must be a list")
        if not isinstance(response.get("cited_asset_ids"), list):
            errors.append(f"response {index} cited_asset_ids must be a list")
        if not isinstance(response.get("comment"), str):
            errors.append(f"response {index} comment must be a string")
    item_ids = [str(item.get("human_item_id")) for item in items]
    response_ids = [str(item.get("human_item_id")) for item in responses]
    if len(item_ids) != len(set(item_ids)):
        errors.append("duplicate human_item_id")
    if item_ids != response_ids:
        errors.append("response template does not match item order")
    if manifest.get("item_count") != len(items):
        errors.append("manifest item_count does not match items.jsonl")
    if manifest.get("rateable_item_count") != sum(item.get("rateability") == "rateable" for item in items):
        errors.append("manifest rateable_item_count does not match items.jsonl")
    if manifest.get("cannot_rate_item_count") != sum(item.get("rateability") == "cannot_rate" for item in items):
        errors.append("manifest cannot_rate_item_count does not match items.jsonl")
    if manifest.get("questionnaire_design_id") == HUMAN_REVIEW_DESIGN_ID:
        actual_construct_counts = dict(
            sorted(Counter(str(item.get("construct")) for item in items).items())
        )
        if len(items) != HUMAN_REVIEW_ITEM_COUNT:
            errors.append("ten-item questionnaire has an invalid item count")
        if manifest.get("counts_by_construct") != HUMAN_REVIEW_CONSTRUCT_COUNTS:
            errors.append("manifest counts_by_construct is invalid")
        if actual_construct_counts != HUMAN_REVIEW_CONSTRUCT_COUNTS:
            errors.append("ten-item questionnaire construct counts are invalid")
    for item, response in zip(items, responses):
        if item.get("blind_candidate_id") != response.get("blind_candidate_id"):
            errors.append(f"{item.get('human_item_id')}: blind candidate ID mismatch")
        if item.get("construct") != response.get("construct"):
            errors.append(f"{item.get('human_item_id')}: construct mismatch")
        expected_cannot_rate = item.get("rateability") != "rateable"
        if response.get("cannot_rate") != expected_cannot_rate:
            errors.append(f"{item.get('human_item_id')}: cannot_rate mismatch")
        if response.get("rating") is not None or response.get("confidence") is not None:
            errors.append(f"{item.get('human_item_id')}: response template must be blank")
    records = asset_index.get("assets", []) if isinstance(asset_index.get("assets"), list) else []
    if not isinstance(asset_index.get("assets"), list):
        errors.append("asset_index assets must be a list")
    asset_ids = {str(record.get("asset_id")) for record in records if isinstance(record, dict)}
    def referenced_asset_ids(value: Any, key: str = "") -> Iterable[str]:
        if isinstance(value, dict):
            for name, item in value.items():
                yield from referenced_asset_ids(item, str(name))
        elif isinstance(value, list):
            if key in {"asset_ids", "cited_asset_ids"}:
                for item in value:
                    if isinstance(item, str):
                        yield item
            else:
                for item in value:
                    yield from referenced_asset_ids(item, key)
        elif key == "asset_id" and isinstance(value, str):
            yield value
    missing_refs = sorted(set(referenced_asset_ids(items)) - asset_ids)
    if missing_refs:
        errors.append("items reference missing assets: " + ", ".join(missing_refs))
    for record in records:
        if not isinstance(record, dict):
            errors.append("invalid asset record")
            continue
        relative = Path(str(record.get("path") or ""))
        if relative.is_absolute() or ".." in relative.parts:
            errors.append(f"unsafe asset path: {relative}")
            continue
        sha = str(record.get("sha256") or "")
        if (
            not re.fullmatch(r"[0-9a-f]{64}", sha)
            or relative.as_posix() != f"assets/sha256/{sha[:2]}/{sha}{relative.suffix}"
            or str(record.get("asset_id") or "") != f"asset-{sha[:16]}"
        ):
            errors.append(f"asset path is not content-addressed: {relative.as_posix()}")
        path = root / relative
        if not path.is_file():
            errors.append(f"missing asset: {relative.as_posix()}")
        elif _sha256_file(path) != record.get("sha256"):
            errors.append(f"asset SHA256 mismatch: {relative.as_posix()}")
        elif str(record.get("media_type") or "").startswith("text/") or record.get("media_type") == "application/json":
            text = path.read_text(encoding="utf-8", errors="replace")
            if MODEL_ID_RE.search(text):
                errors.append(f"model identity token in public asset: {relative.as_posix()}")
            if INTERNAL_ID_RE.search(text):
                errors.append(f"internal item identifier in public asset: {relative.as_posix()}")
            if ABSOLUTE_PATH_RE.search(text):
                errors.append(f"absolute path in public asset: {relative.as_posix()}")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "passed" if not errors else "failed",
        "bundle_dir": str(root),
        "item_count": len(items),
        "asset_count": len(records),
        "errors": errors,
    }


