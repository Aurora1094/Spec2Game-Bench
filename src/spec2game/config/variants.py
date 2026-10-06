"""Offline validation of instance lineage and the fixed source layouts."""
from __future__ import annotations

from collections import Counter, deque
import hashlib
import json
from pathlib import Path
import re


def maze_layout(text: str) -> list[str]:
    matches = re.findall(r"(?m)^#{15}\n(?:[^\n]*\n){13}#{15}$", text)
    if len(matches) != 1:
        raise ValueError("expected one fixed 15-row maze")
    rows = matches[0].splitlines()
    if any(len(row) != 15 or set(row) - set("# PE") for row in rows):
        raise ValueError("maze spacing, width or cell alphabet is invalid")
    starts = [(y, x) for y, row in enumerate(rows) for x, cell in enumerate(row) if cell == "P"]
    exits = {(y, x) for y, row in enumerate(rows) for x, cell in enumerate(row) if cell == "E"}
    if len(starts) != 1 or not exits:
        raise ValueError("maze requires one start and at least one exit")
    seen, queue = set(starts), deque(starts)
    while queue:
        y, x = queue.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p = (y + dy, x + dx)
            if 0 <= p[0] < 15 and 0 <= p[1] < 15 and rows[p[0]][p[1]] != "#" and p not in seen:
                seen.add(p)
                queue.append(p)
    if not exits.issubset(seen):
        raise ValueError("at least one maze exit is unreachable")
    return rows


def pipe_layout(text: str) -> list[list[str]]:
    rows = re.findall(r"(?m)^Row ([0-5]): ([^\n]+)$", text)
    if [n for n, _ in rows] != list("012345"):
        raise ValueError("expected six ordered pipe rows")
    grid = [[cell.strip() for cell in row.split("|")] for _, row in rows]
    allowed = {"SRC-E", "SNK-W", "LEK", "BLK", "SH", "SV", "CNE", "CES", "CSW", "CWN", "TNES", "TESW", "TSWN", "TWNE"}
    if any(len(row) != 6 or set(row) - allowed for row in grid):
        raise ValueError("invalid pipe map dimensions or cell types")
    actual = Counter(cell for row in grid for cell in row)
    if actual["SRC-E"] != 1 or actual["SNK-W"] != 2 or actual["LEK"] != 1:
        raise ValueError("pipe map requires one source, two sinks and one leak")
    for label, cell in (("Source", "SRC-E"), ("Sink 1", "SNK-W"), ("Sink 2", "SNK-W"), ("Leak", "LEK")):
        coordinates = re.search(rf"(?m)^- {label}: `\((\d),(\d)\)`", text)
        if coordinates is None or grid[int(coordinates[1])][int(coordinates[2])] != cell:
            raise ValueError(f"{label} coordinate disagrees with the pipe grid")
    return grid


def carrot_paths(text: str) -> list[list[tuple[int, int]]]:
    paths = []
    for block in re.findall(r"```(?:text)?\n(.*?)\n```", text, re.S):
        if not re.fullmatch(r"[\s(),\d↑↓→←]+", block):
            continue
        points = [tuple(map(int, pair)) for pair in re.findall(r"\((\d+),\s*(\d+)\)", block)]
        if len(points) < 2:
            continue
        if len(points) != len(set(points)) or any(not (0 <= x < 12 and 0 <= y < 8) for x, y in points):
            raise ValueError("carrot path repeats or leaves the 12x8 grid")
        if any(abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1 for a, b in zip(points, points[1:])):
            raise ValueError("carrot path has a nonadjacent step")
        paths.append(points)
    if not paths or not any(path[0][0] == 0 and path[-1][0] == 11 for path in paths):
        raise ValueError("no complete entrance-to-carrot path")
    return paths


def combat_layout(text: str, family: str) -> None:
    rectangle_pattern = r"(?m)^\| (?:Wall )?([A-E]\d*) \| `\((\d+),\s*(\d+)\)` \| `(\d+) × (\d+) px` \|"
    rectangles = [(name, *map(int, values)) for name, *values in re.findall(rectangle_pattern, text)]
    if not rectangles:
        raise ValueError("no fixed combat obstacle rectangles")
    bounds = (0, 80, 800, 620) if family == "arena_shooter" else (50, 100, 750, 600)
    for name, x, y, width, height in rectangles:
        if width <= 0 or height <= 0 or not (bounds[0] <= x < x + width <= bounds[2] and bounds[1] <= y < y + height <= bounds[3]):
            raise ValueError(f"obstacle {name} leaves the combat area")

    def check_point(x, y, obstacles, radius=18):
        if not (bounds[0] + radius <= x <= bounds[2] - radius and bounds[1] + radius <= y <= bounds[3] - radius):
            raise ValueError("spawn lies outside combat bounds")
        for name, rx, ry, width, height in obstacles:
            nearest_x, nearest_y = min(max(x, rx), rx + width), min(max(y, ry), ry + height)
            if (x - nearest_x) ** 2 + (y - nearest_y) ** 2 < radius ** 2:
                raise ValueError(f"spawn overlaps obstacle {name}")

    if family == "arena_shooter":
        if len(rectangles) != 3:
            raise ValueError("arena requires three walls")
        check_point(400, 560, rectangles)
        entries = re.findall(r"(?m)^- ((?:Chaser|Shooter) \d+): `\((\d+),\s*(\d+)\)`", text)
        enemies = {}
        for name, x, y in entries:
            if name in enemies and enemies[name] != (x, y):
                raise ValueError(f"inconsistent initial center for {name}")
            enemies[name] = (x, y)
        if len(enemies) != 6:
            raise ValueError("arena requires six initial enemy centers")
        for x, y in enemies.values():
            check_point(int(x), int(y), rectangles, 16)
    else:
        rooms = re.findall(r"(?ms)^## 3\.[3-7] Room ([A-E])\n(.*?)(?=^## |\Z)", text)
        if [room for room, _ in rooms] != list("ABCDE"):
            raise ValueError("Zelda room layout is incomplete")
        for room, section in rooms:
            obstacles = [rect for rect in rectangles if rect[0].startswith(room)]
            # Table coordinates describe obstacles, not spawn points.
            prose = "\n".join(line for line in section.splitlines() if not line.startswith("|"))
            points = re.findall(r"`\((\d+),\s*(\d+)\)`", prose)
            for x, y in points:
                check_point(int(x), int(y), obstacles)


def variant_data_errors(catalog: dict, benchmark: Path) -> list[str]:
    errors = []
    entries = catalog.get("variant_instances", [])
    ids = [row.get("slug") for row in entries]
    expected = [f"{base['slug']}_var{n:02d}" for base in catalog["games"] for n in range(1, 10)]
    if ids != expected or catalog.get("instance_count") != 150:
        errors.append("Full catalog must contain nine ordered variants per canonical family")
    base_counts = Counter()
    for base in catalog["games"]:
        family = base["slug"]
        if base.get("variants") != [f"{family}_var{n:02d}" for n in range(1, 10)]:
            errors.append(f"{family}: variant membership is invalid")
        rows = _rows(benchmark / base["path"] / "checkpoints.jsonl")
        base_counts.update(row["dimension"] for row in rows)
    if dict(base_counts) != catalog["dimensions"] or sum(base_counts.values()) != 537:
        errors.append("canonical checkpoint counts changed")
    audit = json.loads((benchmark / "variant_source_audit.json").read_text(encoding="utf-8"))
    source_map = {row["instance_id"]: row for row in audit["instances"]}
    if set(source_map) != set(expected):
        errors.append("source audit does not cover all 135 variants")
    for entry in entries:
        slug = entry["slug"]
        try:
            root = benchmark / entry["path"]
            family, variant = entry["family_slug"], entry["variant_id"]
            if slug != f"{family}_{variant}":
                raise ValueError("instance identity differs from family/variant")
            rows = _rows(root / "checkpoints.jsonl")
            original = benchmark / "games" / family / "checkpoints.jsonl"
            base_ids = {row["id"] for row in _rows(original)}
            variation = json.loads((root / "variation.json").read_text(encoding="utf-8"))
            if variation["base_checkpoints_sha256"] != _sha(original) or variation["checkpoints_sha256"] != _sha(root / "checkpoints.jsonl"):
                raise ValueError("checkpoint lineage hash changed")
            if source_map[slug]["spec_sha256"] != _sha(root / "spec.md"):
                raise ValueError("specification differs from the audited conversion")
            if any(row.get("base_checkpoint_id") not in base_ids | {None} for row in rows):
                raise ValueError("unknown parent checkpoint")
            if {row.get("base_checkpoint_id") for row in rows if row.get("base_checkpoint_id")} != base_ids:
                raise ValueError("each original checkpoint must retain its correspondence")
            local_ids = [row["id"] for row in rows]
            if local_ids != sorted(set(local_ids)):
                raise ValueError("checkpoint order or uniqueness is invalid")
            counts = Counter(row["dimension"] for row in rows)
            if set(counts) != {f"D2.{n}" for n in range(1, 6)} or dict(counts) != entry["dimension_counts"]:
                raise ValueError("all five dimensions must match catalog counts")
            changed = variation["changed_checkpoint_ids"]
            if not changed or not set(changed).issubset(local_ids):
                raise ValueError("changed rules need corresponding checkpoints")
            text = (root / "spec.md").read_text(encoding="utf-8")
            if family == "maze_runner":
                layout = maze_layout(text)
                if variant in {"var01", "var02", "var06"} and layout != maze_layout((benchmark / "games/maze_runner/spec.md").read_text(encoding="utf-8")):
                    raise ValueError("unchanged map does not match canonical map")
            if family == "pipe_connection":
                pipe_layout(text)
            if family == "carrot_defense":
                carrot_paths(text)
            if family in {"arena_shooter", "mini_zelda"}:
                combat_layout(text, family)
        except (OSError, ValueError, KeyError, IndexError) as exc:
            errors.append(f"{slug}: {exc}")
    return errors


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
