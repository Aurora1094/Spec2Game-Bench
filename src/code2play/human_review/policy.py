"""Pre-registered anchors for the fixed ten-item human-review design."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from code2play.config.project import PROJECT_ROOT, games
from code2play.generation.prompt_builder import load_evaluator_checkpoints, load_spec


HUMAN_REVIEW_DESIGN_ID = "fixed_10_item_human_review"
HUMAN_REVIEW_POLICY_PATH = PROJECT_ROOT / "benchmark" / "human_review.json"
HUMAN_REVIEW_ITEM_COUNT = 10
D2_DIMENSIONS = ("D2.1", "D2.2", "D2.3", "D2.4", "D2.5")
HUMAN_REVIEW_CONSTRUCT_COUNTS = {
    "artistic_visual_quality": 1,
    "dynamic_visual_feedback": 2,
    "functional_behavior": 5,
    "visual_question_answer": 1,
    "visual_question_validity": 1,
}


def _policy_path(path: str | Path | None = None) -> Path:
    return Path(path or HUMAN_REVIEW_POLICY_PATH).expanduser().resolve()


def _load_raw_policy(path: str | Path | None = None) -> dict[str, Any]:
    policy_path = _policy_path(path)
    try:
        raw = json.loads(policy_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"human-review policy cannot be read: {policy_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"human-review policy is invalid JSON: {policy_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("human-review policy must be a JSON object")
    return dict(raw)


def _policy_sha256(raw_policy: Mapping[str, Any]) -> str:
    payload = json.dumps(
        raw_policy,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        return None
    return [str(item) for item in value]


def human_review_policy_errors(
    config: Mapping[str, Any],
    *,
    path: str | Path | None = None,
    raw_policy: Mapping[str, Any] | None = None,
) -> list[str]:
    """Return structural and benchmark-alignment errors for the anchor policy."""

    errors: list[str] = []
    try:
        policy = dict(raw_policy) if raw_policy is not None else _load_raw_policy(path)
    except ValueError as exc:
        return [str(exc)]

    if policy.get("schema_version") != 1:
        errors.append("human-review policy schema_version must be 1")
    if policy.get("design_id") != HUMAN_REVIEW_DESIGN_ID:
        errors.append(f"human-review policy design_id must be {HUMAN_REVIEW_DESIGN_ID}")
    if policy.get("items_per_game") != HUMAN_REVIEW_ITEM_COUNT:
        errors.append("human-review policy items_per_game must be 10")
    if policy.get("d43_question_slot") != 1:
        errors.append("human-review policy d43_question_slot must be 1")

    policy_games = policy.get("games")
    if not isinstance(policy_games, Mapping):
        return [*errors, "human-review policy games must be an object"]

    configured_games = games(config)
    expected_slugs = {game.slug for game in configured_games}
    actual_slugs = {str(slug) for slug in policy_games}
    missing_slugs = sorted(expected_slugs - actual_slugs)
    extra_slugs = sorted(actual_slugs - expected_slugs)
    if missing_slugs:
        errors.append("human-review policy is missing games: " + ", ".join(missing_slugs))
    if extra_slugs:
        errors.append("human-review policy has unknown games: " + ", ".join(extra_slugs))

    for game in configured_games:
        entry = policy_games.get(game.slug)
        if not isinstance(entry, Mapping):
            errors.append(f"{game.slug}: human-review policy entry must be an object")
            continue
        d2_anchor_ids = _string_list(entry.get("d2_anchor_ids"))
        d42_anchor_ids = _string_list(entry.get("d42_anchor_ids"))
        if d2_anchor_ids is None or len(d2_anchor_ids) != len(D2_DIMENSIONS):
            errors.append(f"{game.slug}: requires exactly five D2 anchor IDs")
        elif len(set(d2_anchor_ids)) != len(d2_anchor_ids):
            errors.append(f"{game.slug}: D2 anchor IDs must be unique")
        if d42_anchor_ids is None or len(d42_anchor_ids) != 2:
            errors.append(f"{game.slug}: requires exactly two D4.2 anchor IDs")
        elif len(set(d42_anchor_ids)) != len(d42_anchor_ids):
            errors.append(f"{game.slug}: D4.2 anchor IDs must be unique")

        try:
            checkpoints = load_evaluator_checkpoints(load_spec(game.spec))
        except Exception as exc:
            errors.append(f"{game.slug}: cannot load checkpoints: {type(exc).__name__}: {exc}")
            continue
        checkpoint_by_id = {str(checkpoint.get("id")): checkpoint for checkpoint in checkpoints}

        if d2_anchor_ids is not None and len(d2_anchor_ids) == len(D2_DIMENSIONS):
            actual_dimensions: list[str] = []
            for checkpoint_id in d2_anchor_ids:
                checkpoint = checkpoint_by_id.get(checkpoint_id)
                if checkpoint is None:
                    errors.append(f"{game.slug}: unknown D2 anchor {checkpoint_id}")
                    continue
                actual_dimensions.append(str(checkpoint.get("dimension") or ""))
            if actual_dimensions and tuple(actual_dimensions) != D2_DIMENSIONS:
                errors.append(
                    f"{game.slug}: D2 anchors must follow {', '.join(D2_DIMENSIONS)}"
                )

        if d42_anchor_ids is not None and len(d42_anchor_ids) == 2:
            for checkpoint_id in d42_anchor_ids:
                checkpoint = checkpoint_by_id.get(checkpoint_id)
                if checkpoint is None:
                    errors.append(f"{game.slug}: unknown D4.2 anchor {checkpoint_id}")
                elif checkpoint.get("kind") != "dynamic":
                    errors.append(
                        f"{game.slug}: D4.2 anchor {checkpoint_id} must be dynamic"
                    )
    return errors


def load_human_review_policy(
    config: Mapping[str, Any], *, path: str | Path | None = None
) -> dict[str, Any]:
    """Load a verified copy of the pre-registered human-review policy."""

    raw_policy = _load_raw_policy(path)
    errors = human_review_policy_errors(config, path=path, raw_policy=raw_policy)
    if errors:
        raise ValueError("; ".join(errors))
    games_policy = raw_policy["games"]
    return {
        "design_id": HUMAN_REVIEW_DESIGN_ID,
        "policy_sha256": _policy_sha256(raw_policy),
        "items_per_game": HUMAN_REVIEW_ITEM_COUNT,
        "d43_question_slot": 1,
        "games": {
            str(slug): {
                "d2_anchor_ids": tuple(str(item) for item in value["d2_anchor_ids"]),
                "d42_anchor_ids": tuple(str(item) for item in value["d42_anchor_ids"]),
            }
            for slug, value in games_policy.items()
        },
    }


def human_review_game_policy(
    config: Mapping[str, Any], game_slug: str
) -> dict[str, Any]:
    policy = load_human_review_policy(config)
    try:
        return {
            "design_id": policy["design_id"],
            "policy_sha256": policy["policy_sha256"],
            "items_per_game": policy["items_per_game"],
            "d43_question_slot": policy["d43_question_slot"],
            **dict(policy["games"][game_slug]),
        }
    except KeyError as exc:
        raise ValueError(f"human-review policy has no entry for {game_slug}") from exc


__all__ = [
    "D2_DIMENSIONS",
    "HUMAN_REVIEW_CONSTRUCT_COUNTS",
    "HUMAN_REVIEW_DESIGN_ID",
    "HUMAN_REVIEW_ITEM_COUNT",
    "HUMAN_REVIEW_POLICY_PATH",
    "human_review_game_policy",
    "human_review_policy_errors",
    "load_human_review_policy",
]
