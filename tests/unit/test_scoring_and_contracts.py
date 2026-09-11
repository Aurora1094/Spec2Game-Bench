from __future__ import annotations

import json
from pathlib import Path

import pytest

from code2play.cli import EXPECTED_SLUGS, _mock_contract_generator
from code2play.config.project import games, load_config
from code2play.d4.contracts import (
    D4_CONTRACT_VERSION,
    _normalize_generated_body,
    build_round_contracts,
    eligible_d43_checkpoints,
    load_round_contract,
    normalize_spec_operation_policy,
    validate_round_manifest,
)
from code2play.evaluation.scoring import assemble_result


def test_official_weights_and_soft_d1_contribution_gate() -> None:
    result = assemble_result(
        game="snake",
        model="qwen3_7_plus",
        repetition=1,
        candidate_project_sha256="a" * 64,
        d4_configured=True,
        d1_detail={"score": 80, "gate_pass": True},
        d2_detail={"score": 0.60, "status": "completed"},
        d3_detail={"score": 70, "max_score": 100, "status": "completed"},
        d4_detail={"score_normalized": 0.80, "status": "completed"},
    )
    assert result["weights"] == {"D1": 0.20, "D2": 0.50, "D3": 0.15, "D4": 0.15}
    assert result["official_total"] == 68.5

    gated = assemble_result(
        game="snake",
        model="qwen3_7_plus",
        repetition=1,
        candidate_project_sha256="a" * 64,
        d4_configured=True,
        d1_detail={"score": 40, "gate_pass": False},
        d2_detail={"score": 1.0, "status": "completed"},
        d3_detail={"score": 100, "max_score": 100, "status": "completed"},
        d4_detail={"score_normalized": 1.0, "status": "completed"},
    )
    assert gated["official_total"] == 8.0
    assert gated["dimensions"]["D1"]["gate_factor"] == 0.0
    assert gated["dimensions"]["D2"]["weighted_contribution"] == 0.0

    transition = assemble_result(
        game="snake",
        model="qwen3_7_plus",
        repetition=1,
        candidate_project_sha256="a" * 64,
        d4_configured=True,
        d1_detail={"score": 50, "gate_pass": False},
        d2_detail={"score": 1.0, "status": "completed"},
        d3_detail={"score": 100, "max_score": 100, "status": "completed"},
        d4_detail={"score_normalized": 1.0, "status": "completed"},
    )
    assert transition["dimensions"]["D1"]["gate_factor"] == 0.5
    assert transition["official_total"] == 50.0

    passed = assemble_result(
        game="snake",
        model="qwen3_7_plus",
        repetition=1,
        candidate_project_sha256="a" * 64,
        d4_configured=True,
        d1_detail={"score": 60, "gate_pass": True},
        d2_detail={"score": 1.0, "status": "completed"},
        d3_detail={"score": 100, "max_score": 100, "status": "completed"},
        d4_detail={"score_normalized": 1.0, "status": "completed"},
    )
    assert passed["dimensions"]["D1"]["gate_factor"] == 1.0
    assert passed["official_total"] == 92.0


def test_judge_gap_has_no_official_total_even_when_d1_gate_fails() -> None:
    result = assemble_result(
        game="snake",
        model="qwen3_7_plus",
        repetition=1,
        candidate_project_sha256="a" * 64,
        d4_configured=True,
        d1_detail={"score": 40, "gate_pass": False},
        d2_detail={"score": None, "status": "judge_output_unavailable"},
        d3_detail={"score": 70, "max_score": 100, "status": "completed"},
        d4_detail={"score_normalized": 0.8, "status": "completed"},
    )
    assert result["status"] == "needs_rescore"
    assert result["official_total"] is None


def test_d3_incomplete_judge_has_no_official_total() -> None:
    result = assemble_result(
        game="snake",
        model="qwen3_7_plus",
        repetition=1,
        candidate_project_sha256="a" * 64,
        d4_configured=True,
        d1_detail={"score": 80, "gate_pass": True},
        d2_detail={"score": 0.60, "status": "completed"},
        d3_detail={"score": None, "max_score": 100, "status": "incomplete_judge"},
        d4_detail={"score_normalized": 0.80, "status": "completed"},
    )
    assert result["status"] == "needs_rescore"
    assert result["official_total"] is None
    assert result["dimensions"]["D3"]["status"] == "incomplete_judge"


def test_round_contracts_are_generated_once_and_hash_locked(tmp_path: Path) -> None:
    config = load_config()
    round_dir = tmp_path / "round-001"
    manifest = build_round_contracts(
        round_dir,
        games(config),
        config=config,
        generator=_mock_contract_generator(config),
        round_id="round-001",
        timestamp="2026-08-28T00:00:00+00:00",
    )
    assert manifest["games"] == list(EXPECTED_SLUGS)
    assert len(manifest["contracts"]) == 15
    assert (round_dir / "manifest.json").is_file()
    assert (round_dir / "contracts" / "manifest.json").is_file()
    validate_round_manifest(manifest, round_dir=round_dir, expected_slugs=list(EXPECTED_SLUGS))
    contract = load_round_contract(
        round_dir,
        "snake",
        expected_manifest_sha256=manifest["manifest_sha256"],
        d2_checkpoints=[],
    )
    assert contract["contract_version"] == D4_CONTRACT_VERSION
    assert contract["round_id"] == "round-001"

    changed = json.loads((round_dir / "contracts" / "manifest.json").read_text(encoding="utf-8"))
    changed["round_id"] = "other-round"
    (round_dir / "contracts" / "manifest.json").write_text(
        json.dumps(changed), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="manifest SHA256"):
        validate_round_manifest(changed, round_dir=round_dir)


def test_legacy_contract_fields_are_normalized_to_the_locked_schema() -> None:
    config = load_config()
    game = next(item for item in games(config) if item.slug == "snake")
    from code2play.generation.prompt_builder import load_evaluator_checkpoints, load_spec
    from code2play.d4.contracts import eligible_d43_checkpoints

    checkpoints = load_evaluator_checkpoints(load_spec(game.spec))
    eligible = eligible_d43_checkpoints(checkpoints)
    normalized = _normalize_generated_body(
        {
            "player_goal": "Collect food and survive as long as possible.",
            "legal_physical_operations": [
                "Press W to move up.",
                "Press A to move left.",
                "Press R to restart the game after game over.",
            ],
            "art_requirements": ["Use a clear, readable game scene."],
            "eligible_source_requirement_ids": [r"criterion\_2\_01", r"criterion\_2\_02"],
        },
        game_slug="snake",
        eligible_ids={row["id"] for row in eligible},
    )

    assert normalized["target"] == "Collect food and survive as long as possible."
    assert normalized["allowed_operations"] == ["Press W to move up.", "Press A to move left."]
    assert normalized["art_direction"] == ["Use a clear, readable game scene."]
    assert normalized["d4_3"]["source_checkpoint_ids"] == [eligible[0]["id"], eligible[1]["id"]]


def test_contract_generation_rejects_verbose_art_direction_before_persisting() -> None:
    config = load_config()
    game = next(item for item in games(config) if item.slug == "snake")
    from code2play.generation.prompt_builder import load_evaluator_checkpoints, load_spec

    checkpoints = load_evaluator_checkpoints(load_spec(game.spec))
    eligible = eligible_d43_checkpoints(checkpoints)
    base = {
        "target": "Collect food and survive as long as possible.",
        "allowed_operations": ["Press W to move up.", "Press A to move left."],
        "d4_3_source_checkpoint_ids": [eligible[0]["id"], eligible[1]["id"]],
    }

    with pytest.raises(ValueError, match="1 through 6"):
        _normalize_generated_body(
            {
                **base,
                "art_direction": [f"Readable visual requirement {index}." for index in range(7)],
            },
            game_slug="snake",
            eligible_ids={row["id"] for row in eligible},
        )

    with pytest.raises(ValueError, match="at most 180 characters"):
        _normalize_generated_body(
            {
                **base,
                "art_direction": ["x" * 181],
            },
            game_slug="snake",
            eligible_ids={row["id"] for row in eligible},
        )


def test_contract_requires_two_distinct_gameplay_operations() -> None:
    config = load_config()
    game = next(item for item in games(config) if item.slug == "snake")
    from code2play.generation.prompt_builder import load_evaluator_checkpoints, load_spec
    from code2play.d4.contracts import eligible_d43_checkpoints

    checkpoints = load_evaluator_checkpoints(load_spec(game.spec))
    eligible = eligible_d43_checkpoints(checkpoints)
    with pytest.raises(ValueError, match="at least two distinct"):
        _normalize_generated_body(
            {
                "target": "Collect food and survive as long as possible.",
                "allowed_operations": ["Press W to move up."],
                "art_direction": ["Use a clear, readable game scene."],
                "d4_3_source_checkpoint_ids": [eligible[0]["id"], eligible[1]["id"]],
            },
            game_slug="snake",
            eligible_ids={row["id"] for row in eligible},
        )


def test_contract_reports_operation_and_source_errors_together() -> None:
    eligible_ids = {"criterion_2_01", "criterion_2_02"}

    with pytest.raises(ValueError) as exc_info:
        _normalize_generated_body(
            {
                "target": "Collect food and survive as long as possible.",
                "allowed_operations": [
                    "Press W to move up.",
                    "Press R to restart after game over.",
                ],
                "art_direction": ["Use a clear, readable game scene."],
                "d4_3_source_checkpoint_ids": ["D2.1", "D2.2"],
            },
            game_slug="snake",
            eligible_ids=eligible_ids,
        )

    message = str(exc_info.value)
    assert "allowed operation is disallowed" in message
    assert "D4.3 source references ineligible checkpoint" in message
    assert "criterion_2_01, criterion_2_02" in message


def test_whack_a_mole_target_policy_uses_two_game_semantic_operations(
    tmp_path: Path,
) -> None:
    config = load_config()
    game = next(item for item in games(config) if item.slug == "whack_a_mole")
    from code2play.generation.prompt_builder import load_evaluator_checkpoints, load_spec

    spec = load_spec(game.spec)
    checkpoints = load_evaluator_checkpoints(spec)
    raw_policy = spec["d4_operation_policy"]
    policy = normalize_spec_operation_policy(raw_policy, checkpoints=checkpoints)
    assert policy is not None
    assert [item["id"] for item in policy["operations"]] == [
        "click_normal_mole",
        "click_golden_mole",
    ]
    assert all(item["control"] == "left_mouse_button" for item in policy["operations"])

    eligible = eligible_d43_checkpoints(checkpoints, policy)
    assert {row["id"] for row in eligible} == set(policy["d43_source_checkpoint_ids"])
    assert all(".04" not in row["id"] and ".05" not in row["id"] for row in eligible)

    lifecycle_sources = dict(raw_policy)
    lifecycle_sources["d43_source_checkpoint_ids"] = [
        "whack_a_mole.D2.2.04",
        "whack_a_mole.D2.2.05",
    ]
    with pytest.raises(ValueError, match="non-interaction checkpoint"):
        normalize_spec_operation_policy(lifecycle_sources, checkpoints=checkpoints)

    hollow_operation = dict(raw_policy)
    hollow_operation["operations"] = [
        raw_policy["operations"][0],
        {
            "id": "click_empty_hole",
            "control": "left_mouse_button",
            "target": "background",
            "description": "Click an empty background hole with the left mouse button.",
        },
    ]
    with pytest.raises(ValueError, match="disallowed"):
        normalize_spec_operation_policy(hollow_operation, checkpoints=checkpoints)

    restart_operation = dict(raw_policy)
    restart_operation["operations"] = [
        raw_policy["operations"][0],
        {
            "id": "restart_round",
            "control": "R",
            "target": "game",
            "description": "Restart the game with the R key.",
        },
    ]
    with pytest.raises(ValueError, match="disallowed"):
        normalize_spec_operation_policy(restart_operation, checkpoints=checkpoints)

    round_dir = tmp_path / "round"
    build_round_contracts(
        round_dir,
        [game],
        config=config,
        generator=_mock_contract_generator(config),
        round_id="round",
    )
    contract = json.loads(
        (round_dir / "contracts" / "whack_a_mole.json").read_text(encoding="utf-8")
    )
    assert contract["allowed_operations"] == [
        "Click a visible Normal Mole with the left mouse button.",
        "Click a visible Golden Mole with the left mouse button.",
    ]
    assert contract["operation_policy"]["identity"] == "control_plus_target"
    assert contract["operation_policy"]["operation_ids"] == [
        "click_normal_mole",
        "click_golden_mole",
    ]
    assert set(contract["d4_3"]["source_checkpoint_ids"]).issubset(
        set(policy["d43_source_checkpoint_ids"])
    )
