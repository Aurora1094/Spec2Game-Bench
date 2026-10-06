from __future__ import annotations

import json
from pathlib import Path

import pytest

from spec2game.cli import EXPECTED_SLUGS, _mock_contract_generator, build_parser
from spec2game.config.project import games, load_config, models
from spec2game.d4.contracts import build_round_contracts, validate_d4_contract
from spec2game.evaluation.scoring import assemble_result
from spec2game.execution.benchmark import (
    run_benchmark,
    validate_batch_state,
    validate_task_state,
)
from spec2game.providers import dashscope
from spec2game.reporting.reports import (
    score_item_rows,
    validate_current_report,
    write_multi_run_reports,
    write_task_reports,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_old_d4_contract_versions_are_rejected(tmp_path: Path) -> None:
    config = load_config()
    game = games(config)[0]
    round_dir = tmp_path / "round-001"
    build_round_contracts(
        round_dir,
        [game],
        config=config,
        generator=_mock_contract_generator(config),
        round_id="round-001",
    )
    contract = json.loads(
        (round_dir / "contracts" / f"{game.slug}.json").read_text(encoding="utf-8")
    )
    checkpoints = json.loads(
        "["
        + ",".join(
            line
            for line in game.checkpoints.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        + "]"
    )
    for old_version in ("v5", "v6", "v7", "pilot_v1"):
        old_contract = dict(contract)
        old_contract["contract_version"] = old_version
        with pytest.raises(ValueError):
            validate_d4_contract(
                old_contract,
                game_slug=game.slug,
                d2_checkpoints=checkpoints,
            )


def test_old_batch_and_task_states_are_rejected() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        validate_batch_state({"schema_version": 2})
    with pytest.raises(ValueError, match="schema_version"):
        validate_task_state({"schema_version": 1})


def test_benchmark_entry_rejects_old_batch_state_before_api_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "workspace" / "runs" / "old-run"
    run_dir.mkdir(parents=True)
    (run_dir / "run_state.json").write_text(
        json.dumps({"schema_version": 2}), encoding="utf-8"
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="schema_version"):
        run_benchmark(workspace=run_dir.parents[1], run_id="old-run", resume=True)


def test_old_report_inputs_are_rejected(tmp_path: Path) -> None:
    old_result = {
        "schema_version": 1,
        "task": {"game_id": "snake", "model_id": "old-model"},
        "final_score": 42,
        "scores": {"total": 42},
    }
    with pytest.raises(ValueError):
        validate_current_report(old_result)
    with pytest.raises(ValueError):
        write_task_reports(tmp_path / "old-task", old_result)

    old_matrix_dir = tmp_path / "old-run"
    old_matrix_dir.mkdir()
    (old_matrix_dir / "matrix.json").write_text(
        json.dumps({"schema_version": 1, "matrix": []}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="unsupported report schema"):
        write_multi_run_reports(tmp_path / "combined", [old_matrix_dir])


def test_current_report_preserves_official_score_and_uses_current_names(
    tmp_path: Path,
) -> None:
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
    result["evaluation_policy"] = {
        "judge_policy": "optimized_qwen_single_pass_v2",
        "judge": {"policy": "optimized_qwen_single_pass_v2"},
        "d4_contract": None,
    }
    paths = write_task_reports(tmp_path / "task", result)
    summary = json.loads(Path(paths["summary_json"]).read_text(encoding="utf-8"))
    scorecard = Path(paths["scorecard_md"]).read_text(encoding="utf-8")
    assert summary["official_total"] == 68.5
    assert "# Spec2Game-Bench scorecard" in scorecard
    assert "GameLLM-Benchmark" not in scorecard
    assert "PILOT_JUDGE_" not in scorecard


def test_legacy_dimension_score_fallbacks_do_not_change_current_scoring() -> None:
    result = assemble_result(
        game="snake",
        model="qwen3_7_plus",
        repetition=1,
        candidate_project_sha256="a" * 64,
        d4_configured=True,
        d1_detail={"score": 80, "gate_pass": True},
        d2_detail={"score": 0.60, "status": "completed"},
        d3_detail={
            "status": "completed",
            "final_score": 100,
            "tool_score": 70,
            "tool_component": {"score": 70},
        },
        d4_detail={"score_normalized": 0.80, "status": "completed"},
    )
    assert result["dimensions"]["D3"]["score"] is None
    assert result["dimensions"]["D3"]["diagnostic_score"] is None
    assert result["official_total"] is None
    assert all(
        row["score"] is None
        for row in score_item_rows(result)
        if row["dimension"] == "D3"
    )


def test_current_nested_report_fields_are_rendered_without_legacy_aliases() -> None:
    criteria = {
        "maintainability": 80.0,
        "reliability": 70.0,
        "security": 60.0,
        "efficiency": 50.0,
        "conformance": 40.0,
    }
    d3_detail = {
        "status": "completed",
        "score": 70.0,
        "max_score": 100.0,
        "tools": {
            "status": "completed",
            "indicator_scores": {key: value / 10 for key, value in criteria.items()},
            "indicator_max_scores": {key: 20.0 for key in criteria},
            "indicator_percentages": criteria,
        },
        "semantic_judge": {"status": "completed", "criterion_scores": criteria},
        "fusion": {
            "indicator_scores": {key: 10.0 for key in criteria},
            "indicator_max_scores": {key: 20.0 for key in criteria},
            "judge_points": {key: 5.0 for key in criteria},
        },
        "tool_result": {"indicator_scores": {"maintainability": 999.0}},
        "semantic_result": {"criterion_scores": {"maintainability": 999.0}},
        "D4.1": {"score": 999.0},
    }
    result = assemble_result(
        game="snake",
        model="qwen3_7_plus",
        repetition=1,
        candidate_project_sha256="a" * 64,
        d4_configured=True,
        d1_detail={"score": 80, "gate_pass": True},
        d2_detail={"score": 0.60, "status": "completed"},
        d3_detail=d3_detail,
        d4_detail={"score_normalized": 0.80, "status": "completed"},
    )
    rows = score_item_rows(result)
    by_id = {row["item_id"]: row for row in rows}
    assert by_id["D3.maintainability.tool"]["score"] == 8.0
    assert by_id["D3.maintainability.semantic"]["score"] == 5.0
    assert by_id["D3.maintainability.fused"]["score"] == 10.0


def test_current_batch_matrix_can_be_combined_without_score_regression(
    tmp_path: Path,
) -> None:
    record = {
        "game": "snake",
        "model": "qwen3_7_plus",
        "repetition": 1,
        "task_id": "snake__qwen3_7_plus__r01",
        "status": "completed",
        "round_id": "round-001",
        "contract_manifest_sha256": "a" * 64,
        "official_total": 68.5,
        "d4_contract": {
            "contract_version": "round_v1",
            "contract_sha256": "b" * 64,
            "design_version": "d4_round_contract_qwen37_plus_v1",
        },
    }
    run_dir = tmp_path / "run-001"
    from spec2game.reporting.reports import write_batch_reports

    write_batch_reports(run_dir, [record])
    outputs = write_multi_run_reports(tmp_path / "combined", [run_dir])
    combined = json.loads(Path(outputs["combined_runs_json"]).read_text(encoding="utf-8"))
    assert combined["matrix"][0]["final_score"] == 68.5


def test_default_openrouter_terra_generation_and_aws_mantle_judge_routes() -> None:
    config = load_config()
    configured_models = models(config)
    assert len(configured_models) == 1
    assert configured_models[0].id == "qwen3_7_plus"
    assert configured_models[0].name == "Qwen3.7 Plus"
    assert configured_models[0].provider == "alibaba_dashscope"
    assert configured_models[0].model == "qwen3.7-plus"
    assert configured_models[0].api_style == "chat_completions"
    assert configured_models[0].api_key_env == "DASHSCOPE_API_KEY"
    assert configured_models[0].base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert config["judge"]["policy"] == "aws_mantle_vl_qwen235b_2507_text"
    assert config["judge"]["routing"]["roles"] == {
        "text": "aws_mantle_qwen235b",
        "vision": "aws_mantle_vl",
        "contract": "aws_mantle_coder",
    }
    text_roles = {
        "action_compiler",
        "functionality",
        "specification_deviation",
        "code_quality",
    }
    for role, route in config["judge"]["routes"].items():
        if role in text_roles:
            expected_model = "qwen.qwen3-235b-a22b-2507"
        elif role == "contract_generation":
            expected_model = "qwen.qwen3-coder-next"
        else:
            expected_model = "qwen.qwen3-vl-235b-a22b-instruct"
        assert route == {
            "provider": "aws_mantle",
            "model": expected_model,
            "api_style": "chat_completions",
            "enable_thinking": False,
            "max_output_tokens": route["max_output_tokens"],
        }
    profiles = config["judge"]["routing"]["profiles"]
    assert profiles["aws_mantle_qwen235b"]["api_key_env"] == "AWS_MANTLE_API_KEY"
    assert profiles["aws_mantle_coder"]["api_key_env"] == "AWS_MANTLE_API_KEY"
    assert profiles["aws_mantle_vl"]["api_key_env"] == "AWS_MANTLE_API_KEY"
    for profile in profiles.values():
        assert profile["api_key_env"] == "AWS_MANTLE_API_KEY"
        assert profile["response_format"] == {"type": "json_object"}
        assert "reasoning" not in profile
    assert not hasattr(dashscope, "create_compiler_judge")
    assert not hasattr(dashscope, "create_scoring_judge")

    provider_paths = {
        path
        for path in (PROJECT_ROOT / "src").rglob("*.py")
        if "from openai import" in path.read_text(encoding="utf-8")
        or "import openai" in path.read_text(encoding="utf-8")
    }
    assert provider_paths == {PROJECT_ROOT / "src" / "spec2game" / "providers" / "dashscope.py"}
    assert "compatible-mode" in (
        PROJECT_ROOT / "src" / "spec2game" / "providers" / "dashscope.py"
    ).read_text(encoding="utf-8")


def test_old_cli_and_repository_runtime_boundaries_are_absent() -> None:
    help_text = build_parser().format_help()
    assert "human-serve" not in help_text
    assert "human-response-validate" not in help_text
    assert list(EXPECTED_SLUGS) == [game.slug for game in games(load_config())]

    forbidden_dir_names = {
        "runs",
        "rounds",
        "rendered_prompts",
        "ckpt",
        "candidates",
        "questionnaires",
    }
    skipped_parts = {".venv", ".git", "__pycache__", ".pytest_cache", "node_modules"}
    found = [
        path
        for path in PROJECT_ROOT.rglob("*")
        if path.is_dir()
        and path.name in forbidden_dir_names
        and not any(part in skipped_parts for part in path.parts)
    ]
    assert not found
    assert not (PROJECT_ROOT / "contracts").exists()
