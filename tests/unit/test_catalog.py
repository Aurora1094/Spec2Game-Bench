from __future__ import annotations

import json
from pathlib import Path
import pytest

from spec2game.cli import CHECKPOINT_CJK_RE, validate_benchmark
from spec2game.config.project import PROJECT_ROOT, games, load_config, resolve_workspace
from spec2game.generation.prompt_builder import validate_all_prompts
from spec2game.config.variants import carrot_paths, combat_layout, maze_layout, pipe_layout


def test_catalog_has_fifteen_games_and_locked_checkpoint_totals() -> None:
    config = load_config()
    configured = games(config)
    assert len(configured) == 15
    assert all(len(game.variants) == 9 for game in configured)
    report = validate_benchmark(config)
    assert report["status"] == "passed", report["errors"]
    assert report["base_checkpoints"] == 537
    assert report["instances"] == 150
    assert report["checkpoints"] == config["catalog"]["full_checkpoint_count"]
    assert config["catalog"]["dimensions"] == {
        "D2.1": 97,
        "D2.2": 94,
        "D2.3": 150,
        "D2.4": 66,
        "D2.5": 130,
    }


def test_all_staged_prompts_validate_without_paid_requests() -> None:
    reports = validate_all_prompts(load_config()["generation"])
    assert len(reports) == 150
    assert sum(item["checkpoint_count"] for item in reports if "_var" not in item["game_slug"]) == 537
    assert sum(item["checkpoint_count"] for item in reports) == load_config()["catalog"]["full_checkpoint_count"]


def test_checkpoint_text_is_english() -> None:
    for checkpoint_path in (PROJECT_ROOT / "benchmark" / "games").glob("*/checkpoints.jsonl"):
        for line in checkpoint_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            text_fields = (
                "item",
                "objective",
                "initial_state",
                "trigger",
                "expected_transition",
                "detection_method",
            )
            for field in text_fields:
                assert CHECKPOINT_CJK_RE.search(row[field]) is None, f"{row['id']}:{field}"
            for score, rubric in row["score_rubric"].items():
                assert CHECKPOINT_CJK_RE.search(rubric) is None, f"{row['id']}:score_rubric:{score}"


def test_variant_layout_checks_detect_corruption_and_blocked_spawns():
    root = PROJECT_ROOT / "benchmark/games"
    maze = (root / "maze_runner_var01/spec.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        maze_layout(maze.replace("#P    #", "#P   #", 1))
    pipe = (root / "pipe_connection_var04/spec.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        pipe_layout(pipe.replace("SNK-W", "BLK"))
    carrot = (root / "carrot_defense_var06/spec.md").read_text(encoding="utf-8")
    assert len(carrot_paths(carrot)) >= 2
    with pytest.raises(ValueError, match="nonadjacent"):
        carrot_paths(carrot.replace("(1,1), (2,1)", "(1,1), (2,2)", 1))
    arena = (root / "arena_shooter_var07/spec.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="overlaps"):
        combat_layout(arena.replace("(110, 145)", "(170, 230)"), "arena_shooter")
    zelda = (root / "mini_zelda_var07/spec.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="overlaps"):
        combat_layout(zelda.replace("(390, 180)", "(90, 300)"), "mini_zelda")


def test_legacy_workspace_environment_name_remains_supported(monkeypatch, tmp_path: Path) -> None:
    legacy_workspace = tmp_path / "legacy-workspace"
    monkeypatch.delenv("SPEC2GAME_WORKSPACE", raising=False)
    monkeypatch.setenv("CODE2PLAY_WORKSPACE", str(legacy_workspace))

    assert resolve_workspace() == legacy_workspace.resolve()
