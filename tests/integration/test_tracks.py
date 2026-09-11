from __future__ import annotations

from collections import Counter
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from code2play.cli import _mock_contract_generator, main
from code2play.config.project import (games, load_config, normalized_policy_sha256,
                                      require_locked_runtime_policy, select_run_config, task_storage_dir)
from code2play.d4.contracts import ContractsIncomplete, build_round_contracts, validate_round_manifest
from code2play.execution import benchmark
from code2play.providers.dashscope import JudgeAttemptsExhausted, candidate_generation_settings
from code2play.reporting.tracks import api_usage, combined_report, inspect_run


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_tracks_select_models_independently_of_judge_and_preserve_resume_identity():
    original = load_config()
    core = select_run_config(original)
    full = select_run_config(original, track="full150")
    assert len(core["games"]) == 15 and len(full["games"]) == 150
    assert Counter(item["family_slug"] for item in full["games"]) == {item["slug"]: 10 for item in core["games"]}
    second = {**original["models"][0], "id": "other_candidate", "model": "qwen/qwen3.7-plus", "reasoning": {"enabled": False}}
    original["models"].append(second)
    with pytest.raises(ValueError, match="explicitly"):
        select_run_config(original)
    selected = select_run_config(original, model_id=core["models"][0]["id"])
    assert normalized_policy_sha256(selected) == normalized_policy_sha256(core)
    require_locked_runtime_policy(selected)
    alternate = select_run_config(original, model_id="other_candidate")
    require_locked_runtime_policy(alternate)
    assert alternate["judge"] == selected["judge"]
    from code2play.config.project import models
    assert candidate_generation_settings(models(alternate)[0])["model"] == second["model"]
    assert len(select_run_config(original, model_id="other_candidate", track="full150", game_slug="snake")["games"]) == 10
    assert select_run_config(original, model_id="other_candidate", track="full150", game_slug="snake", variant_id="var09")["games"][0]["slug"] == "snake_var09"
    for kwargs in ({"variant_id": "var01"}, {"game_slug": "snake", "variant_id": "var01"}, {"track": "full150", "game_slug": "snake", "variant_id": "var10"}):
        with pytest.raises(ValueError):
            select_run_config(original, model_id="other_candidate", **kwargs)


def test_full_round_serves_core_and_contract_failure_only_retries_missing(tmp_path):
    full = select_run_config(load_config(), track="full150")
    core = select_run_config(load_config())
    generate = _mock_contract_generator(full)
    called = []
    fail = {"snake_var09", "mini_zelda_var09"}

    def partial(slug, prompt):
        called.append(slug)
        if slug in fail:
            raise JudgeAttemptsExhausted(purpose=slug, attempts=2, error=ValueError("incomplete JSON"))
        return generate(slug, prompt)

    root = tmp_path / "round-full"
    with pytest.raises(ContractsIncomplete) as caught:
        build_round_contracts(root, games(full), config=full, generator=partial)
    assert set(caught.value.report["missing_instances"]) == fail
    assert len(called) == 150 and not (root / "contracts/manifest.json").exists()
    assert (root / "contracts/snake.json").is_file()
    kept = (root / "contracts/snake.json").read_bytes()
    called.clear()
    fail.clear()
    manifest = build_round_contracts(root, games(full), config=full, generator=partial)
    assert called == ["snake_var09", "mini_zelda_var09"]
    assert (root / "contracts/snake.json").read_bytes() == kept
    assert len(manifest["contracts"]) == 150
    validate_round_manifest(manifest, round_dir=root, expected_slugs=[game.slug for game in games(core)])
    called.clear()
    assert build_round_contracts(root, games(core), config=core, generator=partial) == manifest
    assert called == []
    with pytest.raises(ValueError, match="order"):
        validate_round_manifest(manifest, expected_slugs=["snake_var01", "snake"])
    core_root = tmp_path / "round-core"
    build_round_contracts(core_root, games(core), config=core, generator=generate)
    with pytest.raises(ValueError, match="contain every"):
        build_round_contracts(core_root, games(full), config=full, generator=generate)


def test_contract_interruption_retains_completed_instances(tmp_path):
    config = select_run_config(load_config(), track="full150", game_slug="snake")
    generate = _mock_contract_generator(config)
    called = []

    def interrupted(slug, prompt):
        called.append(slug)
        if slug == "snake_var02":
            raise KeyboardInterrupt()
        return generate(slug, prompt)

    root = tmp_path / "interrupted"
    with pytest.raises(KeyboardInterrupt):
        build_round_contracts(root, games(config), config=config, generator=interrupted)
    assert (root / "contracts/snake_var01.json").exists()
    called.clear()

    def recover(slug, prompt):
        called.append(slug)
        return generate(slug, prompt)

    build_round_contracts(root, games(config), config=config, generator=recover)
    assert called == [f"snake_var{n:02d}" for n in range(2, 10)]


def test_two_independent_tracks_schedule_165_distinct_projects(tmp_path, monkeypatch):
    observed = []
    real_build = build_round_contracts

    def mock_build(root, selected, *, config, round_id):
        return real_build(root, selected, config=config, round_id=round_id, generator=_mock_contract_generator(config))

    def generated(**kwargs):
        game = kwargs["game"]
        task = task_storage_dir(kwargs["run_dir"], f"{game.slug}__{kwargs['model'].id}__r01")
        observed.append((game.slug, task, game.spec, game.checkpoints, kwargs["config"]["selection"]["track"]))
        return {"status": "completed", "official_total": 0.0}

    monkeypatch.setenv("OPENROUTER_API_KEY", "not-a-real-key")
    monkeypatch.setattr(benchmark, "build_round_contracts", mock_build)
    monkeypatch.setattr(benchmark, "run_task", generated)
    for track in ("full150", "core15"):
        state = benchmark.run_benchmark(track=track, run_id=track, round_id="shared", workspace=tmp_path, progress=lambda _: None)
        assert state["status"] == "completed"
    assert len(observed) == len({row[1] for row in observed}) == 165
    assert len({row[2] for row in observed}) == len({row[3] for row in observed}) == 150
    assert all(len(row[1].name) == 17 for row in observed)
    with pytest.raises(ValueError, match="selection changed"):
        benchmark.run_benchmark(track="core15", run_id="full150", round_id="shared", workspace=tmp_path)


def make_scored_run(root, track, *, missing=False, subset=False):
    config = select_run_config(load_config(), track=track, game_slug="snake" if subset else None)
    matrix = []
    for index, game in enumerate(games(config)):
        status = "needs_rescore" if missing and index == 0 else "completed"
        task_id = f"{game.slug}__candidate__r01"
        task = task_storage_dir(root, task_id)
        score = 80 if game.variant_id == "base" else 60
        put(task / "summary.json", {"official_total": None if status != "completed" else score,
                                   "dimensions": {dim: {"score": score} for dim in ("D1", "D2", "D3", "D4")}})
        matrix.append({"game": game.slug, "instance_id": game.slug, "family_slug": game.family_slug,
                       "variant_id": game.variant_id, "variation_types": list(game.variation_types),
                       "task_id": task_id, "status": status})
    state = {"run_id": root.name, "selection": config["selection"], "matrix": matrix,
             "contract_manifest_sha256": "shared", "selected_model": {"id": "candidate"}}
    put(root / "run_state.json", state)
    return config, state


def test_full_family_aggregation_gaps_and_subset_never_rank(tmp_path):
    full = tmp_path / "full"
    core = tmp_path / "core"
    make_scored_run(full, "full150")
    make_scored_run(core, "core15")
    report = inspect_run(full)
    assert report["official_score"] == 62 and report["eligible_for_ranking"]
    assert report["robustness_summary"] == {"base_mean": 80, "variant_mean": 60, "mean_delta": -20, "complete_family_pairs": 15}
    assert all(row["variant_minus_base"] == -20 for row in report["robustness"])
    assert inspect_run(core)["official_score"] == 80
    groups = combined_report([full, core])["groups"]
    assert {group["track"] for group in groups} == {"core15", "full150"}
    make_scored_run(full, "full150", missing=True)
    report = inspect_run(full)
    assert not report["eligible_for_ranking"] and report["official_score"] is None
    assert report["scored_count"] == 149
    subset = tmp_path / "subset"
    make_scored_run(subset, "core15", subset=True)
    assert not inspect_run(subset)["eligible_for_ranking"]


def test_api_accounting_counts_failed_attempts_and_resume_without_duplicates(tmp_path):
    request = tmp_path / "model_calls/functionality/abcd"
    put(request / "raw_input.json", {"model": "judge", "role": "functionality"})
    usages = [{"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.02},
              {"prompt_tokens": 200, "completion_tokens": 30, "cost": 0.03}]
    put(request / "request_result.json", {"attempts_made": 2, "attempts": [{"attempt": n, "usage": usage} for n, usage in enumerate(usages, 1)]})
    for n, usage in enumerate(usages, 1):
        put(request / f"raw_response_attempt_{n:03d}.json", {"usage": usage})
    put(tmp_path / "generation/state/attempts/cycle_002/attempt_001/call_metadata.json",
        {"requested_model": "candidate", "usage": {"prompt_tokens": 10, "completion_tokens": 40, "cost": 0.01}})
    report = api_usage(tmp_path)
    assert report["attempts"] == 3 and report["known_cost_usd"] == pytest.approx(0.06)
    judge = next(row for row in report["models"] if row["model"] == "judge")
    assert judge["input_tokens"] == 300 and judge["output_tokens"] == 50 and judge["retry_attempts"] == 1
    generation = next(row for row in report["models"] if row["model"] == "candidate")
    assert generation["explicit_resume_cost_usd"] == 0.01
    put(request / "request_result.json", {"attempts_made": 2, "attempts": []})
    assert not api_usage(tmp_path)["cost_complete"]


def test_plan_and_budget_are_offline_and_evaluate_requires_one_instance(monkeypatch, capsys):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert main(["plan", "--track", "full150"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["generation"]["candidate_count"] == 150
    assert result["generation"]["normal_requests"] == 600
    assert result["generation"]["output_token_cap"] == 2_700_000
    assert main(["budget", "--track", "core15"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["generation_output_cap"] == 270_000
    assert result["total_estimated_usd"] is None
    assert main(["evaluate", "--track", "full150", "--game", "snake", "--candidate", "unused"]) == 2
    assert "exactly one instance" in capsys.readouterr().out


def test_contract_recovers_interruption_between_manifest_and_pointer(tmp_path, monkeypatch):
    from code2play.d4 import contracts
    config = select_run_config(load_config(), game_slug="snake")
    root = tmp_path / "publish-interrupted"
    writer = contracts._write_json

    def interrupt(path, value):
        if path == root / "manifest.json":
            raise OSError("simulated process interruption during publication")
        writer(path, value)

    monkeypatch.setattr(contracts, "_write_json", interrupt)
    with pytest.raises(OSError):
        build_round_contracts(root, games(config), config=config, generator=_mock_contract_generator(config))
    monkeypatch.setattr(contracts, "_write_json", writer)

    def no_call(*args):
        pytest.fail("already saved contract must not call the model")

    manifest = build_round_contracts(root, games(config), config=config, generator=no_call)
    assert (root / "manifest.json").exists()
    validate_round_manifest(manifest, round_dir=root)


def test_long_workspace_and_long_purposes_do_not_expand_request_names(tmp_path, monkeypatch):
    from code2play.providers.dashscope import OpenRouterChatJudge
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    root = tmp_path / ("workspace" * 8) / "model_calls" / "functionality"

    def reply(**kwargs):
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"echo": kwargs["messages"][1]["content"]})}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 8, "cost": 0.001}}

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=reply)))
    judge = OpenRouterChatJudge(root, model="qwen/qwen3.7-plus", role="functionality", client=client, response_format={"type": "json_object"})
    purposes = [f"unique-{i}-" + "checkpoint/unsafe:path?" * 60 for i in range(8)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda purpose: judge.json_text("Return JSON", purpose, purpose), purposes))
    assert len(results) == 8
    directories = list(root.iterdir())
    assert len(directories) == 8 and all(len(path.name) == 32 for path in directories)
    for path in directories:
        raw = json.loads((path / "raw_input.json").read_text(encoding="utf-8"))
        parsed = json.loads((path / "parsed_output.json").read_text(encoding="utf-8"))
        assert parsed["echo"] == raw["purpose"]
    assert api_usage(root)["attempts"] == 8


def test_budget_uses_instance_workload_and_shared_contracts_once(tmp_path):
    from code2play.reporting.budget import project_budget
    from code2play.providers.dashscope import resolve_judge_route
    root = tmp_path / "runs/pilot"
    config, state = make_scored_run(root, "core15", subset=True)
    task = task_storage_dir(root, state["matrix"][0]["task_id"])
    candidate_model = config["models"][0]["model"]
    put(task / "generation/state/attempts/cycle_001/attempt_001/call_metadata.json",
        {"requested_model": candidate_model, "usage": {"prompt_tokens": 100, "completion_tokens": 200, "cost": 0.1}})
    for role, images in (("functionality", []), ("artistic_visual", ["frame.png"])):
        folder = task / "model_calls" / role / "abc"
        put(folder / "raw_input.json", {"model": resolve_judge_route(config["judge"], role)["model"], "role": role, "images": images})
        put(folder / "request_result.json", {"attempts_made": 1, "attempts": [{"attempt": 1, "usage": {"prompt_tokens": 50, "completion_tokens": 25, "cost": 0.02}}]})
    round_dir = tmp_path / "rounds/existing"
    put(round_dir / "contracts/manifest.json", {"games": [game.slug for game in games(load_config())]})
    target = select_run_config(load_config())
    report = project_budget(target, [root, root], round_dir=round_dir)
    generation = next(row for row in report["categories"] if row["category"] == "generation")
    assert generation["output_tokens"] == 3000
    assert generation["cost_usd"] == pytest.approx(1.5)
    contracts = next(row for row in report["categories"] if row["category"] == "contracts")
    assert contracts["workload_units"] == 0 and contracts["cost_usd"] == 0
    assert report["total_estimated_usd"] > 1.5
    # A priced model does not turn an unlogged attempt into zero billed tokens.
    put(task / "generation/game/attempts/cycle_001/attempt_001/call_metadata.json",
        {"requested_model": candidate_model, "usage": None})
    prices = {"models": {candidate_model: {"input_usd_per_million": 1, "output_usd_per_million": 2}}}
    incomplete = project_budget(target, [root], price_snapshot=prices, round_dir=round_dir)
    generation = next(row for row in incomplete["categories"] if row["category"] == "generation")
    assert generation["reference_missing_usage_attempts"] == 1
    assert generation["cost_usd"] is None and incomplete["total_estimated_usd"] is None


def test_old_manual_results_are_visible_without_entering_new_leaderboards(tmp_path):
    root = tmp_path / "legacy-manual"
    put(root / "manual_evaluation.json", {"game": "snake", "model_id": "old_model"})
    put(root / "tasks/snake__old_model__r01/summary.json", {"official_total": 70})
    report = combined_report([root])
    assert report["groups"] == []
    assert report["historical_runs"][0]["tasks"][0]["official_total"] == 70


def test_usage_uses_optional_provider_image_token_breakdown(tmp_path):
    request = tmp_path / "model_calls/dynamic_visual/request"
    put(request / "raw_input.json", {"role": "dynamic_visual", "model": "vl", "images": ["frame.png"]})
    put(request / "request_result.json", {"attempts_made": 1, "attempts": [{"attempt": 1, "usage": {
        "prompt_tokens": 100, "completion_tokens": 20, "cost": 0.01,
        "prompt_tokens_details": {"image_tokens": 80, "cached_tokens": 30},
    }}]})
    report = api_usage(tmp_path)["models"][0]
    assert report["category"] == "vision_judge"
    assert report["image_input_tokens"] == 80 and report["text_input_tokens"] == 20
    put(request / "request_result.json", {"attempts_made": 2, "attempts": [{"attempt": 2, "usage": {
        "prompt_tokens": 100, "completion_tokens": 20, "cost": 0.01,
    }}]})
    assert api_usage(tmp_path)["models"][0]["image_input_tokens"] is None


def test_budget_does_not_price_unexecuted_judging_as_a_full_workload(tmp_path):
    from code2play.reporting.budget import project_budget
    root = tmp_path / "runs/adapter-failed"
    config, state = make_scored_run(root, "core15", subset=True)
    task = task_storage_dir(root, state["matrix"][0]["task_id"])
    put(task / "generation/state/attempts/cycle_001/attempt_001/call_metadata.json",
        {"requested_model": config["models"][0]["model"], "usage": {"prompt_tokens": 100, "completion_tokens": 200, "cost": 0.1}})
    request = task / "model_calls/code_quality/request"
    put(request / "raw_input.json", {"role": "code_quality", "model": "qwen/qwen3.7-plus"})
    put(request / "request_result.json", {"attempts_made": 1, "attempts": [{"attempt": 1, "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.01}}]})
    put(task / "evaluation/sample_manifest.json", {"compiler_parallelism": {"status": "not_run_adapter_contract"}})
    report = project_budget(select_run_config(load_config()), [root])
    groups = {row["category"]: row for row in report["categories"]}
    assert groups["generation"]["cost_usd"] == pytest.approx(1.5)
    assert groups["text_judge"]["reference_units"] == 0
    assert groups["text_judge"]["cost_usd"] is None and report["total_estimated_usd"] is None
    assert report["excluded_samples"][0]["categories"] == ["text_judge", "vision_judge"]


def test_completed_task_resume_preserves_original_execution_timestamps(tmp_path, monkeypatch):
    real_build = build_round_contracts
    monkeypatch.setenv("OPENROUTER_API_KEY", "not-a-real-key")

    def contracts(root, selected, *, config, round_id):
        return real_build(root, selected, config=config, round_id=round_id, generator=_mock_contract_generator(config))

    def task(**kwargs):
        root = task_storage_dir(kwargs["run_dir"], "snake__gpt_5_6_terra__r01")
        put(root / "run_state.json", {"created_at": "2026-09-10T10:00:00+00:00", "finished_at": "2026-09-10T10:05:00+00:00"})
        return {"status": "completed", "official_total": 70}

    monkeypatch.setattr(benchmark, "build_round_contracts", contracts)
    monkeypatch.setattr(benchmark, "run_task", task)
    initial = benchmark.run_benchmark(game_slug="snake", workspace=tmp_path, run_id="cached", round_id="round", progress=lambda _: None)
    resumed = benchmark.run_benchmark(game_slug="snake", workspace=tmp_path, run_id="cached", round_id="round", progress=lambda _: None)
    assert resumed["matrix"][0]["started_at"] == initial["matrix"][0]["started_at"]
    assert resumed["matrix"][0]["finished_at"] == initial["matrix"][0]["finished_at"]
    assert resumed["finished_at"] == initial["finished_at"]
    assert inspect_run(tmp_path / "runs/cached")["tasks"][0]["elapsed_seconds"] == 300
