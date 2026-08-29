from __future__ import annotations

from code2play.cli import validate_benchmark
from code2play.config.project import games, load_config
from code2play.generation.prompt_builder import validate_all_prompts


def test_catalog_has_fifteen_games_and_locked_checkpoint_totals() -> None:
    config = load_config()
    configured = games(config)
    assert len(configured) == 15
    assert {game.variants for game in configured} == {()}
    report = validate_benchmark(config)
    assert report["status"] == "passed", report["errors"]
    assert report["checkpoints"] == 537
    assert report["dimensions"] == {
        "D2.1": 97,
        "D2.2": 94,
        "D2.3": 150,
        "D2.4": 66,
        "D2.5": 130,
    }


def test_all_staged_prompts_validate_without_paid_requests() -> None:
    reports = validate_all_prompts(load_config()["generation"])
    assert len(reports) == 15
    assert sum(item["checkpoint_count"] for item in reports) == 537
