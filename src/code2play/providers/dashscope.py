"""OpenAI-compatible providers used by model-facing operations.

The provider deliberately keeps the evaluator-facing interface small.  It is
also usable with a fake OpenAI-compatible client in tests, so the default test
suite never needs a paid API call.
"""

from __future__ import annotations

import ast
import base64
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
from threading import Lock
import time
from typing import Any, Callable, Mapping, Protocol, Sequence
from uuid import uuid4


DASHSCOPE_PROVIDER = "alibaba_dashscope"
DASHSCOPE_MODEL = "qwen3.7-plus"
DASHSCOPE_API_STYLE = "chat_completions"
OPENROUTER_PROVIDER = "openrouter"
OPENROUTER_MODEL = "google/gemini-3.8-flash"
OPENROUTER_API_STYLE = "chat_completions"
OPENROUTER_QWEN_MODEL = "qwen/qwen3.7-plus"
OPENROUTER_QWEN_VL_MODEL = "qwen/qwen3-vl-235b-a22b-instruct"
OPENROUTER_KIMI_CODE_MODEL = "moonshotai/kimi-k2.7-code"
OPENROUTER_KIMI_REASONING = {"effort": "minimal", "exclude": True}
OPENROUTER_GPT56_TERRA_MODEL = "openai/gpt-5.6-terra"
OPENROUTER_GPT56_TERRA_REASONING = {"effort": "none"}
# Qwen3.7 Plus enables reasoning by default on OpenRouter.  ``exclude`` only
# hides that output; it does not preserve the completion budget for JSON.
OPENROUTER_QWEN_JUDGE_REASONING = {"effort": "none"}
_LEGACY_OPENROUTER_QWEN_JUDGE_REASONING = {"effort": "minimal", "exclude": True}
OPENROUTER_API_KEY_ENV = "OPENROUTER_API_KEY"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
LINK_OPENAI_PROVIDER = "link_openai"
LINK_OPENAI_MODEL = "gpt-5.6-sol"
LINK_OPENAI_API_STYLE = "chat_completions"
LINK_OPENAI_API_KEY_ENV = "LINK_API_KEY"
LINK_OPENAI_BASE_URL = "https://ai.klinkw.com/v1"
MAX_JUDGE_OUTPUT_TOKENS = 6000
JUDGE_TEMPERATURE = 0.0
PANEL_POLICY = "single_qwen37_plus_stateless"

_SECRET_ENV_NAMES = ("DASHSCOPE_API_KEY", "OPENROUTER_API_KEY", LINK_OPENAI_API_KEY_ENV)
_DIMENSION_NAMES = {
    "D2.1": "game element modeling",
    "D2.2": "interaction modeling",
    "D2.3": "rule and mechanism modeling",
    "D2.4": "dynamic evolution",
    "D2.5": "goal and termination modeling",
    "D1": "executability",
    "D2": "functionality",
    "D3": "code quality",
    "D4": "user experience",
    "D4.1": "artistic visual quality",
    "D4.2": "feedback fidelity",
    "D4.3": "goal and interaction inferability",
}
_DIMENSION_RE = re.compile(
    r"(?<![A-Za-z0-9_])D[1-4](?:[._][1-9][0-9]*)?(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
_CHECKPOINT_RE = re.compile(
    r"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9_]*\.D[1-4](?:\.[0-9]+)+(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


class SemanticJudge(Protocol):
    def json_text(self, instructions: str, prompt: str, purpose: str) -> dict[str, Any]: ...

    def json_vision(
        self,
        instructions: str,
        prompt: str,
        images: Sequence[tuple[Path, str]],
        purpose: str,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ModelRequest:
    request_id: str
    role: str
    modality: str
    instructions: str
    prompt: str
    images: tuple[tuple[Path, str], ...] = ()
    response_schema: dict[str, Any] | None = None
    max_output_tokens: int = MAX_JUDGE_OUTPUT_TOKENS


@dataclass(frozen=True)
class ModelResult:
    parsed_output: dict[str, Any]
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    attempts: int = 1
    raw_usage: dict[str, Any] = field(default_factory=dict)


class JudgeAttemptsExhausted(RuntimeError):
    """A retryable Judge request used both permitted attempts without output."""

    def __init__(self, *, purpose: str, attempts: int, error: BaseException) -> None:
        self.purpose = str(purpose)
        self.attempts = int(attempts)
        self.error_type = type(error).__name__
        self.error_message = _redact(str(error))
        super().__init__(
            f"Judge request {self.purpose!r} exhausted {self.attempts} attempts: "
            f"{self.error_type}: {self.error_message}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "attempt_limit": self.attempts,
            "attempts_made": self.attempts,
            "last_error_type": self.error_type,
            "last_error": self.error_message,
        }


@dataclass
class GenerationResult:
    provider: str
    requested_model: str
    response_model: str
    text: str
    code: str
    usage: dict[str, Any] | None
    request_id: str | None
    attempts: int
    request_parameters: dict[str, Any]
    raw_response: dict[str, Any]
    finish_reason: str | None
    truncated: bool
    attempt_history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class GenerationOutputInvalid(ValueError):
    """One model response was returned but cannot be treated as complete code."""

    def __init__(self, result: GenerationResult, reasons: Sequence[str]) -> None:
        self.result = result
        self.reasons = tuple(str(reason) for reason in reasons if str(reason))
        message = "; ".join(self.reasons) or "generation output failed completeness checks"
        super().__init__(message)


class GenerationNeedsRegeneration(RuntimeError):
    """A generation stage exhausted its fixed attempts on incomplete output."""

    def __init__(
        self,
        *,
        stage: str,
        attempts: int,
        attempt_history: Sequence[Mapping[str, Any]],
        error: BaseException | None = None,
    ) -> None:
        self.stage = str(stage)
        self.attempts = int(attempts)
        self.attempts_made = self.attempts
        self.attempt_history = [dict(item) for item in attempt_history]
        self.error_type = type(error).__name__ if error is not None else "GenerationOutputInvalid"
        self.error_message = _redact(str(error)) if error is not None else "incomplete generation output"
        self.failure_reasons = [
            str(reason)
            for item in self.attempt_history
            for reason in item.get("reasons", [])
            if str(reason)
        ]
        super().__init__(
            f"Generation stage {self.stage!r} exhausted {self.attempts} attempts; "
            f"regeneration required: {self.error_message}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": type(self).__name__,
            "stage": self.stage,
            "attempt_limit": self.attempts,
            "attempts_made": self.attempts_made,
            "attempts": [
                {
                    key: value
                    for key, value in item.items()
                    if key not in {"text", "code", "raw_response", "request_parameters"}
                }
                for item in self.attempt_history
            ],
            "failure_reasons": list(dict.fromkeys(self.failure_reasons)),
            "error_type": self.error_type,
            "error": self.error_message,
        }


def _dump(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    method = getattr(value, "model_dump", None)
    if callable(method):
        try:
            result = method(mode="json")
        except TypeError:
            result = method()
        return result if isinstance(result, dict) else {}
    return {}


def _get(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _redact(value: str, additional: Sequence[str] = ()) -> str:
    result = str(value)
    secrets = [
        secret
        for secret in (*(os.getenv(name, "") for name in _SECRET_ENV_NAMES), *additional)
        if isinstance(secret, str) and len(secret) >= 4
    ]
    for secret in sorted(set(secrets), key=len, reverse=True):
        result = result.replace(secret, "[REDACTED]")
    result = re.sub(
        r"(?i)(authorization\s*[:=]\s*[\"']?)(?:bearer\s+)?[^\s\"',}]+",
        r"\1[REDACTED]",
        result,
    )
    result = re.sub(r"(?i)bearer\s+[^\s\"',}]+", "Bearer [REDACTED]", result)
    return result


def redact_sensitive_text(text: str, additional_secrets: Sequence[str] = ()) -> str:
    return _redact(text, additional_secrets)


def _model_visible_text(text: str) -> str:
    def replace_checkpoint(match: re.Match[str]) -> str:
        parts = match.group(0).split(".")
        return "criterion_" + "_".join(parts[-2:])

    text = _CHECKPOINT_RE.sub(replace_checkpoint, str(text))

    def replace_dimension(match: re.Match[str]) -> str:
        raw = match.group(0).upper().replace("_", ".")
        return _DIMENSION_NAMES.get(raw, raw)

    return _DIMENSION_RE.sub(replace_dimension, text)


def _model_visible_texts(*texts: str) -> tuple[str, ...]:
    return tuple(_model_visible_text(text) for text in texts)


def _model_aliases(*texts: str) -> dict[str, str]:
    """Build unambiguous model-visible aliases for post-call normalization."""

    candidates: dict[str, set[str]] = {}

    def register(alias: str, original: str) -> None:
        if alias and alias != original:
            candidates.setdefault(alias, set()).add(original)

    for text in texts:
        original_text = str(text)
        for match in _CHECKPOINT_RE.finditer(original_text):
            original = match.group(0)
            parts = original.split(".")
            register("criterion_" + "_".join(parts[-2:]), original)
        for match in _DIMENSION_RE.finditer(original_text):
            original = match.group(0).upper().replace("_", ".")
            register(_DIMENSION_NAMES.get(original, original), original)

    # Never guess when two hidden identifiers collapse to one public alias.
    return {
        alias: next(iter(originals))
        for alias, originals in candidates.items()
        if len(originals) == 1
    }


def parse_json_object(text: str) -> dict[str, Any]:
    cleaned = str(text).strip().lstrip("\ufeff")
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    if start < 0:
        raise ValueError("Model response does not contain a JSON object")
    value, _ = json.JSONDecoder().raw_decode(cleaned[start:])
    if not isinstance(value, dict):
        raise ValueError("Model response JSON must be an object")
    return value


_ALIAS_FIELDS = frozenset(
    {
        "batch_id",
        "checkpoint_id",
        "d4_3_source_checkpoint_ids",
        "dimension",
        "source_checkpoint_id",
        "source_checkpoint_ids",
        "task_id",
    }
)


def _restore_alias_value(value: str, aliases: Mapping[str, str]) -> str:
    normalized = re.sub(r"\\([_.])", r"\1", value)
    if normalized in aliases:
        return aliases[normalized]
    folded = normalized.casefold()
    for alias, original in aliases.items():
        if alias.casefold() == folded:
            return original
    return value


def _restore_aliases(
    value: Any,
    aliases: Mapping[str, str],
    *,
    field: str | None = None,
) -> Any:
    if isinstance(value, str):
        if field in _ALIAS_FIELDS:
            return _restore_alias_value(value, aliases)
        return value
    if isinstance(value, list):
        return [_restore_aliases(item, aliases, field=field) for item in value]
    if isinstance(value, dict):
        return {
            restored_key: _restore_aliases(item, aliases, field=restored_key)
            for key, item in value.items()
            for restored_key in (_restore_alias_value(str(key), aliases),)
        }
    return value


def _finish_reason(response: Mapping[str, Any]) -> str | None:
    choices = response.get("choices")
    if isinstance(choices, list) and choices and isinstance(choices[0], Mapping):
        value = choices[0].get("finish_reason")
        if value is not None:
            return str(value)
    for key in ("finish_reason", "stop_reason", "status"):
        if response.get(key) is not None:
            return str(response[key])
    return None


def _is_truncated(reason: str | None) -> bool:
    return str(reason or "").strip().casefold() in {
        "length",
        "max_tokens",
        "max_output_tokens",
        "incomplete",
    }


def extract_python_code(text: str) -> str:
    normalized = str(text).strip().lstrip("\ufeff")
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)\n```", normalized, re.DOTALL | re.IGNORECASE)
    if blocks:
        return max((block.strip() for block in blocks), key=len)
    if normalized.startswith("```") and normalized.endswith("```"):
        return normalized[3:-3].strip()
    return normalized


def _retryable(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status in {401, 408, 409, 429} or status >= 500
    name = type(exc).__name__.lower()
    message = str(exc).casefold()
    if any(
        value in name
        for value in (
            "timeout",
            "connection",
            "proxy",
            "ssl",
            "throttl",
            "protocol",
            "incompleteread",
        )
    ):
        return True
    # Some OpenAI-compatible relays return transient capacity errors as a
    # generic APIError without exposing an HTTP status code.
    return any(
        value in message
        for value in (
            "incomplete chunked",
            "overloaded",
            "temporarily unavailable",
            "try again later",
            "service unavailable",
            "server is busy",
            "server busy",
            "capacity",
            "too many requests",
            "rate limit",
        )
    )


def _permanent_judge_configuration_error(exc: BaseException) -> bool:
    """Authentication and request-configuration faults are not rescore gaps."""

    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and status in {400, 401, 403, 404, 422}


def candidate_generation_settings(model: Any) -> dict[str, Any]:
    """Resolve one explicitly supported candidate-generation endpoint."""

    provider = str(getattr(model, "provider", ""))
    requested_model = str(getattr(model, "model", ""))
    api_style = str(getattr(model, "api_style", "chat_completions"))
    configured_key_env = getattr(model, "api_key_env", None)
    configured_base_url = getattr(model, "base_url", None)
    if api_style != "chat_completions":
        raise ValueError(f"Unsupported candidate-generation API style: {api_style!r}")
    if (provider, requested_model) == (DASHSCOPE_PROVIDER, DASHSCOPE_MODEL):
        return {
            "provider": provider,
            "model": requested_model,
            "api_style": api_style,
            "api_key_env": str(configured_key_env or "DASHSCOPE_API_KEY"),
            "base_url": str(
                configured_base_url
                or os.getenv(
                    "DASHSCOPE_BASE_URL",
                    "https://dashscope.aliyuncs.com/compatible-mode/v1",
                )
            ),
            "enable_thinking": True,
        }
    if (provider, requested_model) == (OPENROUTER_PROVIDER, OPENROUTER_QWEN_MODEL):
        return {
            "provider": provider,
            "model": requested_model,
            "api_style": api_style,
            "api_key_env": str(configured_key_env or OPENROUTER_API_KEY_ENV),
            "base_url": str(
                configured_base_url
                or os.getenv("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL)
            ),
            "enable_thinking": False,
        }
    if (provider, requested_model) == (OPENROUTER_PROVIDER, OPENROUTER_KIMI_CODE_MODEL):
        configured_reasoning = getattr(model, "reasoning", None)
        reasoning = (
            dict(configured_reasoning)
            if isinstance(configured_reasoning, Mapping)
            else dict(OPENROUTER_KIMI_REASONING)
        )
        if reasoning != OPENROUTER_KIMI_REASONING:
            raise ValueError(
                "Kimi K2.7 Code candidate reasoning must use minimal effort "
                "with reasoning output excluded"
            )
        return {
            "provider": provider,
            "model": requested_model,
            "api_style": api_style,
            "api_key_env": str(configured_key_env or OPENROUTER_API_KEY_ENV),
            "base_url": str(
                configured_base_url
                or os.getenv("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL)
            ),
            "enable_thinking": False,
            "reasoning": reasoning,
        }
    if (provider, requested_model) == (OPENROUTER_PROVIDER, OPENROUTER_GPT56_TERRA_MODEL):
        configured_reasoning = getattr(model, "reasoning", None)
        reasoning = (
            dict(configured_reasoning)
            if isinstance(configured_reasoning, Mapping)
            else dict(OPENROUTER_GPT56_TERRA_REASONING)
        )
        if reasoning != OPENROUTER_GPT56_TERRA_REASONING:
            raise ValueError(
                "GPT-5.6 Terra candidate reasoning must be disabled with "
                "{'effort': 'none'}"
            )
        return {
            "provider": provider,
            "model": requested_model,
            "api_style": api_style,
            "api_key_env": str(configured_key_env or OPENROUTER_API_KEY_ENV),
            "base_url": str(
                configured_base_url
                or os.getenv("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL)
            ),
            "enable_thinking": False,
            "reasoning": reasoning,
        }
    if (provider, requested_model) == (LINK_OPENAI_PROVIDER, LINK_OPENAI_MODEL):
        return {
            "provider": provider,
            "model": requested_model,
            "api_style": api_style,
            "api_key_env": str(configured_key_env or LINK_OPENAI_API_KEY_ENV),
            "base_url": str(
                configured_base_url
                or os.getenv("LINK_OPENAI_BASE_URL", LINK_OPENAI_BASE_URL)
            ),
            "enable_thinking": False,
        }
    raise ValueError(
        "Candidate generation only supports "
        "alibaba_dashscope/qwen3.7-plus, openrouter/qwen/qwen3.7-plus, "
        "openrouter/moonshotai/kimi-k2.7-code, openrouter/openai/gpt-5.6-terra, "
        "or link_openai/gpt-5.6-sol"
    )


def candidate_api_key_env(model: Any) -> str:
    return str(candidate_generation_settings(model)["api_key_env"])


def _chat_client(model: Any) -> tuple[Any, str, dict[str, Any]]:
    settings = candidate_generation_settings(model)
    key_env = str(settings["api_key_env"])
    key = os.getenv(key_env)
    if not key:
        raise ValueError(f"{key_env} is not set")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install the openai-compatible SDK to use candidate generation") from exc
    return (
        OpenAI(
            api_key=key,
            base_url=str(settings["base_url"]),
            timeout=300.0,
            max_retries=0,
        ),
        key,
        settings,
    )


def _generate_once(
    model: Any,
    prompt: str,
    *,
    max_output_tokens: int,
    temperature: float,
) -> GenerationResult:
    client, key, settings = _chat_client(model)
    request_kwargs: dict[str, Any] = {
        "model": str(settings["model"]),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_output_tokens,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    reasoning = settings.get("reasoning")
    if isinstance(reasoning, Mapping):
        request_kwargs["extra_body"] = {"reasoning": dict(reasoning)}
    elif settings["provider"] == DASHSCOPE_PROVIDER:
        request_kwargs["extra_body"] = {"enable_thinking": True}
    response = client.chat.completions.create(**request_kwargs)
    parts: list[str] = []
    usage: dict[str, Any] | None = None
    response_model = str(settings["model"])
    request_id: str | None = None
    finish_reason: str | None = None
    chunks = 0
    for chunk in response:
        chunks += 1
        dumped = _dump(chunk)
        request_id = str(_get(chunk, "id") or dumped.get("id") or request_id) if (_get(chunk, "id") or dumped.get("id")) else request_id
        response_model = str(_get(chunk, "model") or dumped.get("model") or response_model)
        chunk_usage = _get(chunk, "usage") or dumped.get("usage")
        if chunk_usage is not None:
            usage = _dump(chunk_usage) or (dict(chunk_usage) if isinstance(chunk_usage, Mapping) else usage)
        choices = _get(chunk, "choices", [])
        if not choices:
            continue
        choice = choices[0]
        reason = _get(choice, "finish_reason")
        if reason is not None:
            finish_reason = str(reason)
        delta = _get(choice, "delta")
        content = _get(delta, "content") if delta is not None else None
        if isinstance(content, str):
            parts.append(content)
    text = "".join(parts)
    if not text:
        raise ValueError(f"{settings['provider']} returned no text content")
    request_parameters = {
        "max_output_tokens": max_output_tokens,
        "temperature": temperature,
        "provider": settings["provider"],
        "model": settings["model"],
        "api_style": settings["api_style"],
        "enable_thinking": settings["enable_thinking"],
        "stream": True,
        "stream_options": {"include_usage": True},
        "base_url": settings["base_url"],
    }
    if isinstance(reasoning, Mapping):
        request_parameters["reasoning"] = dict(reasoning)
    return GenerationResult(
        provider=str(settings["provider"]),
        requested_model=str(settings["model"]),
        response_model=response_model,
        text=text,
        code=extract_python_code(text),
        usage=usage,
        request_id=request_id,
        attempts=1,
        request_parameters=request_parameters,
        raw_response={
            "id": request_id,
            "model": response_model,
            "finish_reason": finish_reason,
            "usage": usage,
            "stream": True,
            "chunk_count": chunks,
            "content_characters": len(text),
            "credentials_logged": False,
            "api_key_present": bool(key),
        },
        finish_reason=finish_reason,
        truncated=_is_truncated(finish_reason),
    )


def generate_stage_source(
    model: Any,
    prompt: str,
    *,
    region: str = "us-east-1",
    max_output_tokens: int = 8000,
    temperature: float = 0.2,
    attempts: int = 2,
    retry_delays_seconds: list[float] | None = None,
    stage: str | None = None,
    stop_on_truncation: bool = True,
    result_validator: Callable[[GenerationResult], Sequence[str] | None] | None = None,
) -> GenerationResult:
    del region
    candidate_generation_settings(model)
    delays = retry_delays_seconds or [2.0]
    if int(attempts) != 2 or tuple(float(delay) for delay in delays) != (2.0,):
        raise ValueError(
            "Candidate generation requires two attempts with one 2-second delay"
        )
    last: BaseException | None = None
    history: list[dict[str, Any]] = []
    for attempt in range(1, int(attempts) + 1):
        try:
            result = _generate_once(model, prompt, max_output_tokens=max_output_tokens, temperature=temperature)
            result.attempts = attempt
            reasons = generation_output_issues(result, stage=stage)
            if result_validator is not None:
                try:
                    custom_reasons = result_validator(result)
                except BaseException as exc:
                    custom_reasons = [f"result_validator:{type(exc).__name__}: {exc}"]
                if custom_reasons:
                    reasons.extend(str(reason) for reason in custom_reasons)
            reasons = list(dict.fromkeys(reason for reason in reasons if str(reason)))
            if stop_on_truncation and reasons:
                invalid = GenerationOutputInvalid(result, reasons)
                record = _generation_attempt_record(
                    attempt=attempt,
                    result=result,
                    reasons=reasons,
                    error=invalid,
                )
                history.append(record)
                raise invalid
            result.attempt_history = [*history, _generation_attempt_record(
                attempt=attempt,
                result=result,
                reasons=reasons,
            )]
            return result
        except GenerationOutputInvalid as exc:
            last = exc
            if attempt >= attempts:
                raise GenerationNeedsRegeneration(
                    stage=stage or "unknown",
                    attempts=attempt,
                    attempt_history=history,
                    error=exc,
                ) from exc
            time.sleep(float(delays[min(attempt - 1, len(delays) - 1)] if delays else 0))
        except BaseException as exc:
            last = exc
            # An empty response is an output-completeness failure even though
            # the provider did not return a GenerationResult object.
            empty_output = isinstance(exc, ValueError) and "no text content" in str(exc).lower()
            if empty_output and stop_on_truncation:
                history.append(
                    _generation_attempt_record(
                        attempt=attempt,
                        reasons=("empty_output",),
                        error=exc,
                    )
                )
                if attempt >= attempts:
                    raise GenerationNeedsRegeneration(
                        stage=stage or "unknown",
                        attempts=attempt,
                        attempt_history=history,
                        error=exc,
                    ) from exc
                time.sleep(float(delays[min(attempt - 1, len(delays) - 1)] if delays else 0))
                continue
            if attempt >= attempts or not _retryable(exc):
                raise RuntimeError(_redact(f"Model call failed: {type(exc).__name__}: {exc}")) from exc
            time.sleep(float(delays[min(attempt - 1, len(delays) - 1)] if delays else 0))
    raise RuntimeError(_redact(f"Model call failed: {last}"))


def _image_format(path: Path) -> str:
    guessed = mimetypes.guess_type(path.name)[0] or "image/png"
    return guessed.split("/", 1)[-1] if guessed.startswith("image/") else "png"


def _usage_numbers(usage: Mapping[str, Any]) -> tuple[int, int, int, int]:
    def number(*keys: str) -> int:
        for key in keys:
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return value
        return 0

    return (
        number("prompt_tokens", "input_tokens"),
        number("completion_tokens", "output_tokens"),
        number("reasoning_tokens"),
        number("cached_tokens", "cache_read_input_tokens"),
    )


def _normalize_response_format(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Validate the optional JSON-mode configuration for a judge profile."""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("judge response_format must be an object when configured")
    normalized = dict(value)
    if normalized != {"type": "json_object"}:
        raise ValueError("judge response_format must be exactly {'type': 'json_object'}")
    return normalized


def _normalize_openrouter_reasoning(
    value: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Validate an approved policy-specific reasoning setting for OpenRouter."""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("judge reasoning must be an object when configured")
    normalized = dict(value)
    if normalized not in (
        OPENROUTER_QWEN_JUDGE_REASONING,
        _LEGACY_OPENROUTER_QWEN_JUDGE_REASONING,
    ):
        raise ValueError(
            "judge reasoning must be exactly {'effort': 'none'} or the "
            "legacy {'effort': 'minimal', 'exclude': True'} setting"
        )
    return normalized


_EOF_SYNTAX_MARKERS = (
    "unexpected eof",
    "eof in multi-line statement",
    "incomplete input",
    "was never closed",
    "unterminated string",
    "unterminated triple-quoted string",
    "expected an indented block",
    "expected 'except' or 'finally' block",
    "expected 'finally' or 'except' block",
)


def _has_unclosed_code_fence(text: str) -> bool:
    fences = re.findall(r"(?m)^[ \t]*```(?:[A-Za-z0-9_-]+)?[ \t]*$", str(text))
    return len(fences) % 2 == 1


def _is_eof_syntax_error(error: SyntaxError) -> bool:
    message = str(getattr(error, "msg", error)).casefold()
    return any(marker in message for marker in _EOF_SYNTAX_MARKERS)


def generation_output_issues(
    result: GenerationResult,
    *,
    stage: str | None = None,
) -> list[str]:
    """Return only conservative completeness defects for a generated response.

    Ordinary syntax, interface, and dependency defects remain candidate
    diagnostics.  This helper is intentionally limited to defects that make it
    unsafe to install the response as a stage artifact.
    """

    issues: list[str] = []
    finish_reason = str(result.finish_reason or "").casefold()
    if result.truncated or _is_truncated(result.finish_reason):
        issues.append(f"truncated_finish_reason:{finish_reason or 'truncated'}")
    if not str(result.text or "").strip():
        issues.append("empty_output")
    if _has_unclosed_code_fence(result.text):
        issues.append("unclosed_code_fence")
    if not str(result.code or "").strip():
        issues.append("empty_code")
    if str(result.code or "").strip():
        try:
            ast.parse(result.code, filename=stage or "generated.py")
        except SyntaxError as exc:
            if _is_eof_syntax_error(exc):
                issues.append(f"eof_syntax_error:{exc.msg}")
    return list(dict.fromkeys(issues))


def _generation_attempt_record(
    *,
    attempt: int,
    result: GenerationResult | None = None,
    reasons: Sequence[str] = (),
    error: BaseException | None = None,
) -> dict[str, Any]:
    text = result.text if result is not None else ""
    record: dict[str, Any] = {
        "attempt": int(attempt),
        "provider": result.provider if result is not None else None,
        "requested_model": result.requested_model if result is not None else None,
        "response_model": result.response_model if result is not None else None,
        "finish_reason": result.finish_reason if result is not None else None,
        "usage": result.usage if result is not None else None,
        "request_id": result.request_id if result is not None else None,
        "output_sha256": hashlib.sha256(str(text).encode("utf-8")).hexdigest(),
        "truncated": bool(result.truncated) if result is not None else False,
        "reasons": [str(reason) for reason in reasons if str(reason)],
        "text": str(text),
        "code": result.code if result is not None else "",
        "raw_response": dict(result.raw_response) if result is not None else {},
        "request_parameters": (
            dict(result.request_parameters) if result is not None else {}
        ),
    }
    if error is not None:
        record["error_type"] = type(error).__name__
        record["error"] = _redact(str(error))
    return record


def _request_log_directory(log_root: Path, purpose: str) -> tuple[Path, str]:
    """Create a collision-free, filesystem-safe directory for one Judge call."""

    safe_purpose = re.sub(r"[^A-Za-z0-9._-]+", "_", str(purpose)).strip("._-")
    safe_purpose = safe_purpose[:96] or "request"
    request_id = (
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}"
        f"-{uuid4().hex[:12]}-{safe_purpose}"
    )
    call_dir = log_root / request_id
    call_dir.mkdir(parents=True, exist_ok=False)
    return call_dir, request_id


def _write_request_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(dict(payload), ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


class OpenAICompatibleChatJudge:
    """Stateless JSON/vision client with exactly one local retry.

    Provider and model are selected by the router. The retry contract remains
    fixed at two attempts with a single two-second delay for every provider.
    """

    def __init__(
        self,
        log_dir: Path,
        *,
        provider: str,
        model: str,
        api_style: str = "chat_completions",
        api_key_env: str,
        base_url: str,
        max_output_tokens: int = MAX_JUDGE_OUTPUT_TOKENS,
        enable_thinking: bool = False,
        attempts: int = 2,
        retry_delays_seconds: Sequence[float] = (2,),
        role: str = "scoring",
        response_format: Mapping[str, Any] | None = None,
        reasoning: Mapping[str, Any] | None = None,
        client: Any | None = None,
    ) -> None:
        if not provider or not model:
            raise ValueError("Judge provider and model must be non-empty")
        if api_style != "chat_completions":
            raise ValueError(f"Unsupported judge API style: {api_style!r}")
        if attempts != 2 or tuple(float(value) for value in retry_delays_seconds) != (2.0,):
            raise ValueError("Judge requests require two attempts with one 2-second delay")
        self.provider = str(provider)
        self.model = model
        self.api_style = api_style
        self.api_key_env = api_key_env
        self.max_output_tokens = int(max_output_tokens)
        self.enable_thinking = bool(enable_thinking)
        self.attempts = int(attempts)
        self.retry_delays_seconds = tuple(float(value) for value in retry_delays_seconds)
        self.role = str(role)
        self.response_format = _normalize_response_format(response_format)
        if self.provider != OPENROUTER_PROVIDER and reasoning is not None:
            raise ValueError("judge reasoning is supported only for OpenRouter routes")
        self.reasoning = _normalize_openrouter_reasoning(reasoning)
        self.log_dir = Path(log_dir).resolve()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        if client is None:
            key = os.getenv(api_key_env)
            if not key:
                raise ValueError(f"{api_key_env} is not set")
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError("Install the openai-compatible SDK to use a judge provider") from exc
            client = OpenAI(api_key=key, base_url=base_url, timeout=300.0, max_retries=0)
        else:
            key = os.getenv(api_key_env, "")
        self.client = client
        self._api_key = key
        self.base_url = base_url

    def json_text(self, instructions: str, prompt: str, purpose: str) -> dict[str, Any]:
        return self._call(instructions, prompt, (), purpose).parsed_output

    def json_text_validated(
        self,
        instructions: str,
        prompt: str,
        purpose: str,
        validator: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        return self._call(instructions, prompt, (), purpose, validator=validator).parsed_output

    def json_vision(
        self,
        instructions: str,
        prompt: str,
        images: Sequence[tuple[Path, str]],
        purpose: str,
    ) -> dict[str, Any]:
        return self._call(instructions, prompt, images, purpose).parsed_output

    def json_vision_validated(
        self,
        instructions: str,
        prompt: str,
        images: Sequence[tuple[Path, str]],
        purpose: str,
        validator: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        return self._call(instructions, prompt, images, purpose, validator=validator).parsed_output

    def execute(self, request: ModelRequest) -> ModelResult:
        if request.role != self.role:
            raise ValueError(f"ModelRequest role {request.role!r} does not match {self.role!r}")
        if request.modality not in {"text", "vision"}:
            raise ValueError("ModelRequest modality must be text or vision")
        return self._call(request.instructions, request.prompt, request.images, request.request_id)

    def _call(
        self,
        instructions: str,
        prompt: str,
        images: Sequence[tuple[Path, str]],
        purpose: str,
        validator: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> ModelResult:
        visible = _model_visible_texts(instructions, prompt, *(label for _path, label in images))
        safe_instructions = _redact(visible[0], [self._api_key])
        safe_prompt = _redact(visible[1], [self._api_key])
        aliases = _model_aliases(
            instructions,
            prompt,
            *(label for _path, label in images),
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": safe_prompt}]
        image_records: list[dict[str, Any]] = []
        for (path, _label), label in zip(images, visible[2:], strict=True):
            image_format = _image_format(path)
            image_records.append({"path": str(path.resolve()), "label": _redact(label, [self._api_key]), "format": image_format})
            content.append({"type": "text", "text": _redact(label, [self._api_key])})
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/{image_format};base64,{encoded}"}})
        call_dir, request_id = _request_log_directory(self.log_dir, purpose)
        request_log = {
            "request_id": request_id,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "purpose": purpose,
            "provider": self.provider,
            "model": self.model,
            "api_style": self.api_style,
            "base_url": self.base_url,
            "role": self.role,
            "temperature": 0.0,
            "enable_thinking": self.enable_thinking,
            "response_format": self.response_format,
            "reasoning": self.reasoning,
            "max_output_tokens": self.max_output_tokens,
            "request_attempt_limit": self.attempts,
            "stateless": True,
            "instructions": safe_instructions,
            "prompt": safe_prompt,
            "images": image_records,
            "credentials_logged": False,
            "authorization_logged": False,
        }
        _write_request_json(call_dir / "raw_input.json", request_log)
        messages: list[dict[str, Any]] = [{"role": "system", "content": safe_instructions}, {"role": "user", "content": content if images else safe_prompt}]
        last: BaseException | None = None
        attempt_records: list[dict[str, Any]] = []
        for attempt in range(1, self.attempts + 1):
            raw_text = ""
            finish_reason: str | None = None
            try:
                request_kwargs: dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": self.max_output_tokens,
                    "temperature": 0.0,
                    "stream": False,
                }
                if self.response_format is not None:
                    request_kwargs["response_format"] = self.response_format
                if self.provider == OPENROUTER_PROVIDER and self.reasoning is not None:
                    request_kwargs["extra_body"] = {"reasoning": dict(self.reasoning)}
                elif self.provider == DASHSCOPE_PROVIDER:
                    request_kwargs["extra_body"] = {"enable_thinking": self.enable_thinking}
                response = self.client.chat.completions.create(
                    **request_kwargs,
                )
                dumped = _dump(response)
                usage_value = dumped.get("usage")
                usage = dict(usage_value) if isinstance(usage_value, Mapping) else {}
                finish_reason = _finish_reason(dumped)
                attempt_records.append(
                    {
                        "attempt": attempt,
                        "usage": usage,
                        "finish_reason": finish_reason,
                    }
                )
                _write_request_json(call_dir / f"raw_response_attempt_{attempt:03d}.json", dumped)
                choices = _get(response, "choices", [])
                if not choices:
                    (call_dir / f"raw_output_attempt_{attempt:03d}.txt").write_text(
                        "",
                        encoding="utf-8",
                    )
                    raise ValueError(f"{self.provider} judge returned no choices")
                message = _get(choices[0], "message")
                response_text = _get(message, "content")
                if isinstance(response_text, str):
                    raw_text = _redact(response_text, [self._api_key])
                (call_dir / f"raw_output_attempt_{attempt:03d}.txt").write_text(
                    raw_text,
                    encoding="utf-8",
                )
                if not isinstance(response_text, str):
                    raise ValueError(f"{self.provider} judge returned no text content")
                parsed = _restore_aliases(parse_json_object(raw_text), aliases)
                if validator is not None:
                    parsed = validator(parsed)
                if not isinstance(parsed, dict):
                    raise ValueError("Model response validator must return an object")
                input_tokens, output_tokens, reasoning_tokens, cached_tokens = _usage_numbers(usage)
                _write_request_json(call_dir / "parsed_output.json", parsed)
                _write_request_json(
                    call_dir / "request_result.json",
                    {
                        "request_id": request_id,
                        "purpose": purpose,
                        "status": "completed",
                        "attempts_made": attempt,
                        "attempt_limit": self.attempts,
                        "attempts": attempt_records,
                        "finish_reason": finish_reason,
                    },
                )
                return ModelResult(parsed, input_tokens, output_tokens, reasoning_tokens, cached_tokens, attempt, {"attempts": attempt_records})
            except BaseException as exc:
                last = exc
                failure = {"attempt": attempt, "type": type(exc).__name__, "message": _redact(str(exc), [self._api_key]), "finish_reason": finish_reason}
                _write_request_json(call_dir / f"attempt_error_{attempt:03d}.json", failure)
                retryable_output_error = isinstance(exc, (ValueError, json.JSONDecodeError))
                retryable_transport_error = _retryable(exc) and not _permanent_judge_configuration_error(exc)
                if not retryable_output_error and not retryable_transport_error:
                    _write_request_json(
                        call_dir / "request_result.json",
                        {
                            "request_id": request_id,
                            "purpose": purpose,
                            "status": "failed",
                            "attempts_made": attempt,
                            "attempt_limit": self.attempts,
                            "attempts": attempt_records,
                            "finish_reason": finish_reason,
                            "error": failure,
                        },
                    )
                    raise
                if attempt >= self.attempts:
                    _write_request_json(
                        call_dir / "request_result.json",
                        {
                            "request_id": request_id,
                            "purpose": purpose,
                            "status": "attempts_exhausted",
                            "attempts_made": attempt,
                            "attempt_limit": self.attempts,
                            "attempts": attempt_records,
                            "finish_reason": finish_reason,
                            "error": failure,
                        },
                    )
                    raise JudgeAttemptsExhausted(
                        purpose=purpose,
                        attempts=self.attempts,
                        error=exc,
                    ) from exc
                if isinstance(exc, (ValueError, json.JSONDecodeError)):
                    correction = (
                        "Discard the previous response and regenerate one corrected, "
                        "complete minified JSON object. The previous response failed "
                        "local validation with this exact error: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    messages = [
                        *messages,
                        {
                            "role": "assistant",
                            "content": _redact(
                                raw_text,
                                [self._api_key],
                            ),
                        },
                        {"role": "user", "content": _redact(correction, [self._api_key])},
                    ]
                time.sleep(self.retry_delays_seconds[min(attempt - 1, len(self.retry_delays_seconds) - 1)])
        raise RuntimeError(_redact(f"{self.provider} judge failed: {last}", [self._api_key]))


class DashScopeChatJudge(OpenAICompatibleChatJudge):
    """DashScope Qwen3.7-Plus client."""

    def __init__(
        self,
        log_dir: Path,
        *,
        model: str = DASHSCOPE_MODEL,
        max_output_tokens: int = MAX_JUDGE_OUTPUT_TOKENS,
        enable_thinking: bool = False,
        attempts: int = 2,
        retry_delays_seconds: Sequence[float] = (2,),
        role: str = "scoring",
        response_format: Mapping[str, Any] | None = None,
        client: Any | None = None,
        base_url: str | None = None,
    ) -> None:
        if model != DASHSCOPE_MODEL:
            raise ValueError("DashScope judge only supports qwen3.7-plus")
        super().__init__(
            log_dir,
            provider=DASHSCOPE_PROVIDER,
            model=model,
            api_style=DASHSCOPE_API_STYLE,
            api_key_env="DASHSCOPE_API_KEY",
            base_url=base_url or os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            max_output_tokens=max_output_tokens,
            enable_thinking=enable_thinking,
            attempts=attempts,
            retry_delays_seconds=retry_delays_seconds,
            role=role,
            response_format=response_format,
            client=client,
        )


class OpenRouterChatJudge(OpenAICompatibleChatJudge):
    """OpenRouter client for a role that is configured for another model."""

    def __init__(
        self,
        log_dir: Path,
        *,
        model: str = OPENROUTER_MODEL,
        max_output_tokens: int = MAX_JUDGE_OUTPUT_TOKENS,
        enable_thinking: bool = False,
        attempts: int = 2,
        retry_delays_seconds: Sequence[float] = (2,),
        role: str = "scoring",
        response_format: Mapping[str, Any] | None = None,
        reasoning: Mapping[str, Any] | None = None,
        client: Any | None = None,
        base_url: str | None = None,
        api_key_env: str = OPENROUTER_API_KEY_ENV,
    ) -> None:
        super().__init__(
            log_dir,
            provider=OPENROUTER_PROVIDER,
            model=model,
            api_style=OPENROUTER_API_STYLE,
            api_key_env=api_key_env,
            base_url=base_url or os.getenv("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL),
            max_output_tokens=max_output_tokens,
            enable_thinking=enable_thinking,
            attempts=attempts,
            retry_delays_seconds=retry_delays_seconds,
            role=role,
            response_format=response_format,
            reasoning=reasoning,
            client=client,
        )


class LinkOpenAIChatJudge(OpenAICompatibleChatJudge):
    """Link's OpenAI-compatible endpoint for the fixed GPT-5.6 Sol trial."""

    def __init__(
        self,
        log_dir: Path,
        *,
        model: str = LINK_OPENAI_MODEL,
        max_output_tokens: int = MAX_JUDGE_OUTPUT_TOKENS,
        enable_thinking: bool = False,
        attempts: int = 2,
        retry_delays_seconds: Sequence[float] = (2,),
        role: str = "scoring",
        response_format: Mapping[str, Any] | None = None,
        client: Any | None = None,
        base_url: str | None = None,
        api_key_env: str = LINK_OPENAI_API_KEY_ENV,
    ) -> None:
        if model != LINK_OPENAI_MODEL:
            raise ValueError("Link judge only supports gpt-5.6-sol")
        super().__init__(
            log_dir,
            provider=LINK_OPENAI_PROVIDER,
            model=model,
            api_style=LINK_OPENAI_API_STYLE,
            api_key_env=api_key_env,
            base_url=base_url or os.getenv("LINK_OPENAI_BASE_URL", LINK_OPENAI_BASE_URL),
            max_output_tokens=max_output_tokens,
            enable_thinking=enable_thinking,
            attempts=attempts,
            retry_delays_seconds=retry_delays_seconds,
            role=role,
            response_format=response_format,
            client=client,
        )


def create_dashscope_judge(
    log_dir: Path,
    *,
    model: str = DASHSCOPE_MODEL,
    max_output_tokens: int = MAX_JUDGE_OUTPUT_TOKENS,
    enable_thinking: bool = False,
    attempts: int = 2,
    retry_delays_seconds: Sequence[float] = (2,),
    role: str = "scoring",
    response_format: Mapping[str, Any] | None = None,
    client: Any | None = None,
    **_ignored: Any,
) -> SemanticJudge:
    return DashScopeChatJudge(log_dir, model=model, max_output_tokens=max_output_tokens, enable_thinking=enable_thinking, attempts=attempts, retry_delays_seconds=retry_delays_seconds, role=role, response_format=response_format, client=client)


def create_judge(
    log_dir: Path,
    *,
    provider: str,
    model: str,
    api_style: str = "chat_completions",
    api_key_env: str | None = None,
    base_url: str | None = None,
    max_output_tokens: int = MAX_JUDGE_OUTPUT_TOKENS,
    enable_thinking: bool = False,
    attempts: int = 2,
    retry_delays_seconds: Sequence[float] = (2,),
    role: str = "scoring",
    response_format: Mapping[str, Any] | None = None,
    reasoning: Mapping[str, Any] | None = None,
    client: Any | None = None,
    **_ignored: Any,
) -> SemanticJudge:
    if provider == DASHSCOPE_PROVIDER:
        return DashScopeChatJudge(
            log_dir,
            model=model,
            max_output_tokens=max_output_tokens,
            enable_thinking=enable_thinking,
            attempts=attempts,
            retry_delays_seconds=retry_delays_seconds,
            role=role,
            response_format=response_format,
            client=client,
            base_url=base_url,
        )
    if provider == OPENROUTER_PROVIDER:
        return OpenRouterChatJudge(
            log_dir,
            model=model,
            max_output_tokens=max_output_tokens,
            enable_thinking=enable_thinking,
            attempts=attempts,
            retry_delays_seconds=retry_delays_seconds,
            role=role,
            response_format=response_format,
            reasoning=reasoning,
            client=client,
            base_url=base_url,
            api_key_env=api_key_env or OPENROUTER_API_KEY_ENV,
        )
    if provider == LINK_OPENAI_PROVIDER:
        return LinkOpenAIChatJudge(
            log_dir,
            model=model,
            max_output_tokens=max_output_tokens,
            enable_thinking=enable_thinking,
            attempts=attempts,
            retry_delays_seconds=retry_delays_seconds,
            role=role,
            response_format=response_format,
            client=client,
            base_url=base_url,
            api_key_env=api_key_env or LINK_OPENAI_API_KEY_ENV,
        )
    raise ValueError(f"Unsupported judge provider: {provider!r}")


class JudgeRouter:
    """Route evaluator roles through configurable text/vision profiles."""

    def __init__(self, config: Mapping[str, Any], log_root: Path, client_factory: Callable[..., Any] | None = None) -> None:
        self.config = dict(config)
        self.log_root = Path(log_root).resolve()
        self._clients: dict[str, SemanticJudge] = {}
        self._clients_lock = Lock()
        self._client_factory = client_factory or create_judge

    def for_role(self, role: str) -> SemanticJudge:
        with self._clients_lock:
            if role in self._clients:
                return self._clients[role]
            route = resolve_judge_route(self.config, role)
            client = self._client_factory(
                self.log_root / role,
                provider=str(route["provider"]),
                model=str(route["model"]),
                api_style=str(route.get("api_style", "chat_completions")),
                api_key_env=route.get("api_key_env"),
                base_url=route.get("base_url"),
                max_output_tokens=int(route["max_output_tokens"]),
                enable_thinking=bool(route.get("enable_thinking", False)),
                attempts=int(self.config.get("attempts", 2)),
                retry_delays_seconds=self.config.get("retry_delays_seconds", [2]),
                role=role,
                response_format=route.get("response_format"),
                reasoning=route.get("reasoning"),
            )
            self._clients[role] = client
            return client

    def scoring(self) -> SemanticJudge:
        return RoutedSemanticJudge(self)

    def execute(self, request: ModelRequest) -> ModelResult:
        client = self.for_role(request.role)
        execute = getattr(client, "execute", None)
        if not callable(execute):
            raise TypeError(f"Configured client for {request.role!r} lacks execute()")
        return execute(request)


def resolve_judge_route(config: Mapping[str, Any], role: str) -> dict[str, Any]:
    """Return the effective provider route for one evaluator role.

    Per-role output limits stay in ``routes``. Provider identity is selected
    through the role's modality profile, so changing the vision provider does
    not require touching evaluation code.
    """
    routes = config.get("routes", {})
    route = routes.get(role) if isinstance(routes, Mapping) else None
    if not isinstance(route, Mapping):
        raise KeyError(f"No evaluator model route configured for role {role!r}")
    resolved = dict(route)
    routing = config.get("routing", {})
    profiles = routing.get("profiles", {}) if isinstance(routing, Mapping) else {}
    role_modalities = routing.get("role_modalities", {}) if isinstance(routing, Mapping) else {}
    roles = routing.get("roles", {}) if isinstance(routing, Mapping) else {}
    modality = role_modalities.get(role) if isinstance(role_modalities, Mapping) else None
    profile_name = roles.get(modality) if modality and isinstance(roles, Mapping) else None
    profile = profiles.get(profile_name) if profile_name and isinstance(profiles, Mapping) else None
    if profile is not None:
        if not isinstance(profile, Mapping):
            raise ValueError(f"Judge profile {profile_name!r} must be a mapping")
        for key in (
            "provider",
            "model",
            "api_style",
            "api_key_env",
            "base_url",
            "response_format",
            "reasoning",
        ):
            if key in profile:
                resolved[key] = profile[key]
    if not resolved.get("provider") or not resolved.get("model"):
        raise ValueError(f"Judge route {role!r} is missing provider or model")
    return resolved


class RoutedSemanticJudge:
    def __init__(self, router: JudgeRouter) -> None:
        self.router = router

    @staticmethod
    def _role(purpose: str) -> str:
        if purpose.startswith("d2_compile_") or purpose.startswith("d4_compile_"):
            return "action_compiler"
        if purpose.startswith("d2_dimension_") or purpose.startswith("d2_checkpoint_"):
            return "functionality"
        if purpose == "d2_specification_deviation":
            return "specification_deviation"
        if purpose == "d3_semantic_code_quality":
            return "code_quality"
        if purpose == "d4_1_artistic_visual_quality":
            return "artistic_visual"
        if purpose.startswith("d4_2_"):
            return "dynamic_visual"
        if purpose.startswith("d4_3_questions"):
            return "question_generation"
        if purpose.startswith("d4_3_"):
            return "question_answering"
        if purpose.startswith("d4_contract"):
            return "contract_generation"
        raise KeyError(f"No evaluator role mapping for purpose {purpose!r}")

    def json_text(self, instructions: str, prompt: str, purpose: str) -> dict[str, Any]:
        return self.router.for_role(self._role(purpose)).json_text(instructions, prompt, purpose)

    def json_text_validated(self, instructions: str, prompt: str, purpose: str, validator: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        client = self.router.for_role(self._role(purpose))
        method = getattr(client, "json_text_validated", None)
        return method(instructions, prompt, purpose, validator) if callable(method) else validator(client.json_text(instructions, prompt, purpose))

    def json_vision(self, instructions: str, prompt: str, images: Sequence[tuple[Path, str]], purpose: str) -> dict[str, Any]:
        return self.router.for_role(self._role(purpose)).json_vision(instructions, prompt, images, purpose)

    def json_vision_validated(self, instructions: str, prompt: str, images: Sequence[tuple[Path, str]], purpose: str, validator: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any]:
        client = self.router.for_role(self._role(purpose))
        method = getattr(client, "json_vision_validated", None)
        return method(instructions, prompt, images, purpose, validator) if callable(method) else validator(client.json_vision(instructions, prompt, images, purpose))


__all__ = [
    "DASHSCOPE_API_STYLE",
    "DASHSCOPE_MODEL",
    "DASHSCOPE_PROVIDER",
    "DashScopeChatJudge",
    "GenerationNeedsRegeneration",
    "GenerationOutputInvalid",
    "GenerationResult",
    "JudgeAttemptsExhausted",
    "JudgeRouter",
    "MAX_JUDGE_OUTPUT_TOKENS",
    "LINK_OPENAI_API_KEY_ENV",
    "LINK_OPENAI_API_STYLE",
    "LINK_OPENAI_BASE_URL",
    "LINK_OPENAI_MODEL",
    "LINK_OPENAI_PROVIDER",
    "LinkOpenAIChatJudge",
    "ModelRequest",
    "ModelResult",
    "OPENROUTER_API_STYLE",
    "OPENROUTER_API_KEY_ENV",
    "OPENROUTER_BASE_URL",
    "OPENROUTER_GPT56_TERRA_MODEL",
    "OPENROUTER_GPT56_TERRA_REASONING",
    "OPENROUTER_KIMI_CODE_MODEL",
    "OPENROUTER_KIMI_REASONING",
    "OPENROUTER_MODEL",
    "OPENROUTER_PROVIDER",
    "OPENROUTER_QWEN_MODEL",
    "OPENROUTER_QWEN_VL_MODEL",
    "OPENROUTER_QWEN_JUDGE_REASONING",
    "OpenAICompatibleChatJudge",
    "OpenRouterChatJudge",
    "RoutedSemanticJudge",
    "SemanticJudge",
    "create_judge",
    "create_dashscope_judge",
    "candidate_api_key_env",
    "candidate_generation_settings",
    "extract_python_code",
    "generation_output_issues",
    "generate_stage_source",
    "parse_json_object",
    "redact_sensitive_text",
    "resolve_judge_route",
]
