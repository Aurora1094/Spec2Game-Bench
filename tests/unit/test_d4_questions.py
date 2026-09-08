from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from code2play.config.project import game_by_slug, load_config
from code2play.d4.contracts import build_round_contracts
from code2play.d4.questions import (
    _normalize_options,
    _question_operations,
    build_d43_question_pack_single_pass,
    validate_d43_question_pack,
)
from code2play.cli import _mock_contract_generator
from code2play.generation.prompt_builder import load_spec


class _QuestionGenerator:
    def json_vision(self, _instructions, _prompt, _images, _purpose):
        return {
            "questions": [
                {
                    "options": {"A": "move left", "B": "move right"},
                    "correct_choice": "A",
                    "answer_rationale": "The visible target is on the left.",
                },
                {
                    "options": {"A": "move left", "B": "move right"},
                    "correct_choice": "B",
                    "answer_rationale": "The visible target is on the right.",
                },
            ]
        }


class _ValidatedQuestionGenerator:
    def json_vision_validated(self, instructions, prompt, images, purpose, validator):
        assert callable(validator)
        value = _QuestionGenerator().json_vision(instructions, prompt, images, purpose)
        validator(value)
        return value


class _FailingQuestionGenerator:
    def json_vision(self, *_args, **_kwargs):
        raise RuntimeError("transport unavailable")


class _GroupedKeyQuestionGenerator:
    def json_vision(self, _instructions, _prompt, _images, _purpose):
        return {
            "questions": [
                {
                    "options": {"A": "press D", "B": "press S"},
                    "correct_choice": "B",
                    "answer_rationale": "The food is below the snake.",
                },
                {
                    "options": {"A": "press A", "B": "press W"},
                    "correct_choice": "B",
                    "answer_rationale": "The upward turn is the legal route.",
                },
            ]
        }


class _TargetSpecificQuestionGenerator:
    def json_vision(self, _instructions, _prompt, _images, _purpose):
        normal = "Click a visible Normal Mole with the left mouse button."
        golden = "Click a visible Golden Mole with the left mouse button."
        return {
            "questions": [
                {
                    "options": {"A": normal, "B": golden},
                    "correct_choice": "A",
                    "answer_rationale": "A normal mole is visibly active.",
                },
                {
                    "options": {"A": normal, "B": golden},
                    "correct_choice": "B",
                    "answer_rationale": "A golden mole is visibly active.",
                },
            ]
        }


def _fixture(tmp_path: Path):
    config = load_config()
    game = game_by_slug(config, "snake")
    round_dir = tmp_path / "round"
    manifest = build_round_contracts(
        round_dir,
        [game],
        config=config,
        generator=_mock_contract_generator(config),
        round_id="round",
    )
    import json

    contract = json.loads((round_dir / "contracts" / "snake.json").read_text(encoding="utf-8"))
    spec = load_spec(game.spec)
    dynamic = [
        row for row in spec["evaluation"]["d2"]["checkpoints"]
        if row["dimension"] == "D2.2" and row["kind"] == "dynamic"
    ]
    images: list[Path] = []
    records = []
    for index, row in enumerate(dynamic[:2]):
        image_path = tmp_path / f"frame-{index}.png"
        Image.new("RGB", (64, 64), (255, 0, 0) if index == 0 else (0, 0, 255)).save(image_path)
        images.append(image_path)
        records.append(
            {
                "id": row["id"],
                "status": "completed",
                "frames": [
                    {
                        "path": str(image_path),
                        "snapshot": {"target": index},
                        "case": "fixture",
                        "phase": "after",
                        "offset_seconds": 0.1,
                    }
                ],
            }
        )
    sample = {"d4_2": records}
    return contract, spec, sample, manifest


def test_dynamic_questions_bind_real_images_deterministically(tmp_path: Path) -> None:
    contract, spec, sample, _manifest = _fixture(tmp_path)
    candidate_sha = "b" * 64
    pack = build_d43_question_pack_single_pass(
        d4_contract=contract,
        d2_checkpoints=spec["evaluation"]["d2"]["checkpoints"],
        sample_manifest=sample,
        candidate_project_sha256=candidate_sha,
        generator=_ValidatedQuestionGenerator(),
    )
    assert pack["status"] == "completed"
    assert [item["source_slot"] for item in pack["questions"]] == [1, 2]
    validate_d43_question_pack(
        pack,
        d4_contract=contract,
        sample_manifest=sample,
        candidate_project_sha256=candidate_sha,
    )

    failed = build_d43_question_pack_single_pass(
        d4_contract=contract,
        d2_checkpoints=spec["evaluation"]["d2"]["checkpoints"],
        sample_manifest=sample,
        candidate_project_sha256=candidate_sha,
        generator=_FailingQuestionGenerator(),
    )
    assert failed["status"] == "judge_output_unavailable"
    assert failed["candidate_failure_proven"] is False


def test_grouped_keyboard_operations_accept_concrete_key_choices(tmp_path: Path) -> None:
    contract, spec, sample, _manifest = _fixture(tmp_path)
    contract["allowed_operations"] = [
        "press W, A, S, or D to change the snake's movement direction",
    ]
    candidate_sha = "c" * 64

    pack = build_d43_question_pack_single_pass(
        d4_contract=contract,
        d2_checkpoints=spec["evaluation"]["d2"]["checkpoints"],
        sample_manifest=sample,
        candidate_project_sha256=candidate_sha,
        generator=_GroupedKeyQuestionGenerator(),
    )

    assert pack["status"] == "completed"
    assert pack["questions"][0]["options"] == {"A": "press D", "B": "press S"}
    validate_d43_question_pack(
        pack,
        d4_contract=contract,
        sample_manifest=sample,
        candidate_project_sha256=candidate_sha,
    )


def test_target_specific_questions_require_active_target_evidence(tmp_path: Path) -> None:
    config = load_config()
    game = game_by_slug(config, "whack_a_mole")
    round_dir = tmp_path / "round-whack"
    build_round_contracts(
        round_dir,
        [game],
        config=config,
        generator=_mock_contract_generator(config),
        round_id="round-whack",
    )
    import json

    contract = json.loads(
        (round_dir / "contracts" / "whack_a_mole.json").read_text(encoding="utf-8")
    )
    spec = load_spec(game.spec)
    source_ids = contract["d4_3"]["source_checkpoint_ids"]
    sample_records = []
    for index, source_id in enumerate(source_ids):
        image_path = tmp_path / f"mole-{index}.png"
        Image.new(
            "RGB",
            (64, 64),
            (255, 210, 0) if index else (120, 70, 30),
        ).save(image_path)
        sample_records.append(
            {
                "id": source_id,
                "status": "completed",
                "frames": [
                    {
                        "path": str(image_path),
                        "snapshot": {
                            "current_mole": {
                                "type": "golden" if index else "normal",
                                "visible": True,
                            }
                        },
                        "case": "active_mole",
                        "phase": "before",
                        "offset_seconds": 0.0,
                    }
                ],
            }
        )
    sample = {"d4_2": sample_records}
    candidate_sha = "d" * 64
    pack = build_d43_question_pack_single_pass(
        d4_contract=contract,
        d2_checkpoints=spec["evaluation"]["d2"]["checkpoints"],
        sample_manifest=sample,
        candidate_project_sha256=candidate_sha,
        generator=_TargetSpecificQuestionGenerator(),
    )
    assert pack["status"] == "completed"
    assert [item["source_checkpoint_id"] for item in pack["questions"]] == source_ids

    inactive = {"d4_2": [dict(record) for record in sample_records]}
    inactive["d4_2"][0]["frames"] = [
        {
            **inactive["d4_2"][0]["frames"][0],
            "snapshot": {"current_mole": None, "waiting": True},
        }
    ]
    unavailable = build_d43_question_pack_single_pass(
        d4_contract=contract,
        d2_checkpoints=spec["evaluation"]["d2"]["checkpoints"],
        sample_manifest=inactive,
        candidate_project_sha256=candidate_sha,
        generator=_TargetSpecificQuestionGenerator(),
    )
    assert unavailable["status"] == "candidate_evidence_unavailable"


_PIPE_CLICK = (
    "Left-click a Straight Pipe, Corner Pipe, or T Pipe to rotate it 90° clockwise"
)
_PIPE_SPACE = (
    "Press Space to submit the current configuration and run a complete water-flow check"
)
_FARM_PRESS_1 = "press 1 to select Carrot seed"
_FARM_CLICK = "left-click a plot to use the selected tool or seed"


def test_question_menu_keeps_locked_contract_operations() -> None:
    pipe = [_PIPE_CLICK, _PIPE_SPACE]
    farming = [_FARM_PRESS_1, _FARM_CLICK]
    assert _question_operations(pipe) == pipe
    assert _question_operations(farming) == farming


def test_question_option_aliases_map_to_locked_operations() -> None:
    allowed = [_PIPE_CLICK, _PIPE_SPACE]
    assert _normalize_options(
        {"A": "press Space", "B": _PIPE_CLICK},
        "questions[0].options",
        allowed,
    ) == {"A": "press Space", "B": _PIPE_CLICK}
    with pytest.raises(ValueError, match="not one of the contract operations"):
        _normalize_options(
            {"A": "press Space", "B": "press R"},
            "questions[0].options",
            allowed,
        )
