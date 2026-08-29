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

from code2play.cli import _mock_contract_generator
from code2play.config.project import games, load_config
from code2play.d4.contracts import (
    build_round_contracts,
    manifest_sha256,
    validate_round_manifest,
)
from code2play.execution import benchmark as benchmark_module


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
        if path.name != "manifest.json"
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


def _installed_console_script() -> Path | None:
    found = shutil.which("code2play")
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
        for name in ("code2play.exe", "code2play.cmd", "code2play"):
            candidate = root / name
            if candidate.is_file():
                return candidate
    return None


def test_main_and_installed_console_entrypoint_have_matching_core_behavior() -> None:
    script = _installed_console_script()
    if script is None:
        pytest.skip("installed code2play console script is unavailable")
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
