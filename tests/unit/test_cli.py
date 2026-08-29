from __future__ import annotations

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
