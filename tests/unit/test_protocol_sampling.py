from __future__ import annotations

from typing import Any

from code2play.execution.protocol_sampling import _compile_checkpoint_programs


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
