from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import site
import subprocess
import sys
import sysconfig

import pytest

from spec2game.cli import _mock_contract_generator
from spec2game.config.project import game_by_slug, games, load_config, models
from spec2game.d4.contracts import (
    build_round_contracts,
    manifest_sha256,
    validate_round_manifest,
)
from spec2game.execution import benchmark as benchmark_module


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAIN = PROJECT_ROOT / "main.py"


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(MAIN), *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def _payload(process: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert process.stdout.strip(), process.stderr
    value = json.loads(process.stdout)
    assert isinstance(value, dict), process.stdout
    return value


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _build_local_round(root: Path, round_id: str = "round-001") -> Path:
    config = load_config()
    round_dir = root / round_id
    build_round_contracts(
        round_dir,
        games(config),
        config=config,
        generator=_mock_contract_generator(config),
        round_id=round_id,
        timestamp="2026-08-28T00:00:00+00:00",
    )
    return round_dir


def test_contract_cli_locks_external_round_with_spaces_and_reuses_it(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "external workspace with spaces"
    first = _run_cli(
        "--workspace",
        str(workspace),
        "contract",
        "build",
        "--mock",
        "--round-id",
        "round-001",
    )
    assert first.returncode == 0, first.stderr
    first_payload = _payload(first)
    assert first_payload["status"] == "passed"

    round_dir = workspace / "rounds" / "round-001"
    root_manifest_path = round_dir / "manifest.json"
    canonical_path = round_dir / "contracts" / "manifest.json"
    root_manifest = json.loads(root_manifest_path.read_text(encoding="utf-8"))
    canonical_manifest = json.loads(canonical_path.read_text(encoding="utf-8"))
    assert root_manifest == canonical_manifest
    assert canonical_manifest["manifest_sha256"] == manifest_sha256(canonical_manifest)
    assert len(canonical_manifest["games"]) == 15
    contract_files = [
        path for path in (round_dir / "contracts").glob("*.json")
        if path.name in {entry["path"] for entry in canonical_manifest["contracts"].values()}
    ]
    assert len(contract_files) == 15

    before = {
        path.relative_to(round_dir).as_posix(): path.read_bytes()
        for path in [root_manifest_path, canonical_path, *contract_files]
    }
    second = _run_cli(
        "--workspace",
        str(workspace),
        "contract",
        "build",
        "--mock",
        "--round-id",
        "round-001",
    )
    assert second.returncode == 0, second.stderr
    second_payload = _payload(second)
    assert second_payload["manifest_sha256"] == first_payload["manifest_sha256"]
    after = {
        path.relative_to(round_dir).as_posix(): path.read_bytes()
        for path in [root_manifest_path, canonical_path, *contract_files]
    }
    assert after == before
    assert not (PROJECT_ROOT / "runs").exists()
    assert not (PROJECT_ROOT / "rounds").exists()


@pytest.mark.parametrize("tamper", ["contract", "pointer", "input", "round"])
def test_round_lock_rejects_contract_pointer_input_and_round_drift(
    tmp_path: Path,
    tamper: str,
) -> None:
    round_dir = _build_local_round(tmp_path)
    canonical_path = round_dir / "contracts" / "manifest.json"
    root_path = round_dir / "manifest.json"
    manifest = json.loads(canonical_path.read_text(encoding="utf-8"))

    if tamper == "contract":
        contract_path = round_dir / "contracts" / "snake.json"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["target"] = "tampered target"
        _write_json(contract_path, contract)
    elif tamper == "pointer":
        pointer = json.loads(root_path.read_text(encoding="utf-8"))
        pointer["created_at"] = "tampered pointer"
        _write_json(root_path, pointer)
    elif tamper == "input":
        manifest["inputs"]["snake"]["input_sha256"] = "0" * 64
        manifest["manifest_sha256"] = manifest_sha256(manifest)
        _write_json(canonical_path, manifest)
        _write_json(root_path, manifest)
    else:
        manifest["round_id"] = "round-002"
        manifest["manifest_sha256"] = manifest_sha256(manifest)
        _write_json(canonical_path, manifest)
        _write_json(root_path, manifest)

    with pytest.raises(ValueError):
        validate_round_manifest(
            json.loads(canonical_path.read_text(encoding="utf-8")),
            round_dir=round_dir,
            expected_slugs=list(manifest["games"]),
        )


def test_benchmark_binds_every_task_to_one_locked_round(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config()
    workspace = tmp_path / "external benchmark workspace"
    observed: list[tuple[str, str, Path, str]] = []
    real_build = build_round_contracts

    def build_mock_round(
        round_dir: Path,
        active_games: object,
        *,
        config: object,
        round_id: str,
    ) -> dict[str, object]:
        assert isinstance(config, dict)
        return real_build(
            round_dir,
            active_games,  # type: ignore[arg-type]
            config=config,
            generator=_mock_contract_generator(config),
            round_id=round_id,
            timestamp="2026-08-28T00:00:00+00:00",
        )

    def complete_task(**kwargs: object) -> dict[str, object]:
        game = kwargs["game"]
        observed.append(
            (
                game.slug,  # type: ignore[union-attr]
                str(kwargs["round_id"]),
                Path(str(kwargs["round_dir"])),
                str(kwargs["contract_manifest_sha256"]),
            )
        )
        return {"status": "completed", "official_total": 68.5}

    monkeypatch.setenv("DASHSCOPE_API_KEY", "integration-test-key")
    monkeypatch.setenv("AWS_MANTLE_API_KEY", "integration-test-key")
    monkeypatch.setattr(benchmark_module, "build_round_contracts", build_mock_round)
    monkeypatch.setattr(benchmark_module, "run_task", complete_task)
    state = benchmark_module.run_benchmark(
        workspace=workspace,
        run_id="run-001",
        round_id="round-001",
        progress=lambda _message: None,
    )

    round_dir = workspace / "rounds" / "round-001"
    manifest = json.loads(
        (round_dir / "contracts" / "manifest.json").read_text(encoding="utf-8")
    )
    assert [game for game, *_rest in observed] == [game.slug for game in games(config)]
    assert len(observed) == 15
    assert {
        (round_id, round_path, manifest_sha)
        for _game, round_id, round_path, manifest_sha in observed
    } == {("round-001", round_dir, manifest["manifest_sha256"])}
    assert {
        (record["round_id"], record["contract_manifest_sha256"])
        for record in state["matrix"]
    } == {("round-001", manifest["manifest_sha256"])}


def test_benchmark_can_run_one_selected_game(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "external benchmark workspace"
    observed: list[str] = []
    real_build = build_round_contracts

    def build_mock_round(
        round_dir: Path,
        active_games: object,
        *,
        config: object,
        round_id: str,
    ) -> dict[str, object]:
        assert isinstance(config, dict)
        return real_build(
            round_dir,
            active_games,  # type: ignore[arg-type]
            config=config,
            generator=_mock_contract_generator(config),
            round_id=round_id,
            timestamp="2026-08-28T00:00:00+00:00",
        )

    def complete_task(**kwargs: object) -> dict[str, object]:
        game = kwargs["game"]
        observed.append(game.slug)  # type: ignore[union-attr]
        return {"status": "completed", "official_total": 68.5}

    monkeypatch.setenv("DASHSCOPE_API_KEY", "integration-test-key")
    monkeypatch.setenv("AWS_MANTLE_API_KEY", "integration-test-key")
    monkeypatch.setattr(benchmark_module, "build_round_contracts", build_mock_round)
    monkeypatch.setattr(benchmark_module, "run_task", complete_task)
    state = benchmark_module.run_benchmark(
        workspace=workspace,
        run_id="snake-run-001",
        round_id="round-001",
        game_slug="snake",
        progress=lambda _message: None,
    )

    assert observed == ["snake"]
    assert [record["game"] for record in state["matrix"]] == ["snake"]
    assert state["policy_descriptor"]["selected_game_slugs"] == ["snake"]


def test_selected_benchmark_reuses_a_full_round_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "external benchmark workspace"
    round_dir = _build_local_round(workspace / "rounds", "round-full")
    manifest = json.loads(
        (round_dir / "contracts" / "manifest.json").read_text(encoding="utf-8")
    )
    observed: list[str] = []

    def complete_task(**kwargs: object) -> dict[str, object]:
        game = kwargs["game"]
        observed.append(game.slug)  # type: ignore[union-attr]
        return {"status": "completed", "official_total": 68.5}

    monkeypatch.setenv("DASHSCOPE_API_KEY", "integration-test-key")
    monkeypatch.setenv("AWS_MANTLE_API_KEY", "integration-test-key")
    monkeypatch.setattr(benchmark_module, "run_task", complete_task)
    state = benchmark_module.run_benchmark(
        workspace=workspace,
        run_id="snake-full-round-run-001",
        round_id="round-full",
        game_slug="snake",
        progress=lambda _message: None,
    )

    assert observed == ["snake"]
    assert state["contract_manifest_sha256"] == manifest["manifest_sha256"]
    assert [record["game"] for record in state["matrix"]] == ["snake"]


def test_selected_game_task_validates_locked_manifest_without_selected_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config()
    game = game_by_slug(config, "snake")
    model = models(config)[0]
    round_dir = tmp_path / "rounds" / "round-snake"
    build_round_contracts(
        round_dir,
        [game],
        config=config,
        generator=_mock_contract_generator(config),
        round_id="round-snake",
        timestamp="2026-08-28T00:00:00+00:00",
    )
    manifest = json.loads(
        (round_dir / "contracts" / "manifest.json").read_text(encoding="utf-8")
    )
    observed: list[object | None] = []

    def stop_after_validation(
        value: object,
        *,
        round_dir: object,
        expected_slugs: object | None = None,
        **_kwargs: object,
    ) -> dict[str, object]:
        observed.append(expected_slugs)
        raise RuntimeError("stop after manifest validation")

    monkeypatch.setattr(
        benchmark_module,
        "validate_round_manifest",
        stop_after_validation,
    )
    with pytest.raises(RuntimeError, match="stop after manifest validation"):
        benchmark_module.run_task(
            run_dir=tmp_path / "runs" / "run-snake",
            game=game,
            model=model,
            repetition=1,
            config=config,
            round_id="round-snake",
            round_dir=round_dir,
            contract_manifest_sha256=str(manifest["manifest_sha256"]),
            resume=True,
            selected_game_slugs=["snake"],
            progress=lambda _message: None,
        )

    assert observed == [None]


def test_generation_gap_skips_generation_and_evaluation_until_explicit_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config()
    workspace = tmp_path / "external benchmark workspace"
    round_dir = _build_local_round(workspace / "rounds", "round-generation-gap")
    manifest = json.loads(
        (round_dir / "contracts" / "manifest.json").read_text(encoding="utf-8")
    )
    game = game_by_slug(config, "snake")
    model = models(config)[0]
    run_dir = workspace / "runs" / "generation-gap-run"
    task_dir = run_dir / "tasks" / f"{game.slug}__{model.id}__r01"
    task_dir.mkdir(parents=True)
    descriptor = benchmark_module._task_policy_descriptor(config, game, manifest)
    failure = {
        "stage": "game",
        "attempts_made": 2,
        "error": "incomplete generation output",
    }
    state = benchmark_module._initial_task_state(
        game,
        model,
        1,
        benchmark_module.sha256_json(descriptor),
        "round-generation-gap",
        manifest["manifest_sha256"],
        descriptor,
    )
    state.update(
        {
            "status": "needs_regeneration",
            "official_total": None,
            "generation_failure": failure,
        }
    )
    state["stages"]["generation"].update(
        {
            "status": "needs_regeneration",
            "failed_stage": "game",
            "generation_failure": failure,
        }
    )
    _write_json(task_dir / "run_state.json", state)
    _write_json(task_dir / "generation_failure.json", {"stage": "game", "failure": failure})
    calls: list[str] = []

    def should_not_evaluate(**_kwargs: object) -> dict[str, object]:
        calls.append("evaluate")
        raise AssertionError("evaluation must not run for a generation gap")

    monkeypatch.setattr(benchmark_module, "evaluate_candidate", should_not_evaluate)
    result = benchmark_module.run_task(
        run_dir=run_dir,
        game=game,
        model=model,
        repetition=1,
        config=config,
        round_id="round-generation-gap",
        round_dir=round_dir,
        contract_manifest_sha256=manifest["manifest_sha256"],
        resume=True,
        resume_generation=False,
        progress=lambda _message: None,
    )

    assert result["status"] == "needs_regeneration"
    assert result["official_total"] is None
    assert calls == []
    assert json.loads((task_dir / "summary.json").read_text(encoding="utf-8"))["status"] == "needs_regeneration"


def _installed_console_script(command: str = "spec2game") -> Path | None:
    found = shutil.which(command)
    if found:
        return Path(found)
    roots: list[Path] = []
    scripts = sysconfig.get_path("scripts")
    if scripts:
        roots.append(Path(scripts))
    user_base = Path(site.getuserbase())
    roots.extend(
        (
            user_base / f"Python{sys.version_info.major}{sys.version_info.minor}" / "Scripts",
            Path(sys.executable).parent / "Scripts",
        )
    )
    for root in roots:
        for name in (f"{command}.exe", f"{command}.cmd", command):
            candidate = root / name
            if candidate.is_file():
                return candidate
    return None


def test_main_and_installed_console_entrypoint_have_matching_core_behavior() -> None:
    script = _installed_console_script()
    if script is None:
        pytest.skip("installed spec2game console script is unavailable")
    main_result = _run_cli("validate")
    console_result = subprocess.run(
        [str(script), "validate"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert main_result.returncode == 0, main_result.stderr
    assert console_result.returncode == 0, console_result.stderr
    main_payload = _payload(main_result)
    console_payload = json.loads(console_result.stdout)
    assert console_payload == main_payload


def test_legacy_code2play_console_alias_has_matching_core_behavior() -> None:
    script = _installed_console_script("code2play")
    if script is None:
        pytest.skip("installed code2play compatibility alias is unavailable")
    main_result = _run_cli("validate")
    console_result = subprocess.run(
        [str(script), "validate"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert main_result.returncode == 0, main_result.stderr
    assert console_result.returncode == 0, console_result.stderr
    assert json.loads(console_result.stdout) == _payload(main_result)
