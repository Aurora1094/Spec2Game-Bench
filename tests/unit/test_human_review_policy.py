from __future__ import annotations

import json

from spec2game.config.project import all_instances, load_config
from spec2game.generation.prompt_builder import load_evaluator_checkpoints, load_spec
from spec2game.human_review.policy import (
    D2_DIMENSIONS,
    HUMAN_REVIEW_ITEM_COUNT,
    HUMAN_REVIEW_POLICY_PATH,
    human_review_policy_errors,
    load_human_review_policy,
)


def test_human_review_policy_covers_all_games_with_fixed_anchor_shapes() -> None:
    config = load_config()
    policy = load_human_review_policy(config)

    assert human_review_policy_errors(config) == []
    assert policy["items_per_game"] == HUMAN_REVIEW_ITEM_COUNT == 10
    assert set(policy["games"]) == {game.slug for game in all_instances(config)}

    for game in all_instances(config):
        anchors = policy["games"][game.slug]
        checkpoints = {
            str(item["id"]): item
            for item in load_evaluator_checkpoints(load_spec(game.spec))
        }
        d2_anchor_ids = anchors["d2_anchor_ids"]
        d42_anchor_ids = anchors["d42_anchor_ids"]
        assert len(d2_anchor_ids) == 5
        assert len(set(d2_anchor_ids)) == 5
        assert tuple(checkpoints[item_id]["dimension"] for item_id in d2_anchor_ids) == D2_DIMENSIONS
        assert len(d42_anchor_ids) == 2
        assert len(set(d42_anchor_ids)) == 2
        assert all(checkpoints[item_id]["kind"] == "dynamic" for item_id in d42_anchor_ids)


def test_human_review_policy_rejects_a_static_dynamic_anchor() -> None:
    config = load_config()
    raw_policy = json.loads(HUMAN_REVIEW_POLICY_PATH.read_text(encoding="utf-8"))
    raw_policy["games"]["snake"]["d42_anchor_ids"][0] = "snake.D2.1.02"

    errors = human_review_policy_errors(config, raw_policy=raw_policy)

    assert any("snake.D2.1.02 must be dynamic" in error for error in errors)
