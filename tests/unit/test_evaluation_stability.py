from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re

import pytest

from spec2game.evaluation.dimensions.d2.protocol_evaluator import (
    D2_BATCH_MAX_CHECKPOINTS,
    D2_BATCH_TARGET_PROMPT_CHARS,
    MAX_CHECKPOINT_JUDGE_PROMPT_CHARS,
    _compact_trace_for_judge,
    _judge_dimension_batch,
    _partition_dimension_batches,
)
from spec2game.evaluation.pipeline import _run_stage
from spec2game.execution import candidate_project as candidate_project_module
from spec2game.execution.candidate_project import (
    BENCHMARK_INIT_SOURCE,
    CandidateProject,
    PROJECT_FILES,
)
from spec2game.execution.protocol_sampling import (
    _ordered_d4_2_records,
    _protocol_failure_phase,
)


def _checkpoint(index: int) -> dict[str, object]:
    checkpoint_id = f"snake.D2.1.{index:02d}"
    return {
        "id": checkpoint_id,
        "dimension": "D2.1",
        "kind": "static",
        "item": f"item {index}",
        "objective": "The required behavior is observable.",
        "initial_state": "A valid initial game state.",
        "trigger": "No action is required.",
        "expected_transition": "The state remains observable.",
        "detection_method": "state trace",
        "score_rubric": "0 missing; 1 partial; 2 complete",
        "source_jsonl": "D2.1.jsonl",
        "source_row": index,
    }


def _trace(checkpoint_id: str, *, state_chars: int = 0) -> dict[str, object]:
    return {
        "id": checkpoint_id,
        "status": "completed",
        "compiled_program": {"cases": []},
        "frames": [{"pixels": "frame-data" * 100}],
        "visual_status": "completed",
        "cases": [
            {
                "visual_probe": {"status": "completed", "frames": ["hidden"]},
                "observations": [
                    {
                        "action_state": {"state": "x" * state_chars},
                        "snapshot": {"state": "x" * state_chars},
                    }
                ],
            }
        ],
    }


class _DimensionJudge:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def json_text_validated(self, _instructions, prompt, *, purpose, validator):
        assert purpose.startswith("d2_dimension_D2.1_batch_")
        self.prompts.append(prompt)
        ids = list(dict.fromkeys(re.findall(r"snake\.D2\.1\.\d+", prompt)))
        return validator(
            {
                "dimension": "D2.1",
                "results": [
                    {
                        "checkpoint_id": checkpoint_id,
                        "score": 2,
                        "evidence": ["trace"],
                        "limitations": [],
                        "rationale": "complete",
                    }
                    for checkpoint_id in ids
                ],
            }
        )


def test_d2_batches_compact_visual_data_and_preserve_checkpoint_order() -> None:
    checkpoints = [_checkpoint(index) for index in range(1, 10)]
    traces = {
        str(checkpoint["id"]): _trace(str(checkpoint["id"]), state_chars=110_000)
        for checkpoint in checkpoints
    }
    compact = _compact_trace_for_judge(next(iter(traces.values())))
    compact_text = json.dumps(compact, ensure_ascii=False)
    assert "frames" not in compact_text
    assert "visual_probe" not in compact_text
    assert "visual_status" not in compact_text

    judge = _DimensionJudge()
    results, report = _judge_dimension_batch(
        "D2.1",
        checkpoints,
        traces,
        source="",
        game_description="A game.",
        judge=judge,
    )

    assert list(results) == [
        checkpoint["id"] for checkpoint in checkpoints
    ]
    assert report["batch_strategy"] == "greedy_character_budget_v2"
    assert [checkpoint_id for batch in report["batches"] for checkpoint_id in batch["checkpoint_ids"]] == [
        checkpoint["id"] for checkpoint in checkpoints
    ]
    assert all(batch["checkpoint_count"] <= D2_BATCH_MAX_CHECKPOINTS for batch in report["batches"])
    assert all(
        batch["prompt_characters"] <= D2_BATCH_TARGET_PROMPT_CHARS
        for batch in report["batches"]
    )
    assert len(judge.prompts) == report["batch_count"]


def test_d2_single_checkpoint_hard_limit_excludes_d4_metadata() -> None:
    checkpoint = _checkpoint(1)
    trace = _trace(str(checkpoint["id"]))
    trace["frames"] = [{"pixels": "x" * (MAX_CHECKPOINT_JUDGE_PROMPT_CHARS + 1)}]
    batches = _partition_dimension_batches(
        "D2.1",
        [checkpoint],
        {str(checkpoint["id"]): trace},
        source="",
        game_description="A game.",
    )
    assert batches[0][1] < D2_BATCH_TARGET_PROMPT_CHARS

    too_large = _trace(
        str(checkpoint["id"]),
        state_chars=MAX_CHECKPOINT_JUDGE_PROMPT_CHARS + 1,
    )
    with pytest.raises(ValueError, match=r"snake\.D2\.1\.01 remains too large"):
        _partition_dimension_batches(
            "D2.1",
            [checkpoint],
            {str(checkpoint["id"]): too_large},
            source="",
            game_description="A game.",
        )


def _write_candidate(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    sources = {
        "__init__.py": BENCHMARK_INIT_SOURCE,
        "state.py": """class GameState:\n    pass\n\ndef create_initial_state(seed=0):\n    return GameState()\n\ndef state_to_dict(state):\n    return {}\n""",
        "game.py": """from .state import GameState\n\nclass GameEngine:\n    def __init__(self, seed=0): self._state = GameState()\n    def reset(self): pass\n    def action(self, action): return self.snapshot()\n    def snapshot(self): return {}\n    @property\n    def state(self): return self._state\n""",
        "rendering.py": """class GameRenderer:\n    def render(self, state=None): return None\n    def close(self): return None\n""",
        "main.py": """class GameBenchAdapter:\n    def init(self): return {}\n    def action(self, action): return {}\n    def snapshot(self): return {}\n    def render(self): return None\n    def close(self): return None\n\ndef create_gamebench_adapter(seed=0): return GameBenchAdapter()\n\ndef main(): return create_gamebench_adapter()\n""",
    }
    for filename, source in sources.items():
        (path / filename).write_text(source, encoding="utf-8")


def test_candidate_snapshot_parses_once_then_copies_by_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_dir = tmp_path / "candidate"
    _write_candidate(candidate_dir)
    original = candidate_project_module.diagnose_stage_source
    calls: list[str] = []

    def counted(stage: str, source: str) -> dict[str, object]:
        calls.append(stage)
        return original(stage, source)

    monkeypatch.setattr(candidate_project_module, "diagnose_stage_source", counted)
    snapshot = CandidateProject(candidate_dir).validated_snapshot()
    assert sorted(calls) == ["game", "main", "rendering", "state"]

    def copy(index: int) -> Path:
        return snapshot.copy_to_isolated(tmp_path / f"isolated-{index}")

    with ThreadPoolExecutor(max_workers=4) as executor:
        destinations = list(executor.map(copy, range(4)))
    assert sorted(calls) == ["game", "main", "rendering", "state"]
    for destination in destinations:
        assert sorted(path.name for path in destination.iterdir()) == sorted(PROJECT_FILES)
        assert {
            filename: hashlib.sha256((destination / filename).read_bytes()).hexdigest()
            for filename in PROJECT_FILES
        } == snapshot.file_hashes()


def test_d4_records_bind_by_checkpoint_id_and_protocol_failures_have_placeholders() -> None:
    checkpoints = [
        {"id": "snake.D2.1.01", "dimension": "D2.1", "kind": "static"},
        {"id": "snake.D2.2.01", "dimension": "D2.2", "kind": "dynamic"},
        {"id": "snake.D2.3.01", "dimension": "D2.3", "kind": "dynamic"},
    ]
    records = [
        {"id": "snake.D2.3.01", "status": "completed", "frames": []},
        {"id": "snake.D2.1.01", "status": "completed", "frames": []},
        {"id": "snake.D2.2.01", "status": "completed", "frames": []},
    ]
    assert [item["id"] for item in _ordered_d4_2_records(checkpoints, records)] == [
        "snake.D2.2.01",
        "snake.D2.3.01",
    ]
    with pytest.raises(ValueError, match="duplicate checkpoint id"):
        _ordered_d4_2_records(checkpoints, [*records, dict(records[0])])
    with pytest.raises(ValueError, match="unknown checkpoint id"):
        _ordered_d4_2_records(
            checkpoints,
            [{"id": "other.D2.1.01", "status": "completed", "frames": []}],
        )
    with pytest.raises(ValueError, match="missing checkpoint record"):
        _ordered_d4_2_records(checkpoints, records[:2])

    phase = _protocol_failure_phase(
        checkpoints,
        {"seed": 17},
        {"type": "SyntaxError", "message": "candidate rendering is invalid"},
    )
    assert [item["id"] for item in phase["d4_records"]["d4_2"]] == [
        "snake.D2.2.01",
        "snake.D2.3.01",
    ]
    assert all(
        item["status"] == "not_run_adapter_contract"
        for item in phase["d4_records"]["d4_2"]
    )


def test_rescore_reuses_completed_stages_and_runs_only_the_gap(tmp_path: Path) -> None:
    state_path = tmp_path / "stage_state.json"
    state = {
        "status": "needs_rescore",
        "active_stage": None,
        "stages": {
            "D1": {"status": "completed"},
            "D3": {"status": "completed"},
            "sampling": {"status": "needs_rescore", "attempts": 1},
        },
    }
    (tmp_path / "d1.json").write_text('{"status":"completed"}', encoding="utf-8")
    (tmp_path / "d3.json").write_text('{"status":"completed"}', encoding="utf-8")
    calls: list[str] = []

    assert _run_stage(
        name="D1",
        state=state,
        state_path=state_path,
        output_path=tmp_path / "d1.json",
        operation=lambda _attempt: calls.append("D1") or {"status": "completed"},
    ) == {"status": "completed"}
    assert _run_stage(
        name="D3",
        state=state,
        state_path=state_path,
        output_path=tmp_path / "d3.json",
        operation=lambda _attempt: calls.append("D3") or {"status": "completed"},
    ) == {"status": "completed"}
    assert _run_stage(
        name="sampling",
        state=state,
        state_path=state_path,
        output_path=tmp_path / "sample_manifest.json",
        operation=lambda _attempt: calls.append("sampling") or {"status": "completed"},
    ) == {"status": "completed"}
    assert calls == ["sampling"]
    assert state["stages"]["sampling"]["attempts"] == 2


def test_rescore_stage_state_retains_judge_failure_metadata(tmp_path: Path) -> None:
    state = {"status": "running", "active_stage": None, "stages": {}}
    judge_failure = {
        "failure_stage": "D2",
        "attempt_limit": 2,
        "attempts_made": 2,
    }
    _run_stage(
        name="D2",
        state=state,
        state_path=tmp_path / "stage_state.json",
        output_path=tmp_path / "d2.json",
        operation=lambda _attempt: {
            "status": "judge_output_unavailable",
            "judge_failure": judge_failure,
        },
    )
    assert state["stages"]["D2"]["status"] == "needs_rescore"
    assert state["stages"]["D2"]["judge_failure"] == judge_failure


def test_incomplete_judge_stage_is_rerun_instead_of_skipped(tmp_path: Path) -> None:
    state_path = tmp_path / "stage_state.json"
    state = {
        "status": "needs_rescore",
        "active_stage": None,
        "stages": {"D3": {"status": "completed"}},
    }
    (tmp_path / "d3.json").write_text(
        '{"status":"incomplete_judge","result":{"status":"incomplete_judge"}}',
        encoding="utf-8",
    )
    calls: list[str] = []

    payload = _run_stage(
        name="D3",
        state=state,
        state_path=state_path,
        output_path=tmp_path / "d3.json",
        operation=lambda _attempt: calls.append("D3")
        or {"status": "incomplete_judge", "result": {"status": "incomplete_judge"}},
    )

    assert calls == ["D3"]
    assert payload["status"] == "incomplete_judge"
    assert state["stages"]["D3"]["status"] == "needs_rescore"
