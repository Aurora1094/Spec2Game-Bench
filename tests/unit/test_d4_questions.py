from __future__ import annotations

from pathlib import Path

from PIL import Image

from code2play.config.project import game_by_slug, load_config
from code2play.d4.contracts import build_round_contracts
from code2play.d4.questions import (
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
        generator=_QuestionGenerator(),
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
