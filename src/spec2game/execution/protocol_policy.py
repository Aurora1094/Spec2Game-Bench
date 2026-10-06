"""Canonical runtime protocol identity for benchmark evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from spec2game.d4.contracts import RUNTIME_QUESTION_POLICY
from spec2game.d4.questions import (
    QUESTION_PACK_DESIGN_VERSION,
    QUESTION_PACK_SCHEMA_VERSION,
    QUESTION_REVIEW_POLICY,
)


ROOT = Path(__file__).resolve().parents[3]
RUNTIME_PROTOCOL_DESCRIPTOR_SCHEMA_VERSION = 3

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _relative_hashes(paths: Iterable[Path]) -> dict[str, str]:
    unique = sorted({path.resolve() for path in paths})
    result: dict[str, str] = {}
    for path in unique:
        if not path.is_file():
            raise FileNotFoundError(f"Required protocol file is missing: {path}")
        result[path.relative_to(ROOT).as_posix()] = sha256_file(path)
    return result


def _implementation_paths() -> list[Path]:
    return sorted((ROOT / "src" / "spec2game").rglob("*.py"))


def _prompt_asset_paths() -> list[Path]:
    paths = list((ROOT / "src" / "spec2game" / "generation" / "templates").glob("*.md"))
    paths.extend((ROOT / "benchmark" / "games").rglob("spec.md"))
    paths.extend((ROOT / "benchmark" / "games").rglob("checkpoints.jsonl"))
    paths.extend((ROOT / "benchmark" / "schemas").glob("*.json"))
    return paths


def runtime_protocol_descriptor() -> dict[str, Any]:
    """Return the exact evaluator, scoring, and Prompt implementation identity."""

    implementation_files = _relative_hashes(_implementation_paths())
    prompt_asset_files = _relative_hashes(_prompt_asset_paths())
    payload: dict[str, Any] = {
        "schema_version": RUNTIME_PROTOCOL_DESCRIPTOR_SCHEMA_VERSION,
        "d4_question_pack": {
            "schema_version": QUESTION_PACK_SCHEMA_VERSION,
            "design_version": QUESTION_PACK_DESIGN_VERSION,
            "review_policy": QUESTION_REVIEW_POLICY,
            "runtime_question_policy": RUNTIME_QUESTION_POLICY,
        },
        "implementation_files": implementation_files,
        "implementation_sha256": sha256_json(implementation_files),
        "prompt_asset_files": prompt_asset_files,
        "prompt_assets_sha256": sha256_json(prompt_asset_files),
    }
    return {
        **payload,
        "descriptor_sha256": sha256_json(payload),
    }


