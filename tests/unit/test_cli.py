from __future__ import annotations

import json
from pathlib import Path

import pytest

import code2play.providers.dashscope as providers
from code2play.cli import build_parser, main


def test_cli_exposes_required_commands_and_no_response_collection_commands() -> None:
    parser = build_parser()
    args = parser.parse_args(["human", "validate", "--bundle-dir", "bundle"])
    assert args.human_command == "validate"
    assert args.bundle_dir == "bundle"
    command_help = parser.format_help()
    assert "contract" in command_help
    assert "human" in command_help
    assert "human-serve" not in command_help
    assert "human-response-validate" not in command_help


def test_local_smoke_command_does_not_require_api_key(capsys) -> None:
    assert main(["smoke"]) == 0
    assert '"status": "passed"' in capsys.readouterr().out


def test_live_preflight_checks_openrouter_text_and_vision_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str, str]] = []

    class FakeJudge:
        def __init__(self, role: str) -> None:
            self.role = role

        def json_text(self, _instructions: str, _prompt: str, purpose: str) -> dict[str, bool]:
            calls.append((self.role, purpose))
            return {"ok": True}

        def json_vision(
            self,
            _instructions: str,
            _prompt: str,
            images: list[tuple[Path, str]],
            purpose: str,
        ) -> dict[str, bool]:
            assert len(images) == 1
            assert images[0][0].read_bytes().startswith(b"\x89PNG")
            calls.append((self.role, purpose))
            return {"ok": True}

    class FakeRouter:
        def __init__(self, _config: object, _log_root: Path) -> None:
            pass

        def for_role(self, role: str) -> FakeJudge:
            return FakeJudge(role)

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    monkeypatch.setattr(providers, "JudgeRouter", FakeRouter)

    assert main(["--workspace", str(tmp_path), "preflight", "--live"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["api_key_envs"] == ["OPENROUTER_API_KEY"]
    assert payload["judge_routes"]["contract_generation"]["model"] == "qwen/qwen3.7-plus"
    assert payload["judge_routes"]["artistic_visual"]["model"] == "google/gemini-3.8-flash"
    assert payload["live_api_check"] is True
    assert calls == [
        ("contract_generation", "d4_contract_preflight"),
        ("artistic_visual", "d4_1_artistic_visual_quality"),
    ]


def test_live_preflight_rejects_missing_openrouter_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    assert main(["--workspace", str(tmp_path), "preflight", "--live"]) == 2
    assert "Missing Judge API key environment variable(s): OPENROUTER_API_KEY" in capsys.readouterr().out
