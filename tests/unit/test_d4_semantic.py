from __future__ import annotations

import json
from pathlib import Path

import pytest

import code2play.evaluation.dimensions.d4.semantic_ux as semantic_ux
from code2play.d4.contracts import D4_CONTRACT_DESIGN_VERSION
from code2play.evaluation.dimensions.d4.semantic_ux import (
    D42_MAX_TRANSITIONS_PER_BATCH,
    _evaluate_d42,
    _payload_sha256,
    evaluate_dimension4_semantic,
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


def _unavailable_subscore(*, max_score: float) -> dict[str, object]:
    return {
        "status": "judge_output_unavailable",
        "score": None,
        "max_score": max_score,
    }


def _scored_subscore(*, score: float, max_score: float) -> dict[str, object]:
    return {"status": "completed", "score": score, "max_score": max_score}


def _patch_d4_evaluation(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    monkeypatch.setattr(
        semantic_ux,
        "load_spec",
        lambda _path: {
            "evaluation": {
                "protocol_version": 4,
                "d2": {"checkpoints": [{"id": "snake.D2.2.01", "kind": "dynamic"}]},
            }
        },
    )
    monkeypatch.setattr(semantic_ux, "validate_d4_contract", lambda contract, **_kwargs: contract)
    monkeypatch.setattr(
        semantic_ux,
        "validate_d43_question_pack",
        lambda pack, **_kwargs: pack,
    )
    monkeypatch.setattr(
        semantic_ux,
        "_evaluate_d41",
        lambda *_args, **_kwargs: calls.append("d41")
        or _scored_subscore(score=1.0, max_score=2.0),
    )
    monkeypatch.setattr(
        semantic_ux,
        "_evaluate_d42",
        lambda *_args, **_kwargs: calls.append("d42")
        or _scored_subscore(score=4.0, max_score=5.0),
    )
    monkeypatch.setattr(
        semantic_ux,
        "_evaluate_d43",
        lambda *_args, **_kwargs: calls.append("d43")
        or _scored_subscore(score=5.0, max_score=5.0),
    )


def _d4_eval_fixture(tmp_path: Path) -> tuple[Path, dict[str, object], dict[str, object], dict[str, object]]:
    contract_path = tmp_path / "contract.json"
    contract_path.write_text("{}", encoding="utf-8")
    contract = {
        "game_slug": "snake",
        "contract_version": "1",
        "contract_sha256": "c" * 64,
        "round_id": "round-test",
        "design_version": D4_CONTRACT_DESIGN_VERSION,
    }
    sample_manifest = {
        "d4_contract_source": "round_locked_manifest",
        "d4_contract_path": str(contract_path.resolve()),
        "d4_contract_version": contract["contract_version"],
        "d4_contract_sha256": contract["contract_sha256"],
        "d4_contract_design_version": D4_CONTRACT_DESIGN_VERSION,
        "d4_compiler": "reused_functionality_compiled_programs",
        "d4_2_checkpoint_selection": "kind_dynamic_only",
        "candidate_received_d4_task_ids": False,
        "candidate_received_d4_contract": False,
        "d4_2": [{"id": "snake.D2.2.01"}],
        "d4_3": [],
    }
    question_pack = {"question_pack_sha256": "q" * 64}
    return contract_path, contract, sample_manifest, question_pack


def test_d4_resume_reruns_unavailable_d41_and_d42(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _patch_d4_evaluation(monkeypatch, calls)
    contract_path, contract, sample_manifest, question_pack = _d4_eval_fixture(tmp_path)
    previous = {
        "status": "completed_with_judge_gap",
        "contract_sha256": contract["contract_sha256"],
        "sample_manifest_sha256": _payload_sha256(sample_manifest),
        "d4_1_artistic_visual_quality": _unavailable_subscore(max_score=2.0),
        "d4_2_feedback_fidelity": _unavailable_subscore(max_score=5.0),
        "d4_3_goal_interaction_inferability": _scored_subscore(score=5.0, max_score=5.0),
    }

    result = evaluate_dimension4_semantic(
        spec_path=tmp_path / "spec.yaml",
        d4_contract=contract,
        contract_path=contract_path,
        sample_manifest=sample_manifest,
        question_pack=question_pack,
        candidate_project_sha256="a" * 64,
        judge=object(),
        previous_detail=previous,
    )

    assert calls == ["d41", "d42", "d43"]
    assert result["reused_previous_non_question_scores"] is False
    assert result["d4_1_artistic_visual_quality"]["score"] == 1.0
    assert result["d4_2_feedback_fidelity"]["score"] == 4.0


def test_d4_resume_reuses_numeric_d41_and_d42(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _patch_d4_evaluation(monkeypatch, calls)
    contract_path, contract, sample_manifest, question_pack = _d4_eval_fixture(tmp_path)
    previous_d41 = _scored_subscore(score=1.5, max_score=2.0)
    previous_d42 = _scored_subscore(score=3.0, max_score=5.0)
    previous = {
        "status": "completed_with_judge_gap",
        "contract_sha256": contract["contract_sha256"],
        "sample_manifest_sha256": _payload_sha256(sample_manifest),
        "d4_1_artistic_visual_quality": previous_d41,
        "d4_2_feedback_fidelity": previous_d42,
        "d4_3_goal_interaction_inferability": _unavailable_subscore(max_score=5.0),
    }

    result = evaluate_dimension4_semantic(
        spec_path=tmp_path / "spec.yaml",
        d4_contract=contract,
        contract_path=contract_path,
        sample_manifest=sample_manifest,
        question_pack=question_pack,
        candidate_project_sha256="a" * 64,
        judge=object(),
        previous_detail=previous,
    )

    assert calls == ["d43"]
    assert result["reused_previous_non_question_scores"] is True
    assert result["d4_1_artistic_visual_quality"] == previous_d41
    assert result["d4_2_feedback_fidelity"] == previous_d42
