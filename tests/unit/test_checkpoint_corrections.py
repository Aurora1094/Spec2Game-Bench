from __future__ import annotations

from copy import deepcopy
import json
import sys

import pytest

from code2play.config.project import PROJECT_ROOT


SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from checkpoint_corrections import apply_corrections, load_corrections  # noqa: E402


def _rows(game_slug: str) -> list[dict]:
    path = PROJECT_ROOT / "benchmark" / "games" / game_slug / "checkpoints.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _row(game_slug: str, checkpoint_id: str) -> dict:
    return next(row for row in _rows(game_slug) if row["id"] == checkpoint_id)


def _variant_row(instance_id: str, base_checkpoint_id: str) -> dict:
    return next(row for row in _rows(instance_id) if row.get("base_checkpoint_id") == base_checkpoint_id)


def test_checkpoint_corrections_are_explicit_idempotent_and_guard_source_drift() -> None:
    corrections = load_corrections()
    by_family: dict[str, list[dict]] = {}
    for correction in corrections["corrections"]:
        family = correction["checkpoint_id"].split(".D2.", 1)[0]
        by_family.setdefault(family, []).append(correction)

    for family, family_corrections in by_family.items():
        current = _rows(family)
        by_id = {row["id"]: row for row in current}
        for correction in family_corrections:
            assert all(
                by_id[correction["checkpoint_id"]][field] == value
                for field, value in correction["after"].items()
            )

        old_source = deepcopy(current)
        old_by_id = {row["id"]: row for row in old_source}
        for correction in family_corrections:
            old_by_id[correction["checkpoint_id"]].update(correction["before"])
        assert apply_corrections(old_source, family) == current
        assert apply_corrections(current, family) == current

        drifted = deepcopy(current)
        drifted_by_id = {row["id"]: row for row in drifted}
        drifted_by_id[family_corrections[0]["checkpoint_id"]]["expected_transition"] = "unreviewed change"
        with pytest.raises(ValueError, match="source rule changed"):
            apply_corrections(drifted, family)


def test_base_terminal_priority_and_normal_victory_cases_are_separate() -> None:
    maze_win = _row("maze_runner", "maze_runner.D2.5.01")
    maze_loss = _row("maze_runner", "maze_runner.D2.5.02")
    arena_loss = _row("arena_shooter", "arena_shooter.D2.5.05")
    zelda_win = _row("mini_zelda", "mini_zelda.D2.5.01")
    zelda_loss = _row("mini_zelda", "mini_zelda.D2.5.02")

    assert "Time remains above 0" in maze_win["expected_transition"]
    assert "state becomes won" in maze_win["expected_transition"]
    assert "countdown reaches 0 before movement" in maze_loss["expected_transition"]
    assert "state becomes lost" in maze_loss["expected_transition"]
    assert "final state is game_over" in arena_loss["expected_transition"]
    assert "HP > 0" in zelda_win["expected_transition"]
    assert "state becomes victory" in zelda_win["expected_transition"]
    assert "final state game_over" in zelda_loss["expected_transition"]


def test_variants_inherit_failure_priority_except_explicit_arena_var09_rule() -> None:
    for variant in range(1, 9):
        row = _variant_row(f"arena_shooter_var{variant:02d}", "arena_shooter.D2.5.05")
        assert "game_over takes priority" in row["expected_transition"]

    exception = _variant_row("arena_shooter_var09", "arena_shooter.D2.5.05")
    assert "victory takes priority" in exception["expected_transition"]

    for variant in range(1, 10):
        maze = _variant_row(f"maze_runner_var{variant:02d}", "maze_runner.D2.5.02")
        zelda = _variant_row(f"mini_zelda_var{variant:02d}", "mini_zelda.D2.5.02")
        assert "lost takes priority" in maze["expected_transition"]
        assert "game_over takes priority" in zelda["expected_transition"]
