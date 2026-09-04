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
    load_round_contract,
    validate_round_manifest,
)
from code2play.evaluation.scoring import assemble_result


def test_official_weights_and_d1_contribution_gate() -> None:
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
    assert gated["dimensions"]["D2"]["weighted_contribution"] == 0.0


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
