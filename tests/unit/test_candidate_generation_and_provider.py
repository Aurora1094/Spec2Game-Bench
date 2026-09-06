from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import code2play.providers.dashscope as dashscope
from code2play.config.project import ModelConfig, game_by_slug, load_config
from code2play.generation.staged import generate_candidate_project
from code2play.providers.dashscope import (
    DashScopeChatJudge,
    GenerationNeedsRegeneration,
    GenerationResult,
    JudgeAttemptsExhausted,
    JudgeRouter,
    OpenRouterChatJudge,
    _model_aliases,
    _restore_aliases,
    generate_stage_source,
    generation_output_issues,
)


STATE = """class GameState:
    def __init__(self, seed=0):
        self.seed = seed

def create_initial_state(seed=0):
    return GameState(seed)

def state_to_dict(state):
    return {"seed": state.seed}
"""
GAME = """from .state import GameState

class GameEngine:
    def __init__(self, seed=0):
        self._state = GameState(seed)

    def reset(self):
        self._state = GameState(0)

    def action(self, action):
        return action

    def snapshot(self):
        return {"seed": self._state.seed}

    @property
    def state(self):
        return self._state
"""
RENDERING = """from .state import GameState

class GameRenderer:
    def __init__(self, state=None):
        self.state = state

    def render(self, state=None):
        return state or self.state

    def close(self):
        return None
"""
MAIN = """from .game import GameEngine
from .rendering import GameRenderer
from .state import GameState

class GameBenchAdapter:
    def __init__(self, seed=0):
        self.engine = GameEngine(seed)
        self.renderer = GameRenderer(self.engine.state)

    def init(self):
        return self.engine.snapshot()

    def action(self, action):
        return self.engine.action(action)

    def snapshot(self):
        return self.engine.snapshot()

    def render(self):
        return self.renderer.render(self.engine.state)

    def close(self):
        return self.renderer.close()

def create_gamebench_adapter(seed=0):
    return GameBenchAdapter(seed)

def main():
    return create_gamebench_adapter()
"""


def _generation_result(
    source: str,
    *,
    finish_reason: str = "stop",
    text: str | None = None,
    request_id: str = "fake-generation",
) -> GenerationResult:
    output = text if text is not None else f"```python\n{source}\n```"
    return GenerationResult(
        provider="alibaba_dashscope",
        requested_model="qwen3.7-plus",
        response_model="qwen3.7-plus",
        text=output,
        code=source,
        usage={"prompt_tokens": 1, "completion_tokens": 1},
        request_id=request_id,
        attempts=1,
        request_parameters={},
        raw_response={"finish_reason": finish_reason},
        finish_reason=finish_reason,
        truncated=finish_reason in {"length", "max_tokens", "max_output_tokens", "incomplete"},
    )


def _generation_model() -> ModelConfig:
    return ModelConfig(
        id="qwen3_7_plus",
        name="Qwen3.7 Plus",
        provider="alibaba_dashscope",
        model="qwen3.7-plus",
        api_style="chat_completions",
    )


def test_staged_generation_preserves_four_call_order_and_budgets(tmp_path: Path) -> None:
    config = load_config()
    game = game_by_slug(config, "snake")
    model = _generation_model()
    sources = [STATE, GAME, RENDERING, MAIN]
    calls: list[tuple[int, int]] = []

    def fake_generate(_model, _prompt, *, max_output_tokens, attempts, **_kwargs):
        index = len(calls)
        calls.append((index, max_output_tokens))
        source = sources[index]
        return GenerationResult(
            provider="alibaba_dashscope",
            requested_model="qwen3.7-plus",
            response_model="qwen3.7-plus",
            text=f"```python\n{source}\n```",
            code=source,
            usage={"prompt_tokens": 1, "completion_tokens": 1},
            request_id=f"fake-{index}",
            attempts=attempts,
            request_parameters={},
            raw_response={},
            finish_reason="stop",
            truncated=False,
        )

    project = generate_candidate_project(
        game=game,
        model=model,
        task_dir=tmp_path / "task",
        config=config,
        resume=False,
        generate=fake_generate,
        progress=lambda _message: None,
    )
    assert calls == [(0, 3000), (1, 7000), (2, 4000), (3, 2000)]
    assert project.validate().valid
    assert project.project_sha256()


def test_generation_retries_one_truncated_response_then_accepts_complete_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    sleeps: list[float] = []
    responses = iter(
        [
            _generation_result(
                "class GameState:",
                finish_reason="length",
                text="```python\nclass GameState:",
                request_id="truncated",
            ),
            _generation_result(STATE, request_id="complete"),
        ]
    )

    def fake_generate_once(*_args, **_kwargs):
        calls.append(1)
        return next(responses)

    monkeypatch.setattr(dashscope, "_generate_once", fake_generate_once)
    monkeypatch.setattr(dashscope.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = generate_stage_source(
        _generation_model(),
        "generate state.py",
        stage="state",
        max_output_tokens=3000,
    )

    assert len(calls) == 2
    assert sleeps == [2.0]
    assert result.code == STATE
    assert result.attempts == 2
    assert [item["finish_reason"] for item in result.attempt_history] == [
        "length",
        "stop",
    ]


def test_two_incomplete_generation_outputs_do_not_create_candidate_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config()
    game = game_by_slug(config, "snake")
    calls: list[int] = []
    sleeps: list[float] = []

    def fake_generate_once(*_args, **_kwargs):
        calls.append(1)
        return _generation_result(
            "def incomplete(",
            text="```python\ndef incomplete(",
            request_id=f"incomplete-{len(calls)}",
        )

    monkeypatch.setattr(dashscope, "_generate_once", fake_generate_once)
    monkeypatch.setattr(dashscope.time, "sleep", lambda seconds: sleeps.append(seconds))

    task_dir = tmp_path / "task"
    with pytest.raises(GenerationNeedsRegeneration) as raised:
        generate_candidate_project(
            game=game,
            model=_generation_model(),
            task_dir=task_dir,
            config=config,
            resume=False,
            progress=lambda _message: None,
        )

    assert len(calls) == 2
    assert sleeps == [2.0]
    assert not (task_dir / "candidate" / "state.py").exists()
    assert json.loads((task_dir / "generation_summary.json").read_text(encoding="utf-8"))["status"] == "needs_regeneration"
    failure = json.loads((task_dir / "generation_failure.json").read_text(encoding="utf-8"))
    assert failure["failure"]["stage"] == "state"
    assert len(list((task_dir / "generation" / "stages" / "01_state" / "attempts").rglob("raw_output.txt"))) == 2
    assert raised.value.to_dict()["attempts_made"] == 2


def test_non_eof_syntax_defect_remains_a_candidate_diagnostic() -> None:
    result = _generation_result("def broken(:\n    pass")
    assert generation_output_issues(result, stage="state") == []


def test_eof_style_indentation_defect_requires_regeneration() -> None:
    result = _generation_result("class Incomplete:")
    assert generation_output_issues(result, stage="state") == [
        "eof_syntax_error:expected an indented block after class definition on line 1"
    ]


def test_generation_resume_only_reopens_the_failed_stage(tmp_path: Path) -> None:
    config = load_config()
    game = game_by_slug(config, "snake")
    calls: list[str] = []
    sources = {"state": STATE, "game": GAME, "rendering": RENDERING, "main": MAIN}
    fail_game_once = True

    def fake_generate(_model, _prompt, *, stage, **_kwargs):
        nonlocal fail_game_once
        calls.append(stage)
        if stage == "game" and fail_game_once:
            fail_game_once = False
            raise GenerationNeedsRegeneration(
                stage="game",
                attempts=2,
                attempt_history=[
                    {"attempt": 1, "reasons": ["truncated_finish_reason:length"]},
                    {"attempt": 2, "reasons": ["unclosed_code_fence"]},
                ],
                error=ValueError("incomplete output"),
            )
        return _generation_result(sources[stage], request_id=f"{stage}-{len(calls)}")

    task_dir = tmp_path / "task"
    with pytest.raises(GenerationNeedsRegeneration):
        generate_candidate_project(
            game=game,
            model=_generation_model(),
            task_dir=task_dir,
            config=config,
            resume=False,
            generate=fake_generate,
            progress=lambda _message: None,
        )
    assert calls == ["state", "game"]
    assert (task_dir / "candidate" / "state.py").is_file()
    assert not (task_dir / "candidate" / "game.py").exists()

    with pytest.raises(GenerationNeedsRegeneration):
        generate_candidate_project(
            game=game,
            model=_generation_model(),
            task_dir=task_dir,
            config=config,
            resume=True,
            resume_generation=False,
            generate=fake_generate,
            progress=lambda _message: None,
        )
    assert calls == ["state", "game"]

    project = generate_candidate_project(
        game=game,
        model=_generation_model(),
        task_dir=task_dir,
        config=config,
        resume=True,
        resume_generation=True,
        generate=fake_generate,
        progress=lambda _message: None,
    )
    assert calls == ["state", "game", "game", "rendering", "main"]
    assert project.validate().valid


class _FakeCompletions:
    def create(self, **_kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))],
            usage={"prompt_tokens": 2, "completion_tokens": 3},
        )


class _FakeClient:
    chat = SimpleNamespace(completions=_FakeCompletions())


def test_provider_is_qwen_only_and_uses_fake_openai_compatible_client(tmp_path: Path) -> None:
    judge = DashScopeChatJudge(
        tmp_path,
        model="qwen3.7-plus",
        role="smoke",
        max_output_tokens=64,
        client=_FakeClient(),
    )
    assert judge.json_text("Return JSON.", "{}", "smoke") == {"ok": True}
    calls = list(tmp_path.rglob("raw_input.json"))
    assert len(calls) == 1
    call_dir = calls[0].parent
    assert (call_dir / "parsed_output.json").is_file()
    result = json.loads((call_dir / "request_result.json").read_text(encoding="utf-8"))
    assert result["status"] == "completed"
    assert result["attempts_made"] == 1


def test_provider_restores_blinded_checkpoint_and_dimension_ids() -> None:
    aliases = _model_aliases(
        "snake.D2.1.01 snake.D2.2.01 D2.1 D2.2",
    )
    value = {
        "checkpoint_id": "criterion_1_01",
        "dimension": "interaction modeling",
        "source_checkpoint_ids": [r"criterion\_2\_01"],
        "rationale": "interaction modeling",
        "penalties": {
            "game element modeling": 0,
            "interaction modeling": 1,
        },
        "rationale_by_dimension": {
            "interaction modeling": "The explanatory text remains unchanged.",
        },
    }

    restored = _restore_aliases(value, aliases)

    assert restored["checkpoint_id"] == "snake.D2.1.01"
    assert restored["dimension"] == "D2.2"
    assert restored["source_checkpoint_ids"] == ["snake.D2.2.01"]
    assert restored["rationale"] == "interaction modeling"
    assert restored["penalties"] == {"D2.1": 0, "D2.2": 1}
    assert restored["rationale_by_dimension"] == {
        "D2.2": "The explanatory text remains unchanged.",
    }


class _InvalidCompletions:
    def __init__(self) -> None:
        self.calls = 0
        self.messages: list[list[dict[str, object]]] = []

    def create(self, **kwargs):
        self.calls += 1
        self.messages.append(kwargs["messages"])
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="{"))],
            usage={"prompt_tokens": 2, "completion_tokens": 3},
        )


class _InvalidClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=_InvalidCompletions())


def test_provider_stops_after_two_invalid_json_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _InvalidClient()
    sleeps: list[float] = []
    monkeypatch.setattr(dashscope.time, "sleep", lambda seconds: sleeps.append(seconds))
    judge = DashScopeChatJudge(
        tmp_path,
        model="qwen3.7-plus",
        role="smoke",
        max_output_tokens=64,
        client=client,
    )

    with pytest.raises(JudgeAttemptsExhausted) as raised:
        judge.json_text_validated(
            "Return JSON.",
            "{}",
            "invalid_json_test",
            validator=lambda value: value,
        )

    assert client.chat.completions.calls == 2
    assert sleeps == [2.0]
    assert raised.value.to_dict()["attempts_made"] == 2
    correction = client.chat.completions.messages[1][-1]["content"]
    assert "complete minified JSON object" in str(correction)
    assert "JSONDecodeError" in str(correction)
    result_paths = list(tmp_path.rglob("request_result.json"))
    assert len(result_paths) == 1
    result = json.loads(result_paths[0].read_text(encoding="utf-8"))
    assert result["status"] == "attempts_exhausted"
    assert result["attempts_made"] == 2


def test_judge_router_keeps_two_roles_on_qwen_then_switches_only_vision(tmp_path: Path) -> None:
    config = load_config()
    calls: list[dict[str, object]] = []

    def factory(_log_dir: Path, **kwargs: object) -> object:
        calls.append(kwargs)
        return object()

    router = JudgeRouter(config["judge"], tmp_path / "qwen", client_factory=factory)
    router.for_role("functionality")
    router.for_role("dynamic_visual")
    assert [(call["provider"], call["model"]) for call in calls] == [
        ("alibaba_dashscope", "qwen3.7-plus"),
        ("alibaba_dashscope", "qwen3.7-plus"),
    ]
    assert all(call["response_format"] == {"type": "json_object"} for call in calls)

    mixed_judge = deepcopy(config["judge"])
    mixed_judge["routing"]["roles"]["vision"] = "gemini_openrouter"
    mixed_calls: list[dict[str, object]] = []

    def mixed_factory(_log_dir: Path, **kwargs: object) -> object:
        mixed_calls.append(kwargs)
        return object()

    mixed_router = JudgeRouter(mixed_judge, tmp_path / "mixed", client_factory=mixed_factory)
    mixed_router.for_role("functionality")
    mixed_router.for_role("dynamic_visual")
    assert [(call["provider"], call["model"]) for call in mixed_calls] == [
        ("alibaba_dashscope", "qwen3.7-plus"),
        ("openrouter", "google/gemini-3.8-flash"),
    ]
    assert all(call["response_format"] == {"type": "json_object"} for call in mixed_calls)


def test_openrouter_judge_uses_openai_compatible_request_without_dashscope_body(tmp_path: Path) -> None:
    requests: list[dict[str, object]] = []

    class Completions:
        def create(self, **kwargs: object) -> SimpleNamespace:
            requests.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))],
                usage={"prompt_tokens": 2, "completion_tokens": 3},
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    judge = OpenRouterChatJudge(
        tmp_path,
        model="google/gemini-3.8-flash",
        role="dynamic_visual",
        max_output_tokens=64,
        response_format={"type": "json_object"},
        client=client,
    )
    assert judge.json_text("Return JSON.", "{}", "dynamic_visual") == {"ok": True}
    assert requests[0]["model"] == "google/gemini-3.8-flash"
    assert "extra_body" not in requests[0]
    assert requests[0]["response_format"] == {"type": "json_object"}


def test_dashscope_judge_uses_json_mode_with_thinking_disabled(tmp_path: Path) -> None:
    requests: list[dict[str, object]] = []

    class Completions:
        def create(self, **kwargs: object) -> SimpleNamespace:
            requests.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))],
                usage={"prompt_tokens": 2, "completion_tokens": 3},
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    judge = DashScopeChatJudge(
        tmp_path,
        model="qwen3.7-plus",
        role="functionality",
        max_output_tokens=64,
        response_format={"type": "json_object"},
        client=client,
    )

    assert judge.json_text("Return JSON.", "{}", "d2_dimension_D2.1_batch_01") == {"ok": True}
    assert requests[0]["response_format"] == {"type": "json_object"}
    assert requests[0]["extra_body"] == {"enable_thinking": False}


def test_parallel_judge_calls_write_isolated_request_artifacts(tmp_path: Path) -> None:
    class Completions:
        def create(self, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok": true}'))],
                usage={"prompt_tokens": 2, "completion_tokens": 3},
            )

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    judge = DashScopeChatJudge(
        tmp_path,
        model="qwen3.7-plus",
        role="functionality",
        max_output_tokens=64,
        response_format={"type": "json_object"},
        client=client,
    )
    purposes = [f"d2_dimension_D2.1_batch_{index:02d}" for index in range(1, 9)]

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda purpose: judge.json_text("Return JSON.", "{}", purpose), purposes))

    inputs = sorted(tmp_path.rglob("raw_input.json"))
    assert len(inputs) == len(purposes)
    assert {json.loads(path.read_text(encoding="utf-8"))["purpose"] for path in inputs} == set(purposes)
    for input_path in inputs:
        call_dir = input_path.parent
        assert (call_dir / "raw_output_attempt_001.txt").is_file()
        assert (call_dir / "raw_response_attempt_001.json").is_file()
        assert (call_dir / "parsed_output.json").is_file()
        assert json.loads((call_dir / "request_result.json").read_text(encoding="utf-8"))["status"] == "completed"
