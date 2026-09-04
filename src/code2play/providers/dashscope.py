"""The single Qwen3.7-Plus provider used by every model-facing operation.

The provider deliberately keeps the evaluator-facing interface small.  It is
also usable with a fake OpenAI-compatible client in tests, so the default test
suite never needs a paid API call.
"""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
import mimetypes
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping, Protocol, Sequence


DASHSCOPE_PROVIDER = "alibaba_dashscope"
DASHSCOPE_MODEL = "qwen3.7-plus"
DASHSCOPE_API_STYLE = "chat_completions"
MAX_JUDGE_OUTPUT_TOKENS = 6000
JUDGE_TEMPERATURE = 0.0
PANEL_POLICY = "single_qwen37_plus_stateless"

_SECRET_ENV_NAMES = ("DASHSCOPE_API_KEY",)
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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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
    return str(reason or "").lower() in {"length", "max_tokens", "max_output_tokens", "incomplete"}


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
    return any(value in name for value in ("timeout", "connection", "proxy", "ssl", "throttl"))


def _permanent_judge_configuration_error(exc: BaseException) -> bool:
    """Authentication and request-configuration faults are not rescore gaps."""

    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and status in {400, 401, 403, 404, 422}


def _chat_client() -> tuple[Any, str, str]:
    key = os.getenv("DASHSCOPE_API_KEY")
    if not key:
        raise ValueError("DASHSCOPE_API_KEY is not set")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Install the openai-compatible SDK to use DashScope") from exc
    base_url = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    return OpenAI(api_key=key, base_url=base_url, timeout=300.0, max_retries=0), key, base_url


def _generate_once(
    model: Any,
    prompt: str,
    *,
    max_output_tokens: int,
    temperature: float,
) -> GenerationResult:
    client, key, base_url = _chat_client()
    response = client.chat.completions.create(
        model=model.model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_output_tokens,
        temperature=temperature,
        extra_body={"enable_thinking": True},
        stream=True,
        stream_options={"include_usage": True},
    )
    parts: list[str] = []
    usage: dict[str, Any] | None = None
    response_model = model.model
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
        raise ValueError("DashScope returned no text content")
    return GenerationResult(
        provider=DASHSCOPE_PROVIDER,
        requested_model=model.model,
        response_model=response_model,
        text=text,
        code=extract_python_code(text),
        usage=usage,
        request_id=request_id,
        attempts=1,
        request_parameters={
            "max_output_tokens": max_output_tokens,
            "temperature": temperature,
            "provider": DASHSCOPE_PROVIDER,
            "model": DASHSCOPE_MODEL,
            "api_style": DASHSCOPE_API_STYLE,
            "enable_thinking": True,
            "stream": True,
            "stream_options": {"include_usage": True},
            "base_url": base_url,
        },
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
) -> GenerationResult:
    del region
    if getattr(model, "provider", None) != DASHSCOPE_PROVIDER or getattr(model, "model", None) != DASHSCOPE_MODEL:
        raise ValueError("Candidate generation only supports alibaba_dashscope/qwen3.7-plus")
    delays = retry_delays_seconds or [2.0]
    last: BaseException | None = None
    for attempt in range(1, int(attempts) + 1):
        try:
            result = _generate_once(model, prompt, max_output_tokens=max_output_tokens, temperature=temperature)
            result.attempts = attempt
            return result
        except BaseException as exc:
            last = exc
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


class DashScopeChatJudge:
    """Stateless Qwen JSON/vision client with exactly one local retry."""

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
        client: Any | None = None,
    ) -> None:
        if model != DASHSCOPE_MODEL:
            raise ValueError("Only qwen3.7-plus is permitted")
        if attempts != 2 or tuple(float(value) for value in retry_delays_seconds) != (2.0,):
            raise ValueError("Qwen judge requests require two attempts with one 2-second delay")
        self.model = model
        self.max_output_tokens = int(max_output_tokens)
        self.enable_thinking = bool(enable_thinking)
        self.attempts = int(attempts)
        self.retry_delays_seconds = tuple(float(value) for value in retry_delays_seconds)
        self.role = str(role)
        self.log_dir = Path(log_dir).resolve()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        if client is None:
            client, key, base_url = _chat_client()
        else:
            key = os.getenv("DASHSCOPE_API_KEY", "")
            base_url = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
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
        request_log = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "purpose": purpose,
            "provider": DASHSCOPE_PROVIDER,
            "model": DASHSCOPE_MODEL,
            "api_style": DASHSCOPE_API_STYLE,
            "base_url": self.base_url,
            "role": self.role,
            "temperature": 0.0,
            "enable_thinking": self.enable_thinking,
            "max_output_tokens": self.max_output_tokens,
            "stateless": True,
            "instructions": safe_instructions,
            "prompt": safe_prompt,
            "images": image_records,
            "credentials_logged": False,
            "authorization_logged": False,
        }
        (self.log_dir / "raw_input.json").write_text(json.dumps(request_log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        messages: list[dict[str, Any]] = [{"role": "system", "content": safe_instructions}, {"role": "user", "content": content if images else safe_prompt}]
        last: BaseException | None = None
        usages: list[dict[str, Any]] = []
        for attempt in range(1, self.attempts + 1):
            try:
                response = self.client.chat.completions.create(
                    model=DASHSCOPE_MODEL,
                    messages=messages,
                    max_tokens=self.max_output_tokens,
                    temperature=0.0,
                    extra_body={"enable_thinking": self.enable_thinking},
                    stream=False,
                )
                dumped = _dump(response)
                choices = _get(response, "choices", [])
                if not choices:
                    raise ValueError("DashScope judge returned no choices")
                message = _get(choices[0], "message")
                raw_text = _get(message, "content")
                if not isinstance(raw_text, str):
                    raise ValueError("DashScope judge returned no text content")
                raw_text = _redact(raw_text, [self._api_key])
                usage = dumped.get("usage")
                usage = dict(usage) if isinstance(usage, Mapping) else {}
                usages.append(usage)
                (self.log_dir / f"raw_output_attempt_{attempt:03d}.txt").write_text(raw_text, encoding="utf-8")
                (self.log_dir / f"raw_response_attempt_{attempt:03d}.json").write_text(json.dumps(dumped, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                parsed = _restore_aliases(parse_json_object(raw_text), aliases)
                if validator is not None:
                    parsed = validator(parsed)
                if not isinstance(parsed, dict):
                    raise ValueError("Model response validator must return an object")
                input_tokens, output_tokens, reasoning_tokens, cached_tokens = _usage_numbers(usage)
                return ModelResult(parsed, input_tokens, output_tokens, reasoning_tokens, cached_tokens, attempt, {"attempts": usages})
            except BaseException as exc:
                last = exc
                failure = {"attempt": attempt, "type": type(exc).__name__, "message": _redact(str(exc), [self._api_key])}
                (self.log_dir / f"attempt_error_{attempt:03d}.json").write_text(json.dumps(failure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                retryable_output_error = isinstance(exc, (ValueError, json.JSONDecodeError))
                retryable_transport_error = _retryable(exc) and not _permanent_judge_configuration_error(exc)
                if not retryable_output_error and not retryable_transport_error:
                    raise
                if attempt >= self.attempts:
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
                                str(raw_text) if "raw_text" in locals() else "",
                                [self._api_key],
                            ),
                        },
                        {"role": "user", "content": _redact(correction, [self._api_key])},
                    ]
                time.sleep(self.retry_delays_seconds[min(attempt - 1, len(self.retry_delays_seconds) - 1)])
        raise RuntimeError(_redact(f"Qwen judge failed: {last}", [self._api_key]))


def create_dashscope_judge(
    log_dir: Path,
    *,
    model: str = DASHSCOPE_MODEL,
    max_output_tokens: int = MAX_JUDGE_OUTPUT_TOKENS,
    enable_thinking: bool = False,
    attempts: int = 2,
    retry_delays_seconds: Sequence[float] = (2,),
    role: str = "scoring",
    client: Any | None = None,
    **_ignored: Any,
) -> SemanticJudge:
    return DashScopeChatJudge(log_dir, model=model, max_output_tokens=max_output_tokens, enable_thinking=enable_thinking, attempts=attempts, retry_delays_seconds=retry_delays_seconds, role=role, client=client)


class JudgeRouter:
    """Route every evaluator purpose to a Qwen3.7-Plus client."""

    def __init__(self, config: Mapping[str, Any], log_root: Path, client_factory: Callable[..., Any] | None = None) -> None:
        self.config = dict(config)
        self.log_root = Path(log_root).resolve()
        self._clients: dict[str, SemanticJudge] = {}
        self._client_factory = client_factory or create_dashscope_judge

    def for_role(self, role: str) -> SemanticJudge:
        if role in self._clients:
            return self._clients[role]
        route = self.config.get("routes", {}).get(role)
        if not isinstance(route, Mapping):
            raise KeyError(f"No evaluator model route configured for role {role!r}")
        if route.get("provider") != DASHSCOPE_PROVIDER or route.get("model") != DASHSCOPE_MODEL or route.get("api_style") != DASHSCOPE_API_STYLE:
            raise ValueError("All model routes must use alibaba_dashscope/qwen3.7-plus/chat_completions")
        client = self._client_factory(
            self.log_root / role,
            model=DASHSCOPE_MODEL,
            max_output_tokens=int(route["max_output_tokens"]),
            enable_thinking=bool(route.get("enable_thinking", False)),
            attempts=int(self.config.get("attempts", 2)),
            retry_delays_seconds=self.config.get("retry_delays_seconds", [2]),
            role=role,
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
    "GenerationResult",
    "JudgeAttemptsExhausted",
    "JudgeRouter",
    "MAX_JUDGE_OUTPUT_TOKENS",
    "ModelRequest",
    "ModelResult",
    "RoutedSemanticJudge",
    "SemanticJudge",
    "create_dashscope_judge",
    "extract_python_code",
    "generate_stage_source",
    "parse_json_object",
    "redact_sensitive_text",
]
