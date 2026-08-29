from __future__ import annotations

import json
from pathlib import Path

from code2play.evaluation.dimensions.d4.semantic_ux import (
    D42_MAX_TRANSITIONS_PER_BATCH,
    _evaluate_d42,
)


class _BatchJudge:
    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def json_vision_validated(
        self,
        _instructions,
        prompt,
        images,
        *,
        purpose,
        validator,
    ):
        assert purpose.startswith("d4_2_batch_D2.2")
        rows = json.loads(prompt)["transition_batch"]
        self.batch_sizes.append(len(rows))
        assert len(images) == len(rows)
        response = {
            "results": [
                {
                    "checkpoint_id": row["checkpoint"]["id"],
                    "faithfulness": 5,
                    "completeness": 5,
                    "timeliness": 5,
                }
                for row in rows
            ]
        }
        return validator(response)


def test_d42_splits_large_dimension_batches_before_calling_judge(tmp_path: Path) -> None:
    checkpoints = [
        {
            "id": f"snake.D2.2.{index:02d}",
            "dimension": "D2.2",
            "kind": "dynamic",
            "objective": "Move the snake.",
        }
        for index in range(1, D42_MAX_TRANSITIONS_PER_BATCH + 2)
    ]
    samples = {
        "d4_2": [
            {
                "id": checkpoint["id"],
                "status": "completed",
                "compiled_program": {"steps": []},
                "frames": [
                    {
                        "path": str(tmp_path / f"{checkpoint['id']}.png"),
                        "phase": "after",
                        "offset_seconds": 0.1,
                    }
                ],
            }
            for checkpoint in checkpoints
        ]
    }
    judge = _BatchJudge()

    result = _evaluate_d42(checkpoints, samples, judge)

    assert judge.batch_sizes == [D42_MAX_TRANSITIONS_PER_BATCH, 1]
    assert result["transition_checkpoint_count"] == len(checkpoints)
    assert all(size <= D42_MAX_TRANSITIONS_PER_BATCH for size in judge.batch_sizes)
