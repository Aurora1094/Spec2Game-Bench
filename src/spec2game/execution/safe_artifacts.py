"""Artifact I/O and secret-redaction helpers."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable


SECRET_ENV_NAMES = (
    "DASHSCOPE_API_KEY",
    "OPENROUTER_API_KEY",
)
SENSITIVE_KEY_RE = re.compile(
    r"^(?:authorization|api[_-]?key|access[_-]?key(?:_id)?|secret(?:_access)?_?key|"
    r"bearer(?:_token)?|session_token|credential(?:s)?)$",
    re.IGNORECASE,
)
SENSITIVE_ARTIFACT_PATTERNS = (
    re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(
        rb"\bBearer\s+(?!\[REDACTED\])[A-Za-z0-9._~+/=-]{20,}",
        re.IGNORECASE,
    ),
    re.compile(
        rb"""["']?authorization["']?\s*:\s*["']?"""
        rb"""(?!\[REDACTED\])(?:bearer\s+)?[A-Za-z0-9._~+/=-]{16,}""",
        re.IGNORECASE,
    ),
)


def known_secret_values(extra: Iterable[str] = ()) -> list[str]:
    values = [os.getenv(name, "") for name in SECRET_ENV_NAMES]
    values.extend(str(value) for value in extra)
    return sorted({value for value in values if value}, key=len, reverse=True)


def redact_text(text: str, extra_secrets: Iterable[str] = ()) -> str:
    redacted = str(text)
    for value in known_secret_values(extra_secrets):
        redacted = redacted.replace(value, "[REDACTED]")
    redacted = re.sub(
        r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;\]}]+",
        r"\1[REDACTED]",
        redacted,
    )
    return redacted


def sanitize(value: Any, extra_secrets: Iterable[str] = ()) -> Any:
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if SENSITIVE_KEY_RE.search(str(key)):
                clean[str(key)] = "[REDACTED]"
            else:
                clean[str(key)] = sanitize(item, extra_secrets)
        return clean
    if isinstance(value, list):
        return [sanitize(item, extra_secrets) for item in value]
    if isinstance(value, tuple):
        return [sanitize(item, extra_secrets) for item in value]
    if isinstance(value, str):
        return redact_text(value, extra_secrets)
    return value


def write_json(path: str | Path, value: Any, *, extra_secrets: Iterable[str] = ()) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            sanitize(value, extra_secrets),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )


def scan_for_secret_leaks(root: str | Path, *, extra_secrets: Iterable[str] = ()) -> list[str]:
    """Return files containing exact secrets or unredacted credential patterns."""
    base = Path(root).resolve()
    secrets = known_secret_values(extra_secrets)
    if not base.exists():
        return []
    hits: list[str] = []
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        exact_match = any(secret.encode("utf-8") in data for secret in secrets)
        pattern_match = any(
            pattern.search(data) is not None
            for pattern in SENSITIVE_ARTIFACT_PATTERNS
        )
        if exact_match or pattern_match:
            hits.append(str(path.relative_to(base)))
    return sorted(hits)
