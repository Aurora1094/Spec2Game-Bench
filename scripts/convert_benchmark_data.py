"""Convert the supplied DOCX/CSV benchmark source into the checked-in catalog.

The source files are intentionally external to the repository.  This script is
deterministic and records hashes of the source artifacts in
``benchmark/conversion_audit.json`` so the checked-in data can be regenerated
and audited without copying the private source bundle into the project.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from docx import Document

from checkpoint_corrections import apply_corrections, correction_metadata, load_corrections

SOURCE_FILES = {
    "snake": ("1_easy_Snake.docx", "snake_checkpoints.csv", "easy", [600, 800]),
    "dodge_blocks": ("2_easy_Dodge Blocks.docx", "dodge_blocks_checkpoints.csv", "easy", [600, 800]),
    "whack_a_mole": ("3_easy_Whack-a-Mole.docx", "whack_a_mole_checkpoints.csv", "easy", [600, 800]),
    "asteroids": ("4_easy_Asteroids.docx", "asteroids_checkpoints.csv", "easy", [600, 800]),
    "maze_runner": ("5_easy_Maze Runner.docx", "maze_runner_checkpoints.csv", "easy", [600, 800]),
    "space_invaders": ("6_medium_Space Invaders.docx", "space_invaders_checkpoints.csv", "medium", [800, 600]),
    "simple_platformer": ("7_medium_Simple Platformer.docx", "simple_platformer_checkpoints.csv", "medium", [800, 600]),
    "tetris": ("8_medium_tetris.docx", "tetris_checkpoints.csv", "medium", [600, 800]),
    "match3": ("9_medium_Match-3.docx", "match3_checkpoints.csv", "medium", [600, 800]),
    "simple_shop": ("10_medium_Simple Shop Management.docx", "simple_shop_checkpoints.csv", "medium", [600, 800]),
    "carrot_defense": ("11_hard_carrot Defense-like.docx", "carrot_defense_checkpoints.csv", "hard", [800, 600]),
    "farming_lite": ("12_hard_Farming-lite.docx", "farming_lite_checkpoints.csv", "hard", [800, 600]),
    "pipe_connection": ("13_hard_Pipe Connection Puzzle.docx", "pipe_connection_checkpoints.csv", "hard", [600, 800]),
    "arena_shooter": ("14_hard_Top-down Arena Shooter.docx", "arena_shooter_checkpoints.csv", "hard", [800, 700]),
    "mini_zelda": ("15_hard_Mini Zelda-like Room Adventure.docx", "mini_zelda_checkpoints.csv", "hard", [800, 700]),
}

EXPECTED_HEADERS = [
    "Checkpoint ID",
    "\u9879\u76ee",
    "\u6d4b\u8bd5\u76ee\u6807",
    "Initial State",
    "Trigger/Event",
    "Expected Transition",
    "\u68c0\u6d4b\u65b9\u5f0f",
    "0\u5206",
    "1\u5206",
    "2\u5206",
]
ID_RE = re.compile(r"^(?P<slug>[a-z0-9_]+)\.(?P<dimension>D2\.[1-5])\.(?P<number>\d+)$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _docx_text(path: Path) -> tuple[str, str]:
    document = Document(path)
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    body = "\n".join(paragraphs).replace("\r\n", "\n").replace("\r", "\n")
    name = ""
    for index, paragraph in enumerate(paragraphs):
        if paragraph.strip().lower() == "## game name" and index + 1 < len(paragraphs):
            name = paragraphs[index + 1].strip()
            break
    if not name:
        raise ValueError(f"could not find game name in {path.name}")
    return body.rstrip("\n") + "\n", name


def _read_checkpoints(path: Path, slug: str) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or list(rows[0].keys()) != EXPECTED_HEADERS:
        actual = list(rows[0].keys()) if rows else []
        raise ValueError(f"unexpected headers in {path.name}: {actual!r}")

    result: list[dict[str, Any]] = []
    for order, row in enumerate(rows, start=1):
        checkpoint_id = (row["Checkpoint ID"] or "").strip()
        match = ID_RE.fullmatch(checkpoint_id)
        if not match or match.group("slug") != slug:
            raise ValueError(f"invalid checkpoint id {checkpoint_id!r} in {path.name}")
        values = {
            "id": checkpoint_id,
            "game_slug": slug,
            "dimension": match.group("dimension"),
            "item": (row["\u9879\u76ee"] or "").strip(),
            "objective": (row["\u6d4b\u8bd5\u76ee\u6807"] or "").strip(),
            "initial_state": (row["Initial State"] or "").strip(),
            "trigger": (row["Trigger/Event"] or "").strip(),
            "expected_transition": (row["Expected Transition"] or "").strip(),
            "detection_method": (row["\u68c0\u6d4b\u65b9\u5f0f"] or "").strip(),
            "score_rubric": {
                "0": (row["0\u5206"] or "").strip(),
                "1": (row["1\u5206"] or "").strip(),
                "2": (row["2\u5206"] or "").strip(),
            },
            "source_order": order,
        }
        missing = [key for key, value in values.items() if key != "score_rubric" and not value]
        missing.extend(f"score_rubric.{key}" for key, value in values["score_rubric"].items() if not value)
        if missing:
            raise ValueError(f"empty fields for {checkpoint_id}: {missing}")
        result.append(values)
    return apply_corrections(result, slug)


def _write_text(path: Path, text: str) -> None:
    path.write_text(text.replace("\r\n", "\n").replace("\r", "\n"), encoding="utf-8", newline="\n")


def _write_json(path: Path, value: Any) -> None:
    _write_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def convert(source_dir: Path, project_dir: Path) -> dict[str, Any]:
    games_dir = project_dir / "benchmark" / "games"
    games_dir.mkdir(parents=True, exist_ok=True)
    audits: list[dict[str, Any]] = []
    catalog_games: list[dict[str, Any]] = []
    total = 0

    for slug, (docx_name, csv_name, difficulty, window_size) in SOURCE_FILES.items():
        docx_path = source_dir / docx_name
        csv_path = source_dir / csv_name
        if not docx_path.is_file() or not csv_path.is_file():
            raise FileNotFoundError(f"missing source pair for {slug}: {docx_name}, {csv_name}")
        body, game_name = _docx_text(docx_path)
        checkpoints = _read_checkpoints(csv_path, slug)
        game_dir = games_dir / slug
        game_dir.mkdir(parents=True, exist_ok=True)

        frontmatter = {
            "schema_version": 1,
            "game_name": game_name,
            "difficulty": difficulty,
            "params": {
                "window_size": window_size,
                "player_color": "#3D7EFF",
                "round_time_sec": 60,
            },
            "checkpoints": [
                {
                    "id": f"d2_{index}",
                    "desc": f"Dimension D2.{index} functional requirements",
                    "weight": 1,
                }
                for index in range(1, 6)
            ],
            "evaluation": {
                "protocol_version": 4,
                "seed": 17,
                "d2": {"checkpoint_jsonl": "checkpoints.jsonl"},
            },
        }
        # The closing frontmatter newline is the only separator before the
        # source body; this keeps the extracted DOCX paragraph stream byte-for-byte
        # stable after the metadata block.
        spec = "---\n" + json.dumps(frontmatter, ensure_ascii=False, indent=2, sort_keys=True) + "\n---\n" + body
        _write_text(game_dir / "spec.md", spec)
        with (game_dir / "checkpoints.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for checkpoint in checkpoints:
                handle.write(json.dumps(checkpoint, ensure_ascii=False, sort_keys=True) + "\n")

        source_audit = {
            "docx": {"file": docx_name, "sha256": sha256_file(docx_path)},
            "csv": {"file": csv_name, "sha256": sha256_file(csv_path)},
            "checkpoint_count": len(checkpoints),
            "spec_body_sha256": sha256_bytes(body.encode("utf-8")),
        }
        game_yaml = (
            f"schema_version: 1\nslug: {slug}\nname: {json.dumps(game_name, ensure_ascii=False)}\n"
            f"difficulty: {difficulty}\nspec: spec.md\ncheckpoints: checkpoints.jsonl\n"
            "variants: []\n"
            f"window_size: [{window_size[0]}, {window_size[1]}]\n"
            "source_audit:\n"
            f"  docx_sha256: {source_audit['docx']['sha256']}\n"
            f"  csv_sha256: {source_audit['csv']['sha256']}\n"
            f"  checkpoint_count: {len(checkpoints)}\n"
        )
        _write_text(game_dir / "game.yaml", game_yaml)

        dimension_counts: dict[str, int] = {}
        for checkpoint in checkpoints:
            dimension_counts[checkpoint["dimension"]] = dimension_counts.get(checkpoint["dimension"], 0) + 1
        audits.append({"slug": slug, **source_audit, "dimension_counts": dimension_counts})
        catalog_games.append(
            {
                "slug": slug,
                "name": game_name,
                "difficulty": difficulty,
                "path": f"games/{slug}",
                "window_size": window_size,
                "checkpoint_count": len(checkpoints),
                "dimension_counts": dimension_counts,
                "variants": [],
            }
        )
        total += len(checkpoints)

    totals: dict[str, int] = {}
    for audit in audits:
        for dimension, count in audit["dimension_counts"].items():
            totals[dimension] = totals.get(dimension, 0) + count
    catalog = {
        "schema_version": 1,
        "catalog_id": "spec2game-bench",
        "game_count": len(catalog_games),
        "checkpoint_count": total,
        "dimensions": totals,
        "games": catalog_games,
    }
    # JSON is valid YAML 1.2, so keeping the catalog in canonical JSON form
    # gives loaders and audits a stable byte representation while retaining the
    # requested ``catalog.yaml`` interface.
    _write_json(project_dir / "benchmark" / "catalog.yaml", catalog)
    _write_json(project_dir / "benchmark" / "checkpoint_corrections.json", load_corrections())
    _write_json(project_dir / "benchmark" / "conversion_audit.json", {
        "schema_version": 1,
        "checkpoint_corrections": correction_metadata(),
        "source_root_name": source_dir.name,
        "source_file_policy": "source files are external and are not copied into the repository",
        "games": audits,
        "totals": {"games": len(catalog_games), "checkpoints": total, "dimensions": totals},
    })
    return catalog


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    catalog = convert(args.source.resolve(), args.project.resolve())
    print(json.dumps({"games": catalog["game_count"], "checkpoints": catalog["checkpoint_count"], "dimensions": catalog["dimensions"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
