from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from code2play.cli import _mock_contract_generator
from code2play.config.project import game_by_slug, load_config
from code2play.d4.contracts import build_round_contracts
from code2play.execution.candidate_project import CandidateProject


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAIN = PROJECT_ROOT / "main.py"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _make_candidate(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "__init__.py").write_text(
        '"""Benchmark-managed candidate package."""\n', encoding="utf-8"
    )
    (path / "state.py").write_text(
        "class GameState:\n"
        "    pass\n\n"
        "def create_initial_state(seed=0):\n"
        "    return GameState()\n\n"
        "def state_to_dict(state):\n"
        "    return {}\n",
        encoding="utf-8",
    )
    (path / "game.py").write_text(
        "from .state import GameState\n\n"
        "class GameEngine:\n"
        "    def __init__(self, seed=0):\n"
        "        self._state = GameState()\n\n"
        "    def reset(self):\n"
        "        return None\n\n"
        "    def action(self, action):\n"
        "        return action\n\n"
        "    def snapshot(self):\n"
        "        return {}\n\n"
        "    @property\n"
        "    def state(self):\n"
        "        return self._state\n",
        encoding="utf-8",
    )
    (path / "rendering.py").write_text(
        "class GameRenderer:\n"
        "    def render(self, state=None):\n"
        "        return None\n\n"
        "    def close(self):\n"
        "        return None\n",
        encoding="utf-8",
    )
    (path / "main.py").write_text(
        "class GameBenchAdapter:\n"
        "    def __init__(self, seed=0):\n"
        "        self.seed = seed\n\n"
        "    def init(self):\n"
        "        return {}\n\n"
        "    def action(self, action):\n"
        "        return action\n\n"
        "    def snapshot(self):\n"
        "        return {}\n\n"
        "    def render(self):\n"
        "        return None\n\n"
        "    def close(self):\n"
        "        return None\n\n"
        "def create_gamebench_adapter(seed=0):\n"
        "    return GameBenchAdapter(seed)\n\n"
        "def main():\n"
        "    return create_gamebench_adapter()\n",
        encoding="utf-8",
    )


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(MAIN), *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_human_export_cli_covers_blind_boundary_assets_and_blank_template(
    tmp_path: Path,
) -> None:
    config = load_config()
    game = game_by_slug(config, "snake")
    round_dir = tmp_path / "external round" / "round-001"
    round_manifest = build_round_contracts(
        round_dir,
        [game],
        config=config,
        generator=_mock_contract_generator(config),
        round_id="round-001",
    )

    task_dir = tmp_path / "task with spaces"
    candidate_dir = task_dir / "candidate"
    _make_candidate(candidate_dir)
    candidate_sha = CandidateProject(candidate_dir).project_sha256()
    trace_path = task_dir / "evaluation" / "trace.json"
    _write_json(trace_path, {"status": "completed", "cases": []})
    checkpoint_id = "snake.D2.1.01"
    _write_json(
        task_dir / "evaluation" / "d2.json",
        {
            "evidence": {
                "checkpoint_results": [
                    {
                        "id": checkpoint_id,
                        "earned": 2,
                        "possible": 2,
                        "trace_path": str(trace_path),
                    }
                ]
            }
        },
    )
    _write_json(
        task_dir / "evaluation" / "d3.json",
        {
            "result": {
                "semantic_judge": {
                    "criterion_scores": {
                        key: 80
                        for key in (
                            "maintainability",
                            "reliability",
                            "security",
                            "efficiency",
                            "conformance",
                        )
                    }
                }
            }
        },
    )
    _write_json(task_dir / "evaluation" / "d4.json", {})
    _write_json(
        task_dir / "evaluation" / "d4_question_pack.json",
        {"status": "candidate_evidence_unavailable", "questions": [], "evidence": []},
    )
    _write_json(
        task_dir / "evaluation" / "d4_sample_manifest.json",
        {
            "d4_contract_path": str(round_dir / "contracts" / "snake.json"),
            "d4_contract_manifest_sha256": round_manifest["manifest_sha256"],
        },
    )
    _write_json(
        task_dir / "summary.json",
        {
            "task": {
                "game": "snake",
                "model": "secret-candidate-model",
                "repetition": 1,
                "candidate_project_sha256": candidate_sha,
            }
        },
    )

    output_dir = tmp_path / "questionnaire output"
    exported = _run(
        "human",
        "export",
        "--task-dir",
        str(task_dir),
        "--output-dir",
        str(output_dir),
        "--blind-id",
        "candidate-001",
    )
    assert exported.returncode == 0, exported.stderr
    export_payload = json.loads(exported.stdout)
    public = Path(export_payload["public_bundle"])
    private = Path(export_payload["private_mapping"])
    assert export_payload["validation"]["status"] == "passed"
    assert public.is_dir()
    assert private.is_file()

    manifest = json.loads((public / "manifest.json").read_text(encoding="utf-8"))
    items = [
        json.loads(line)
        for line in (public / "items.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    responses = [
        json.loads(line)
        for line in (public / "response_template.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assets = json.loads((public / "asset_index.json").read_text(encoding="utf-8"))
    assert items
    assert manifest["item_count"] == len(items) == len(responses)
    assert len(assets["assets"]) > 0
    assert [item["human_item_id"] for item in items] == [
        item["human_item_id"] for item in responses
    ]
    assert all(item["rating"] is None and item["confidence"] is None for item in responses)
    public_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            public / "manifest.json",
            public / "asset_index.json",
            public / "items.jsonl",
            public / "response_template.jsonl",
        )
    )
    private_text = private.read_text(encoding="utf-8")
    for private_value in (
        "secret-candidate-model",
        checkpoint_id,
        candidate_sha,
        str(task_dir),
    ):
        assert private_value not in public_text
    for forbidden_key in ("automatic_score", "answer_key"):
        assert f'"{forbidden_key}"' not in public_text
    assert "secret-candidate-model" in private_text
    for asset in assets["assets"]:
        asset_path = public / asset["path"]
        assert asset_path.is_file()
        assert hashlib.sha256(asset_path.read_bytes()).hexdigest() == asset["sha256"]

    validated = _run("human", "validate", "--bundle-dir", str(public))
    assert validated.returncode == 0, validated.stderr
    assert json.loads(validated.stdout)["status"] == "passed"

    responses[0]["rating"] = 2
    _write_jsonl(public / "response_template.jsonl", responses)
    tampered = _run("human", "validate", "--bundle-dir", str(public))
    assert tampered.returncode == 1
    assert json.loads(tampered.stdout)["status"] == "failed"
