from __future__ import annotations

import json
from pathlib import Path

from code2play.cli import _mock_contract_generator
from code2play.config.project import game_by_slug, load_config
from code2play.d4.contracts import build_round_contracts
from code2play.execution.candidate_project import CandidateProject
from code2play.human_review.artifacts import export_blind_bundle, validate_blind_bundle


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
    checkpoint_id = "snake.D2.1.01"
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
