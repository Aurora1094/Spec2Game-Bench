from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from code2play.execution.protocol_sampling import _compile_checkpoint_programs
from code2play.evaluation.checkpoint_compiler import compile_checkpoint_program_batch
from code2play.providers.dashscope import JudgeAttemptsExhausted


class _RemoteProtocolError(Exception):
    pass


class _BatchFailureCompiler:
    def __init__(self) -> None:
        self.purposes: list[str] = []

    def json_text_validated(
        self,
        _instructions: str,
        _prompt: str,
        purpose: str,
        validator: Any,
    ) -> dict[str, Any]:
        self.purposes.append(purpose)
        if purpose.startswith("d2_compile_batch_"):
            raise ValueError("malformed batch response")
        return validator(
            {
                "checkpoint_id": "snake.D2.1.01",
                "cases": [
                    {
                        "name": "move_right",
                        "actions": [
                            {"command": {"keys_down": ["right"], "dt": 0.1}}
                        ],
                    }
                ],
            }
        )


def test_batch_compiler_failure_falls_back_to_single_checkpoint() -> None:
    compiler = _BatchFailureCompiler()
    checkpoints = [
        {"id": "snake.D2.1.01", "dimension": "D2.1", "kind": "dynamic"}
    ]

    programs, report = _compile_checkpoint_programs(
        checkpoints=checkpoints,
        game_description="A small snake game.",
        functional_requirements=[],
        candidate_source="class GameState: pass",
        initial_snapshot={},
        initial_schema={},
        compiler=compiler,
        max_workers=1,
    )

    assert programs[0]["checkpoint_id"] == "snake.D2.1.01"
    assert report["batch_failure_count"] == 1
    assert report["batch_failures"] == [
        {"batch_id": "D2.1_01", "error_type": "ValueError"}
    ]
    assert report["repair_count"] == 1
    assert compiler.purposes == [
        "d2_compile_batch_D2.1_01",
        "d2_compile_repair_snake.D2.1.01",
    ]


class _ExhaustedCompiler:
    def __init__(self) -> None:
        self.calls = 0
        self.purposes: list[str] = []

    def json_text_validated(
        self,
        _instructions: str,
        _prompt: str,
        purpose: str,
        validator: Any,
    ) -> dict[str, Any]:
        self.calls += 1
        self.purposes.append(purpose)
        raise JudgeAttemptsExhausted(
            purpose=purpose,
            attempts=2,
            error=_RemoteProtocolError("peer closed connection"),
        )


def test_compiler_attempt_exhaustion_propagates_for_rescore_handling() -> None:
    compiler = _ExhaustedCompiler()
    checkpoints = [
        {"id": "snake.D2.1.01", "dimension": "D2.1", "kind": "dynamic"}
    ]

    with pytest.raises(JudgeAttemptsExhausted):
        _compile_checkpoint_programs(
            checkpoints=checkpoints,
            game_description="A small snake game.",
            functional_requirements=[],
            candidate_source="class GameState: pass",
            initial_snapshot={},
            initial_schema={},
            compiler=compiler,
            max_workers=1,
        )

    assert compiler.calls == 1


class _JsonTruncationBatchCompiler:
    def __init__(self) -> None:
        self.purposes: list[str] = []

    def json_text_validated(
        self,
        _instructions: str,
        _prompt: str,
        purpose: str,
        validator: Any,
    ) -> dict[str, Any]:
        self.purposes.append(purpose)
        if purpose.startswith("d2_compile_batch_"):
            raise JudgeAttemptsExhausted(
                purpose=purpose,
                attempts=2,
                error=json.JSONDecodeError("Expecting ',' delimiter", "", 0),
            )
        return validator(
            {
                "checkpoint_id": "snake.D2.1.01",
                "cases": [
                    {
                        "name": "move_right",
                        "actions": [
                            {"command": {"keys_down": ["right"], "dt": 0.1}}
                        ],
                    }
                ],
            }
        )


def test_compiler_batch_json_truncation_falls_back_to_single_checkpoint() -> None:
    compiler = _JsonTruncationBatchCompiler()
    checkpoints = [
        {"id": "snake.D2.1.01", "dimension": "D2.1", "kind": "dynamic"}
    ]

    programs, report = _compile_checkpoint_programs(
        checkpoints=checkpoints,
        game_description="A small snake game.",
        functional_requirements=[],
        candidate_source="class GameState: pass",
        initial_snapshot={},
        initial_schema={},
        compiler=compiler,
        max_workers=1,
    )

    assert programs[0]["checkpoint_id"] == "snake.D2.1.01"
    assert report["batch_failure_count"] == 1
    assert report["batch_failures"] == [
        {"batch_id": "D2.1_01", "error_type": "JSONDecodeError"}
    ]
    assert report["repair_count"] == 1
    assert compiler.purposes == [
        "d2_compile_batch_D2.1_01",
        "d2_compile_repair_snake.D2.1.01",
    ]


def _dynamic_checkpoint(checkpoint_id: str, dimension: str) -> dict[str, str]:
    return {"id": checkpoint_id, "dimension": dimension, "kind": "dynamic"}


def _program(checkpoint_id: str) -> dict[str, Any]:
    return {
        "checkpoint_id": checkpoint_id,
        "cases": [
            {
                "name": "advance",
                "actions": [{"command": {"dt": 0.1}}],
            }
        ],
    }


class _EnvelopeCompiler:
    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.instructions = ""

    def json_text_validated(
        self,
        instructions: str,
        prompt: str,
        purpose: str,
        validator: Any,
    ) -> dict[str, Any]:
        assert purpose == "d2_compile_batch_D2.1_01"
        self.instructions = instructions
        payload = json.loads(prompt.split("Input:", 1)[1])
        checkpoint_ids = [item["id"] for item in payload["textual_checkpoints"]]
        rows = [_program(checkpoint_id) for checkpoint_id in checkpoint_ids]
        if self.mode == "missing":
            rows = rows[:1]
        elif self.mode == "duplicate":
            rows[1]["checkpoint_id"] = rows[0]["checkpoint_id"]
        elif self.mode == "unknown":
            rows[1]["checkpoint_id"] = "other.D2.1.01"
        elif self.mode == "reversed":
            rows = list(reversed(rows))
        return validator({"batch_id": payload["batch_id"], "programs": rows})


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("missing", "omitted checkpoint_id"),
        ("duplicate", "duplicate checkpoint_id"),
        ("unknown", "unknown checkpoint_id"),
        ("reversed", "preserve checkpoint_id input order"),
    ],
)
def test_batch_compiler_rejects_invalid_checkpoint_identity(
    mode: str,
    message: str,
) -> None:
    compiler = _EnvelopeCompiler(mode)
    checkpoints = [
        _dynamic_checkpoint("snake.D2.1.01", "D2.1"),
        _dynamic_checkpoint("snake.D2.1.02", "D2.1"),
    ]

    with pytest.raises(ValueError, match=message):
        compile_checkpoint_program_batch(
            checkpoints,
            game_description="A small snake game.",
            functional_requirements=[],
            candidate_source="class GameState: pass",
            initial_snapshot={},
            initial_schema={},
            compiler=compiler,
            batch_id="D2.1_01",
        )

    assert "batch of one through eight D2 checkpoints" in compiler.instructions


class _RescoreCompiler:
    def __init__(self, log_dir: Path, *, exhausted: bool) -> None:
        self.log_dir = log_dir
        self.exhausted = exhausted
        self.purposes: list[str] = []

    def json_text_validated(
        self,
        _instructions: str,
        prompt: str,
        purpose: str,
        validator: Any,
    ) -> dict[str, Any]:
        self.purposes.append(purpose)
        if self.exhausted:
            raise JudgeAttemptsExhausted(
                purpose=purpose,
                attempts=2,
                error=_RemoteProtocolError("peer closed connection"),
            )
        payload = json.loads(prompt.split("Input:", 1)[1])
        rows = [_program(item["id"]) for item in payload["textual_checkpoints"]]
        return validator({"batch_id": payload["batch_id"], "programs": rows})


def test_compiler_rescore_reuses_prior_validated_batch_and_only_requests_gap(
    tmp_path: Path,
) -> None:
    log_root = tmp_path / "action_compiler"
    previous = log_root / "previous-success"
    previous.mkdir(parents=True)
    successful_checkpoint = _dynamic_checkpoint("snake.D2.1.01", "D2.1")
    (previous / "raw_input.json").write_text(
        json.dumps({"purpose": "d2_compile_batch_D2.1_01"}),
        encoding="utf-8",
    )
    (previous / "parsed_output.json").write_text(
        json.dumps({"programs": [_program(successful_checkpoint["id"])]}),
        encoding="utf-8",
    )
    checkpoints = [
        successful_checkpoint,
        _dynamic_checkpoint("snake.D2.2.01", "D2.2"),
    ]

    failed = _RescoreCompiler(log_root, exhausted=True)
    with pytest.raises(JudgeAttemptsExhausted):
        _compile_checkpoint_programs(
            checkpoints=checkpoints,
            game_description="A small snake game.",
            functional_requirements=[],
            candidate_source="class GameState: pass",
            initial_snapshot={},
            initial_schema={},
            compiler=failed,
            max_workers=1,
        )
    assert failed.purposes == ["d2_compile_batch_D2.2_01"]

    rescore = _RescoreCompiler(log_root, exhausted=False)
    programs, report = _compile_checkpoint_programs(
        checkpoints=checkpoints,
        game_description="A small snake game.",
        functional_requirements=[],
        candidate_source="class GameState: pass",
        initial_snapshot={},
        initial_schema={},
        compiler=rescore,
        max_workers=1,
    )

    assert [program["checkpoint_id"] for program in programs] == [
        "snake.D2.1.01",
        "snake.D2.2.01",
    ]
    assert rescore.purposes == ["d2_compile_batch_D2.2_01"]
    assert report["reused_validated_count"] == 1
    assert report["newly_compiled_count"] == 1
