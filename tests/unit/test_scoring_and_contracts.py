from __future__ import annotations

import json
from pathlib import Path

import pytest

from code2play.cli import EXPECTED_SLUGS, _mock_contract_generator
from code2play.config.project import games, load_config
from code2play.d4.contracts import (
    D4_CONTRACT_VERSION,
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
