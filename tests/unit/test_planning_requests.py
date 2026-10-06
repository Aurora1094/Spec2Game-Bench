from __future__ import annotations

import json
from pathlib import Path

from spec2game.planning.requests import _compiler_usage


def test_compiler_usage_accumulates_all_attempt_usage_from_request_result(
    tmp_path: Path,
) -> None:
    call_dir = tmp_path / "action_compiler" / "request-001"
    call_dir.mkdir(parents=True)
    (call_dir / "raw_input.json").write_text(
        json.dumps(
            {
                "purpose": "d2_compile_batch_D2.1_01",
                "provider": "alibaba_dashscope",
                "model": "qwen3.7-plus",
                "enable_thinking": False,
                "max_output_tokens": 6000,
            }
        ),
        encoding="utf-8",
    )
    (call_dir / "request_result.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "attempts_made": 2,
                "attempts": [
                    {
                        "attempt": 1,
                        "usage": {"prompt_tokens": 11, "completion_tokens": 3},
                        "finish_reason": "stop",
                    },
                    {
                        "attempt": 2,
                        "usage": {"prompt_tokens": 13, "completion_tokens": 5},
                        "finish_reason": "stop",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    requests, totals = _compiler_usage(tmp_path / "action_compiler")

    assert len(requests) == 1
    assert requests[0]["usage"] == {
        "input_tokens": 24,
        "output_tokens": 8,
        "reasoning_tokens": 0,
        "cached_tokens": 0,
        "attempts": 2,
    }
    assert totals == {
        "input_tokens": 24,
        "output_tokens": 8,
        "reasoning_tokens": 0,
        "cached_tokens": 0,
        "attempts": 2,
    }


def test_compiler_usage_reads_legacy_flat_logs(tmp_path: Path) -> None:
    call_dir = tmp_path / "action_compiler" / "legacy"
    call_dir.mkdir(parents=True)
    (call_dir / "raw_input.json").write_text(
        json.dumps(
            {
                "purpose": "d2_compile_snake.D2.1.01",
                "request_attempts": 1,
                "attempt_usages": [{"prompt_tokens": 7, "completion_tokens": 2}],
            }
        ),
        encoding="utf-8",
    )

    requests, totals = _compiler_usage(tmp_path / "action_compiler")

    assert requests[0]["usage"]["input_tokens"] == 7
    assert requests[0]["usage"]["output_tokens"] == 2
    assert totals["attempts"] == 1
