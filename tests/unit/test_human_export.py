from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

from code2play.cli import _mock_contract_generator
from code2play.config.project import game_by_slug, load_config
from code2play.d4.contracts import build_round_contracts
from code2play.execution.candidate_project import CandidateProject
from code2play.human_review.artifacts import (
    SOURCE_RELATIVE,
    build_human_evidence,
    export_blind_bundle,
    validate_blind_bundle,
)
from code2play.human_review.policy import HUMAN_REVIEW_CONSTRUCT_COUNTS, HUMAN_REVIEW_DESIGN_ID


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _candidate(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "__init__.py").write_text('"""Benchmark-managed candidate package."""\n', encoding="utf-8")
    (path / "state.py").write_text(
        "class GameState:\n    pass\n\ndef create_initial_state(seed=0):\n    return GameState()\n\ndef state_to_dict(state):\n    return {}\n",
        encoding="utf-8",
    )
    (path / "game.py").write_text(
        "from .state import GameState\n\nclass GameEngine:\n    def __init__(self, seed=0): self._state = GameState()\n    def reset(self): pass\n    def action(self, action): pass\n    def snapshot(self): return {}\n    @property\n    def state(self): return self._state\n",
        encoding="utf-8",
    )
    (path / "rendering.py").write_text(
        "class GameRenderer:\n    def __init__(self): pass\n    def render(self, state=None): return None\n    def close(self): pass\n",
        encoding="utf-8",
    )
    (path / "main.py").write_text(
        "class GameBenchAdapter:\n    def __init__(self, seed=0): pass\n    def init(self): return {}\n    def action(self, action): pass\n    def snapshot(self): return {}\n    def render(self): return None\n    def close(self): pass\n\ndef create_gamebench_adapter(seed=0): return GameBenchAdapter(seed)\n\ndef main(): pass\n",
        encoding="utf-8",
    )


def test_human_export_separates_public_package_and_private_mapping(tmp_path: Path) -> None:
    config = load_config()
    game = game_by_slug(config, "snake")
    round_dir = tmp_path / "round"
    build_round_contracts(
        round_dir,
        [game],
        config=config,
        generator=_mock_contract_generator(config),
        round_id="round",
    )
    task_dir = tmp_path / "task"
    candidate_dir = task_dir / "candidate"
    _candidate(candidate_dir)
    candidate_sha = CandidateProject(candidate_dir).project_sha256()
    trace_path = task_dir / "evaluation" / "trace.json"
    _write_json(trace_path, {"status": "completed", "cases": []})
    checkpoint_id = "snake.D2.1.02"
    _write_json(
        task_dir / "evaluation" / "d2.json",
        {"evidence": {"checkpoint_results": [{"id": checkpoint_id, "earned": 2, "possible": 2, "trace_path": str(trace_path)}]}},
    )
    _write_json(
        task_dir / "evaluation" / "d3.json",
        {"result": {"semantic_judge": {"criterion_scores": {key: 80 for key in ("maintainability", "reliability", "security", "efficiency", "conformance")}}}},
    )
    _write_json(task_dir / "evaluation" / "d4.json", {})
    _write_json(task_dir / "evaluation" / "d4_question_pack.json", {"status": "candidate_evidence_unavailable", "questions": [], "evidence": [], "candidate_failures": []})
    _write_json(task_dir / "evaluation" / "d4_sample_manifest.json", {"d4_contract_path": str(round_dir / "contracts" / "snake.json")})
    _write_json(task_dir / "summary.json", {"task": {"game": "snake", "model": "secret-candidate", "candidate_project_sha256": candidate_sha}})

    export = export_blind_bundle(task_dir, tmp_path / "questionnaires", blind_id="candidate-001")
    assert export["validation"]["status"] == "passed"
    public = Path(export["public_bundle"])
    private = Path(export["private_mapping"])
    assert validate_blind_bundle(public)["status"] == "passed"
    public_text = (public / "items.jsonl").read_text(encoding="utf-8")
    assert "secret-candidate" not in public_text
    assert "snake.D2.1.01" not in public_text
    assert '"automatic_score"' not in public_text
    assert private.read_text(encoding="utf-8").find("secret-candidate") >= 0

    source_root = task_dir / SOURCE_RELATIVE
    source_manifest = json.loads((source_root / "manifest.json").read_text(encoding="utf-8"))
    source_items = [
        json.loads(line)
        for line in (source_root / "items.private.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert source_manifest["questionnaire_design_id"] == HUMAN_REVIEW_DESIGN_ID
    assert source_manifest["item_count"] == 10
    assert Counter(item["construct"] for item in source_items) == HUMAN_REVIEW_CONSTRUCT_COUNTS
    assert sum(item["rateability"] == "rateable" for item in source_items) == 1
    assert all(
        item["rateability"] == "cannot_rate"
        for item in source_items
        if item["construct"] in {"visual_question_validity", "visual_question_answer"}
    )
    assert not any(
        item["construct"] in {"semantic_code_quality", "specification_deviation"}
        for item in source_items
    )

    source_manifest["questionnaire_policy_sha256"] = "0" * 64
    _write_json(source_root / "manifest.json", source_manifest)
    rebuilt = export_blind_bundle(task_dir, tmp_path / "questionnaires-rebuilt", blind_id="candidate-002")
    assert rebuilt["validation"]["status"] == "passed"
    assert json.loads((source_root / "manifest.json").read_text(encoding="utf-8"))["questionnaire_policy_sha256"] != "0" * 64


def test_human_evidence_recovers_locked_round_contract_before_d4_sampling(
    tmp_path: Path,
) -> None:
    config = load_config()
    game = game_by_slug(config, "snake")
    workspace = tmp_path / "workspace"
    round_dir = workspace / "rounds" / "round-001"
    round_manifest = build_round_contracts(
        round_dir,
        [game],
        config=config,
        generator=_mock_contract_generator(config),
        round_id="round-001",
    )
    task_dir = workspace / "runs" / "run-001" / "tasks" / "snake__candidate__r01"
    candidate_dir = task_dir / "candidate"
    _candidate(candidate_dir)
    candidate_sha = CandidateProject(candidate_dir).project_sha256()
    _write_json(
        task_dir / "run_state.json",
        {
            "policy_descriptor": {
                "d4_contract": {
                    "configured": True,
                    "status": "locked",
                    "round_id": "round-001",
                    "manifest_sha256": round_manifest["manifest_sha256"],
                }
            },
            "task": {"game": "snake"},
        },
    )
    _write_json(
        task_dir / "summary.json",
        {"task": {"game": "snake", "candidate_project_sha256": candidate_sha}},
    )

    manifest = build_human_evidence(task_dir)
    source_items = [
        json.loads(line)
        for line in (task_dir / SOURCE_RELATIVE / "items.private.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]

    assert manifest["item_count"] == 10
    assert all(item["rateability"] == "cannot_rate" for item in source_items)


def test_human_evidence_uses_preregistered_anchor_order_with_complete_evidence(
    tmp_path: Path,
) -> None:
    config = load_config()
    game = game_by_slug(config, "snake")
    round_dir = tmp_path / "round"
    build_round_contracts(
        round_dir,
        [game],
        config=config,
        generator=_mock_contract_generator(config),
        round_id="round",
    )
    task_dir = tmp_path / "task"
    candidate_dir = task_dir / "candidate"
    _candidate(candidate_dir)
    candidate_sha = CandidateProject(candidate_dir).project_sha256()
    d2_anchor_ids = (
        "snake.D2.1.02",
        "snake.D2.2.01",
        "snake.D2.3.04",
        "snake.D2.4.01",
        "snake.D2.5.01",
    )
    d42_anchor_ids = ("snake.D2.2.01", "snake.D2.3.04")
    d2_results = []
    for index, checkpoint_id in enumerate(reversed(d2_anchor_ids), start=1):
        trace_path = task_dir / "evaluation" / "traces" / f"trace-{index}.json"
        _write_json(trace_path, {"status": "completed", "cases": []})
        d2_results.append(
            {
                "id": checkpoint_id,
                "earned": 2,
                "possible": 2,
                "trace_path": str(trace_path),
            }
        )
    _write_json(task_dir / "evaluation" / "d2.json", {"evidence": {"checkpoint_results": d2_results}})

    art_image = task_dir / "evaluation" / "images" / "art.png"
    dynamic_image = task_dir / "evaluation" / "images" / "dynamic.png"
    question_image = task_dir / "evaluation" / "images" / "question.png"
    for image_path in (art_image, dynamic_image, question_image):
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(b"test-image")
    _write_json(
        task_dir / "evaluation" / "model_calls" / "artistic_visual" / "call" / "raw_input.json",
        {"images": [{"path": str(art_image)}]},
    )
    transitions = []
    for checkpoint_id in reversed(d42_anchor_ids):
        transitions.append(
            {
                "id": checkpoint_id,
                "status": "completed",
                "score": 4.0,
                "component_scores": {
                    "faithfulness": 4.0,
                    "completeness": 4.0,
                    "timeliness": 4.0,
                },
                "compiled_program": [{"action": "noop"}],
                "frames": [
                    {"path": str(dynamic_image), "phase": "before"},
                    {"path": str(dynamic_image), "phase": "during"},
                    {"path": str(dynamic_image), "phase": "after"},
                ],
            }
        )
    _write_json(
        task_dir / "evaluation" / "d4.json",
        {
            "d4_1_artistic_visual_quality": {
                "score": 1.5,
                "criterion_scores": {
                    "composition_and_hierarchy": 2,
                    "palette_and_contrast": 2,
                    "shape_and_style_consistency": 1,
                    "polish": 1,
                    "dynamic_presentation": 2,
                },
                "sampled_images": [{"sequence_id": "sample-1"}],
            },
            "d4_2_feedback_fidelity": {"transitions": transitions},
            "d4_3_goal_interaction_inferability": {
                "questions": [{"id": "question-1", "predicted_choice": "A"}]
            },
        },
    )
    _write_json(
        task_dir / "evaluation" / "d4_question_pack.json",
        {
            "status": "completed",
            "questions": [
                {
                    "id": "question-1",
                    "evidence_id": "evidence-1",
                    "question": "Which option is the next legal action?",
                    "options": {"A": "Move left", "B": "Quit"},
                    "correct_choice": "A",
                    "answer_rationale": "The active scene supports A.",
                    "source_checkpoint_id": d42_anchor_ids[0],
                },
                {
                    "id": "question-2",
                    "evidence_id": "evidence-2",
                    "question": "Unused second question",
                    "options": {"A": "A", "B": "B"},
                    "correct_choice": "A",
                    "answer_rationale": "Unused by the fixed ten-item design.",
                    "source_checkpoint_id": d42_anchor_ids[1],
                },
            ],
            "evidence": [
                {"evidence_id": "evidence-1", "path": str(question_image)},
                {"evidence_id": "evidence-2", "path": str(question_image)},
            ],
        },
    )
    _write_json(
        task_dir / "evaluation" / "d4_sample_manifest.json",
        {"d4_contract_path": str(round_dir / "contracts" / "snake.json")},
    )
    _write_json(
        task_dir / "summary.json",
        {"task": {"game": "snake", "candidate_project_sha256": candidate_sha}},
    )

    manifest = build_human_evidence(task_dir)
    source_items = [
        json.loads(line)
        for line in (task_dir / SOURCE_RELATIVE / "items.private.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    functionality_items = [
        item for item in source_items if item["construct"] == "functional_behavior"
    ]
    dynamic_items = [
        item for item in source_items if item["construct"] == "dynamic_visual_feedback"
    ]

    assert manifest["item_count"] == 10
    assert manifest["counts_by_construct"] == HUMAN_REVIEW_CONSTRUCT_COUNTS
    assert all(item["rateability"] == "rateable" for item in source_items)
    assert [item["_private"]["checkpoint_id"] for item in functionality_items] == list(d2_anchor_ids)
    assert [item["_private"]["checkpoint_id"] for item in dynamic_items] == list(d42_anchor_ids)
    assert len(
        [item for item in source_items if item["construct"] == "visual_question_validity"]
    ) == 1
    assert len(
        [item for item in source_items if item["construct"] == "visual_question_answer"]
    ) == 1
