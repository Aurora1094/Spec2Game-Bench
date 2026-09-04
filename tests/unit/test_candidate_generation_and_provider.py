from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import code2play.providers.dashscope as dashscope
from code2play.config.project import ModelConfig, game_by_slug, load_config
from code2play.generation.staged import generate_candidate_project
from code2play.providers.dashscope import (
    DashScopeChatJudge,
    GenerationResult,
    JudgeAttemptsExhausted,
    _model_aliases,
    _restore_aliases,
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


def test_staged_generation_preserves_four_call_order_and_budgets(tmp_path: Path) -> None:
    config = load_config()
    game = game_by_slug(config, "snake")
    model = ModelConfig(
        id="qwen3_7_plus",
        name="Qwen3.7 Plus",
        provider="alibaba_dashscope",
        model="qwen3.7-plus",
        api_style="chat_completions",
    )
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
    assert (tmp_path / "raw_input.json").is_file()


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
