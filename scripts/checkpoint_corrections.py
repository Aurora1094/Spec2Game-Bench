"""Apply the reviewed base-checkpoint errata during source conversion."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path


CORRECTIONS_PATH = Path(__file__).resolve().parents[1] / "benchmark/checkpoint_corrections.json"


def load_corrections() -> dict:
    return json.loads(CORRECTIONS_PATH.read_text(encoding="utf-8"))


def correction_metadata() -> dict:
    return {"file": "checkpoint_corrections.json", "revision": load_corrections()["revision"]}


def apply_corrections(rows: list[dict], slug: str) -> list[dict]:
    corrected = deepcopy(rows)
    by_id = {row["id"]: row for row in corrected}
    for entry in load_corrections()["corrections"]:
        checkpoint_id = entry["checkpoint_id"]
        if not checkpoint_id.startswith(slug + "."):
            continue
        row = by_id[checkpoint_id]
        accepted = {
            entry["source_expected_transition"],
            entry["before"]["expected_transition"],
            entry["after"]["expected_transition"],
        }
        if row["expected_transition"] not in accepted:
            raise ValueError(f"{checkpoint_id}: source rule changed; review its recorded correction")
        row.update(deepcopy(entry["after"]))
    return corrected
