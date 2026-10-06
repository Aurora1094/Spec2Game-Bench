from __future__ import annotations

import pytest

from spec2game.evaluation.dimensions.d2.protocol_evaluator import (
    CARROT_DEFENSE_MAX_CHECKPOINT_JUDGE_PROMPT_CHARS,
    MAX_CHECKPOINT_JUDGE_PROMPT_CHARS,
    _is_carrot_defense_checkpoint,
    _max_checkpoint_judge_prompt_chars,
    _partition_dimension_batches,
)


def _carrot_checkpoint() -> dict[str, object]:
    return {
        "id": "carrot_defense.D2.5.02",
        "dimension": "D2.5",
        "kind": "dynamic",
        "item": "clear a wave",
        "objective": "The required behavior is observable.",
        "initial_state": "A valid initial game state.",
        "trigger": "Advance time until the wave ends.",
        "expected_transition": "The wave is cleared.",
        "detection_method": "state trace",
        "score_rubric": "0 missing; 1 partial; 2 complete",
        "source_jsonl": "D2.5.jsonl",
        "source_row": 2,
    }


def _trace(checkpoint_id: str, *, state_chars: int) -> dict[str, object]:
    return {
        "id": checkpoint_id,
        "status": "completed",
        "compiled_program": {"cases": []},
        "cases": [
            {
                "observations": [
                    {
                        "action_state": {"state": "x" * state_chars},
                        "snapshot": {"state": "x" * state_chars},
                    }
                ],
            }
        ],
    }


def test_carrot_defense_variants_use_raised_d2_prompt_limit() -> None:
    assert _is_carrot_defense_checkpoint("carrot_defense.D2.5.02")
    assert _is_carrot_defense_checkpoint("carrot_defense_var05.D2.3.11")
    assert not _is_carrot_defense_checkpoint("snake.D2.1.01")
    assert (
        _max_checkpoint_judge_prompt_chars("carrot_defense_var09.D2.5.01")
        == CARROT_DEFENSE_MAX_CHECKPOINT_JUDGE_PROMPT_CHARS
    )
    assert _max_checkpoint_judge_prompt_chars("tetris.D2.3.08") == MAX_CHECKPOINT_JUDGE_PROMPT_CHARS


def test_carrot_defense_partition_allows_prompt_above_default_hard_limit() -> None:
    checkpoint = _carrot_checkpoint()
    oversized_for_default = _trace(
        str(checkpoint["id"]),
        state_chars=MAX_CHECKPOINT_JUDGE_PROMPT_CHARS + 1,
    )
    batches = _partition_dimension_batches(
        "D2.5",
        [checkpoint],
        {str(checkpoint["id"]): oversized_for_default},
        source="",
        game_description="A tower-defense game.",
    )
    assert batches[0][1] > MAX_CHECKPOINT_JUDGE_PROMPT_CHARS
    assert batches[0][1] <= CARROT_DEFENSE_MAX_CHECKPOINT_JUDGE_PROMPT_CHARS

    too_large = _trace(
        str(checkpoint["id"]),
        state_chars=CARROT_DEFENSE_MAX_CHECKPOINT_JUDGE_PROMPT_CHARS + 1,
    )
    with pytest.raises(ValueError, match=r"carrot_defense\.D2\.5\.02 remains too large"):
        _partition_dimension_batches(
            "D2.5",
            [checkpoint],
            {str(checkpoint["id"]): too_large},
            source="",
            game_description="A tower-defense game.",
        )
