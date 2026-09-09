"""Deterministic, leak-resistant staged-project prompt construction."""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Literal, Mapping

import yaml

from code2play.config.project import PROJECT_ROOT, load_catalog
from code2play.execution.candidate_project import CandidateProject, STAGE_TARGETS


ROOT_DIR = PROJECT_ROOT
PROMPTS_DIR = PROJECT_ROOT / "benchmark"
STAGED_PROMPTS_DIR = Path(__file__).resolve().parent / "templates"
COMMON_TEMPLATE = STAGED_PROMPTS_DIR / "common_contract.md"
STAGE_TEMPLATES = {stage: STAGED_PROMPTS_DIR / f"{stage}.md" for stage in STAGE_TARGETS}
SPECS_DIR = PROJECT_ROOT / "benchmark" / "games"

_catalog = load_catalog()
GAME_SPECS: "OrderedDict[str, Path]" = OrderedDict(
    (str(item["slug"]), PROJECT_ROOT / "benchmark" / str(item["path"]) / "spec.md")
    for item in _catalog["games"]
)
SUPPORTED_GAMES = tuple(GAME_SPECS)
GAME_ALIASES: dict[str, str] = {}
DIMENSION_ORDER = ("D2.1", "D2.2", "D2.3", "D2.4", "D2.5")
VALID_D2_DIMENSIONS = set(DIMENSION_ORDER)
VALID_DIFFICULTIES = {"easy", "medium", "hard"}

PLACEHOLDER_PATTERN = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
CHECKPOINT_ID_PATTERN = re.compile(
    r"^(?P<prefix>[a-z][a-z0-9_]*)\.D2\.(?P<dimension>[1-5])\.(?P<number>\d{2})$"
)
LOCAL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
MODEL_VISIBLE_DIMENSION_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])D[1-4](?:[._][1-9][0-9]*)?(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
# Section 8 is a legacy/empty checkpoint placeholder in the source specs.  It
# must be recognized as its own section so it cannot be absorbed into section
# 7 and accidentally copied into model-facing prompts.
SPEC_SECTION_PATTERN = re.compile(r"(?m)^#\s+([1-8])(?:\.\s*|\s+)")
SPEC_HEADING_NUMBER_PATTERN = re.compile(r"(?m)^(#{1,6})\s+\d+(?:\.\d+)*\.?\s+")
STAGE_SPEC_SECTIONS = {
    "state": (1, 3, 6),
    "game": (1, 3, 4, 5, 6, 7),
    "rendering": (1, 2, 7),
    "main": (4,),
}
DEFAULT_STAGE_BUDGETS = {"state": 3000, "game": 7000, "rendering": 4000, "main": 2000}
FORBIDDEN_CANDIDATE_LITERALS = (
    "Checkpoint ID",
    "Detection Method",
    "score_rubric",
    "correct_choice",
    "Judge Prompt",
    "judge prompt",
)


@dataclass(frozen=True)
class StagePrompt:
    stage: str
    target_file: str
    text: str
    sha256: str
    generation_contract_sha256: str
    injected_dependency_hashes: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PromptBuildError(ValueError):
    pass


def canonical_game_slug(game_slug: str) -> str:
    slug = str(game_slug).strip().lower().replace("-", "_").replace(" ", "_")
    slug = GAME_ALIASES.get(slug, slug)
    if slug not in GAME_SPECS:
        raise PromptBuildError(f"unsupported game {game_slug!r}; expected one of {', '.join(SUPPORTED_GAMES)}")
    return slug


def get_spec_path(game_slug: str) -> Path:
    return GAME_SPECS[canonical_game_slug(game_slug)]


def split_public_spec_sections(spec_body: str) -> dict[int, str]:
    matches = list(SPEC_SECTION_PATTERN.finditer(spec_body))
    numbers = [int(match.group(1)) for match in matches]
    if numbers not in (list(range(1, 8)), list(range(1, 9))):
        raise PromptBuildError(
            f"public game specification must contain ordered sections 1-7 (with optional 8), got {numbers}"
        )
    result: dict[int, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(spec_body)
        result[int(match.group(1))] = spec_body[match.start() : end].strip()
    return result


def _stage_budget_map(generation_config: Mapping[str, Any] | None) -> dict[str, int]:
    if generation_config is None:
        return dict(DEFAULT_STAGE_BUDGETS)
    stages = generation_config.get("stages")
    if not isinstance(stages, list):
        raise PromptBuildError("generation.stages must be a list")
    result: dict[str, int] = {}
    for raw in stages:
        if not isinstance(raw, Mapping):
            raise PromptBuildError("each generation stage must be a mapping")
        stage = str(raw.get("id", ""))
        value = raw.get("max_output_tokens")
        if stage not in STAGE_TARGETS or stage in result or not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise PromptBuildError(f"invalid generation stage or budget: {raw!r}")
        result[stage] = value
    if tuple(result) != tuple(STAGE_TARGETS):
        raise PromptBuildError("generation stages must be state, game, rendering, main")
    return result


def generation_contract_sha256(game_slug: str, generation_config: Mapping[str, Any] | None = None) -> str:
    slug = canonical_game_slug(game_slug)
    spec = load_spec(GAME_SPECS[slug])
    rows = load_evaluator_checkpoints(spec)
    payload = {
        "schema_version": 1,
        "protocol": "staged_project_v1",
        "game_slug": slug,
        "common_template": _read_required_text(COMMON_TEMPLATE),
        "stage_templates": {stage: _read_required_text(path) for stage, path in STAGE_TEMPLATES.items()},
        "public_spec": spec["body"],
        "public_d2_requirements": _group_rendered_requirements(rows),
        "stage_order": list(STAGE_TARGETS),
        "stage_targets": STAGE_TARGETS,
        "stage_budgets": _stage_budget_map(generation_config),
        "checkpoint_jsonl_sha256": _checkpoint_jsonl_sha256(spec),
    }
    return _sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _read_locked_source(project: CandidateProject, filename: str) -> tuple[str, str]:
    path = project.path(filename)
    if not path.is_file() or path.is_symlink():
        raise PromptBuildError(f"locked dependency is missing or unsafe: {path}")
    data = path.read_bytes()
    return data.decode("utf-8-sig", errors="replace").lstrip("\ufeff"), _sha256_bytes(data)


def _api_summary_text(project: CandidateProject) -> str:
    summary = project.public_api_summary()
    return json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)


def build_stage_prompt(
    *,
    game_slug: str,
    stage: Literal["state", "game", "rendering", "main"],
    locked_project: CandidateProject | None = None,
    generation_config: Mapping[str, Any] | None = None,
) -> StagePrompt:
    if stage not in STAGE_TARGETS:
        raise PromptBuildError(f"unknown staged prompt {stage!r}")
    slug = canonical_game_slug(game_slug)
    spec_path = GAME_SPECS[slug]
    spec = load_spec(spec_path)
    rows = load_evaluator_checkpoints(spec)
    sections = split_public_spec_sections(spec["body"])
    grouped = _group_rendered_requirements(rows)
    width, height = spec["params"]["window_size"]
    target = STAGE_TARGETS[stage]
    common = _render_template(
        _strip_maintainer_comments(_read_required_text(COMMON_TEMPLATE)),
        {"game_name": str(spec["game_name"]), "target_file": target},
        COMMON_TEMPLATE,
    )
    values: dict[str, str] = {
        "window_size": f"{width}x{height}",
        "state_spec_sections": _join_sections(sections, STAGE_SPEC_SECTIONS["state"]),
        "game_spec_sections": _join_sections(sections, STAGE_SPEC_SECTIONS["game"]),
        "rendering_spec_sections": _join_sections(sections, STAGE_SPEC_SECTIONS["rendering"]),
        "interaction_spec_section": _join_sections(sections, STAGE_SPEC_SECTIONS["main"]),
        **grouped,
    }
    dependency_hashes: dict[str, str] = {}
    if stage in {"game", "rendering", "main"} and locked_project is None:
        raise PromptBuildError(f"{stage} prompt requires a locked candidate project")
    if stage in {"game", "rendering"}:
        assert locked_project is not None
        source, digest = _read_locked_source(locked_project, "state.py")
        values.update({"state_source": source or "# Locked state.py contains no source.", "state_sha256": digest})
        dependency_hashes["state.py"] = digest
    if stage == "main":
        assert locked_project is not None
        for filename in ("state.py", "game.py", "rendering.py"):
            _, digest = _read_locked_source(locked_project, filename)
            dependency_hashes[filename] = digest
        values["project_api_summary"] = _api_summary_text(locked_project)
    stage_text = _render_template(
        _strip_maintainer_comments(_read_required_text(STAGE_TEMPLATES[stage])), values, STAGE_TEMPLATES[stage]
    )
    text = common.rstrip() + "\n\n" + stage_text.rstrip() + "\n"
    _validate_stage_prompt(text, stage=stage, rows=rows, injected_sources=(values.get("state_source", ""),), spec_path=spec_path)
    return StagePrompt(
        stage=stage,
        target_file=target,
        text=text,
        sha256=_sha256_text(text),
        generation_contract_sha256=generation_contract_sha256(slug, generation_config),
        injected_dependency_hashes=dependency_hashes,
    )


def render_prompt_contract(
    game_slug: str,
    output_dir: str | Path | None = None,
    generation_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    slug = canonical_game_slug(game_slug)
    spec_path = GAME_SPECS[slug]
    spec_text = _read_required_text(spec_path)
    _metadata, public_spec = _split_frontmatter(spec_text, spec_path)
    spec = load_spec(spec_path)
    rows = load_evaluator_checkpoints(spec)
    state_prompt = build_stage_prompt(game_slug=slug, stage="state", generation_config=generation_config)
    checkpoint_path = _checkpoint_jsonl_path(spec)
    result: dict[str, Any] = {
        "game_slug": slug,
        "generation_contract_sha256": state_prompt.generation_contract_sha256,
        "state_prompt_sha256": state_prompt.sha256,
        "state_prompt": state_prompt.text,
        "public_spec": public_spec,
        "spec_sha256": _sha256_text(spec_text),
        "checkpoint_jsonl_sha256": _sha256_bytes(checkpoint_path.read_bytes()),
        "checkpoint_jsonl_path": str(checkpoint_path),
        "checkpoint_count": len(rows),
        "dimension_counts": {dimension: sum(row["dimension"] == dimension for row in rows) for dimension in DIMENSION_ORDER},
        "stage_budgets": _stage_budget_map(generation_config),
    }
    if output_dir is not None:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "state_final_prompt.md").write_text(state_prompt.text, encoding="utf-8", newline="\n")
        (out / "game_spec.md").write_text(spec_text, encoding="utf-8", newline="\n")
        (out / "common_contract.md").write_text(_read_required_text(COMMON_TEMPLATE), encoding="utf-8", newline="\n")
        templates_dir = out / "stage_templates"
        templates_dir.mkdir(parents=True, exist_ok=True)
        for stage, path in STAGE_TEMPLATES.items():
            (templates_dir / f"{stage}.md").write_text(_read_required_text(path), encoding="utf-8", newline="\n")
        (out / "generation_contract_manifest.json").write_text(
            json.dumps({key: value for key, value in result.items() if key != "state_prompt"}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        result["output_dir"] = str(out.resolve())
    return result


def render_all_prompt_contracts(output_dir: str | Path, generation_config: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    return [render_prompt_contract(slug, Path(output_dir) / slug, generation_config) for slug in SUPPORTED_GAMES]


def validate_all_prompts(generation_config: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    checkpoint_paths: set[Path] = set()
    for slug in SUPPORTED_GAMES:
        rendered = render_prompt_contract(slug, generation_config=generation_config)
        checkpoint_paths.add(Path(rendered["checkpoint_jsonl_path"]).resolve())
        reports.append({key: rendered[key] for key in ("game_slug", "generation_contract_sha256", "state_prompt_sha256", "checkpoint_count", "dimension_counts", "stage_budgets")})
    if len(checkpoint_paths) != len(SUPPORTED_GAMES):
        raise PromptBuildError("each official game must reference one unique checkpoint JSONL")
    if sum(item["checkpoint_count"] for item in reports) != 537:
        raise PromptBuildError("the staged prompt contract must cover exactly 537 D2 rows")
    return reports


def load_spec(spec_path: str | Path) -> dict[str, Any]:
    path = Path(spec_path)
    text = _read_required_text(path)
    meta, body = _split_frontmatter(text, path)
    if not isinstance(meta, dict):
        raise PromptBuildError(f"{path} frontmatter must be a mapping")
    spec = dict(meta)
    spec["body"] = body.strip()
    spec["_spec_path"] = str(path.resolve())
    _validate_spec(spec, path)
    return spec


def load_checkpoints(spec_path_or_difficulty: str | Path, game: str | Path | None = None) -> list[dict[str, Any]]:
    spec_path = _resolve_spec_path(spec_path_or_difficulty, game)
    return [dict(item) for item in load_spec(spec_path)["checkpoints"]]


def load_evaluator_checkpoints(spec_or_path: Mapping[str, Any] | str | Path) -> list[dict[str, Any]]:
    spec = dict(spec_or_path) if isinstance(spec_or_path, Mapping) else load_spec(spec_or_path)
    evaluation = _require_mapping(spec.get("evaluation"), "evaluation")
    d2 = _require_mapping(evaluation.get("d2"), "evaluation.d2")
    rows = _require_nonempty_list(d2.get("checkpoints"), "evaluation.d2.checkpoints")
    return [dict(row) for row in rows]


def _resolve_spec_path(spec_path_or_difficulty: str | Path, game: str | Path | None) -> Path:
    if game is None:
        return Path(spec_path_or_difficulty)
    slug = canonical_game_slug(str(game))
    return GAME_SPECS[slug]


def _read_required_text(path: Path) -> str:
    if not path.is_file():
        raise PromptBuildError(f"missing required file: {path}")
    return path.read_text(encoding="utf-8-sig")


def _strip_maintainer_comments(text: str) -> str:
    return HTML_COMMENT_PATTERN.sub("", text).lstrip()


def _split_frontmatter(text: str, path: Path) -> tuple[dict[str, Any], str]:
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        raise PromptBuildError(f"{path} must begin with YAML frontmatter")
    try:
        end = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise PromptBuildError(f"{path} frontmatter is missing its closing ---") from exc
    try:
        meta = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError as exc:
        raise PromptBuildError(f"{path} has invalid YAML frontmatter: {exc}") from exc
    return meta, "\n".join(lines[end + 1 :])


def _validate_spec(spec: dict[str, Any], path: Path) -> None:
    _nonempty_string(spec.get("game_name"), f"{path} game_name")
    if spec.get("difficulty") not in VALID_DIFFICULTIES:
        raise PromptBuildError(f"{path} difficulty must be easy, medium, or hard")
    params = _require_mapping(spec.get("params"), f"{path} params")
    size = params.get("window_size")
    if not isinstance(size, list) or len(size) != 2:
        raise PromptBuildError(f"{path} params.window_size must be [W, H]")
    for value in size:
        _positive_int(value, f"{path} params.window_size")
    color = params.get("player_color")
    if not isinstance(color, str) or COLOR_PATTERN.fullmatch(color) is None:
        raise PromptBuildError(f"{path} params.player_color must be #RRGGBB")
    _positive_int(params.get("round_time_sec"), f"{path} params.round_time_sec")
    _validate_public_checkpoints(spec.get("checkpoints"), path)
    if not isinstance(spec.get("body"), str) or not spec["body"].strip():
        raise PromptBuildError(f"{path} public spec body must not be empty")
    _validate_evaluation(spec.get("evaluation"), path)


def _validate_public_checkpoints(value: Any, path: Path) -> None:
    rows = _require_nonempty_list(value, f"{path} checkpoints")
    seen: set[str] = set()
    for index, raw in enumerate(rows, 1):
        row = _require_mapping(raw, f"{path} checkpoint #{index}")
        item_id = _nonempty_string(row.get("id"), f"{path} checkpoint #{index}.id")
        if LOCAL_ID_PATTERN.fullmatch(item_id) is None or item_id in seen:
            raise PromptBuildError(f"{path} invalid or duplicated public checkpoint id: {item_id}")
        seen.add(item_id)
        _nonempty_string(row.get("desc"), f"{path} checkpoint {item_id}.desc")
        _positive_int(row.get("weight", 1), f"{path} checkpoint {item_id}.weight")


def _validate_evaluation(value: Any, path: Path) -> None:
    evaluation = _require_mapping(value, f"{path} evaluation")
    if evaluation.get("protocol_version") != 4:
        raise PromptBuildError(f"{path} evaluation.protocol_version must equal 4")
    _positive_int(evaluation.get("seed", 17), f"{path} evaluation.seed")
    d2 = _require_mapping(evaluation.get("d2"), f"{path} evaluation.d2")
    if any(field in d2 for field in ("checkpoint_plan", "state_contract", "checkpoint_csv")):
        raise PromptBuildError(f"{path} may not contain legacy D2 hooks or CSV sources")
    reference = _nonempty_string(d2.get("checkpoint_jsonl"), f"{path} evaluation.d2.checkpoint_jsonl")
    d2["checkpoints"] = _load_d2_checkpoint_jsonl(reference, path)
    if "d4" in evaluation:
        raise PromptBuildError(f"{path} may not embed evaluation.d4; use a round contract")


def _load_d2_checkpoint_jsonl(relative_path: str, spec_path: Path) -> list[dict[str, Any]]:
    path = (spec_path.parent / relative_path).resolve()
    try:
        path.relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise PromptBuildError(f"{spec_path} checkpoint JSONL must remain inside the project") from exc
    if not path.is_file() or path.suffix.lower() != ".jsonl":
        raise PromptBuildError(f"{spec_path} checkpoint JSONL is missing: {path}")
    raw_rows: list[dict[str, Any]] = []
    for source_row, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PromptBuildError(f"{path}:{source_row} is not valid JSON") from exc
        if not isinstance(raw, dict):
            raise PromptBuildError(f"{path}:{source_row} must be a JSON object")
        raw_rows.append(raw)
    if not raw_rows:
        raise PromptBuildError(f"{path} contains no checkpoint rows")

    materialized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    dimension_numbers: dict[str, list[int]] = defaultdict(list)
    dimension_sequence: list[int] = []
    for source_row, raw in enumerate(raw_rows, 1):
        required = ("id", "game_slug", "dimension", "item", "objective", "initial_state", "trigger", "expected_transition", "detection_method", "score_rubric")
        for field_name in required:
            if field_name == "score_rubric":
                rubric = raw.get(field_name)
                if not isinstance(rubric, Mapping) or any(not str(rubric.get(str(score), "")).strip() for score in range(3)):
                    raise PromptBuildError(f"{path}:{source_row} score_rubric must contain non-empty 0/1/2 values")
            else:
                _nonempty_string(raw.get(field_name), f"{path}:{source_row} {field_name}")
        checkpoint_id = str(raw["id"]).strip()
        match = CHECKPOINT_ID_PATTERN.fullmatch(checkpoint_id)
        if match is None or checkpoint_id in seen_ids or match.group("prefix") != spec_path.parent.name:
            raise PromptBuildError(f"{path}:{source_row} invalid/duplicate ID {checkpoint_id!r}")
        dimension = f"D2.{match.group('dimension')}"
        if str(raw["dimension"]) != dimension:
            raise PromptBuildError(f"{path}:{source_row} dimension disagrees with id")
        seen_ids.add(checkpoint_id)
        number = int(match.group("number"))
        dimension_numbers[dimension].append(number)
        dimension_sequence.append(int(match.group("dimension")))
        trigger = str(raw["trigger"]).strip()
        static = trigger.upper().startswith("N/A")
        if static != (dimension == "D2.1"):
            raise PromptBuildError(f"{path}:{source_row} only D2.1 may be static")
        materialized.append({
            "id": checkpoint_id,
            "dimension": dimension,
            "kind": "static" if static else "dynamic",
            "setup": checkpoint_id,
            "action": None if static else checkpoint_id,
            "dt": 0.0,
            "game_slug": spec_path.parent.name,
            "item": str(raw["item"]).strip(),
            "objective": str(raw["objective"]).strip(),
            "initial_state": str(raw["initial_state"]).strip(),
            "trigger": trigger,
            "expected_transition": str(raw["expected_transition"]).strip(),
            "detection_method": str(raw["detection_method"]).strip(),
            "score_rubric": {str(score): str(raw["score_rubric"][str(score)]).strip() for score in range(3)},
            "source_jsonl": str(path),
            "source_row": source_row,
        })
    if dimension_sequence != sorted(dimension_sequence):
        raise PromptBuildError(f"{path} rows must be grouped in D2.1 through D2.5 order")
    if set(dimension_numbers) != VALID_D2_DIMENSIONS:
        raise PromptBuildError(f"{path} is missing dimensions")
    for dimension, numbers in dimension_numbers.items():
        if numbers != list(range(1, len(numbers) + 1)):
            raise PromptBuildError(f"{path} {dimension} row numbers must be contiguous from 01")
    return materialized


def _checkpoint_jsonl_path(spec: Mapping[str, Any]) -> Path:
    evaluation = _require_mapping(spec.get("evaluation"), "evaluation")
    d2 = _require_mapping(evaluation.get("d2"), "evaluation.d2")
    reference = _nonempty_string(d2.get("checkpoint_jsonl"), "evaluation.d2.checkpoint_jsonl")
    return (Path(str(spec["_spec_path"])).parent / reference).resolve()


def _checkpoint_jsonl_sha256(spec: Mapping[str, Any]) -> str:
    return _sha256_bytes(_checkpoint_jsonl_path(spec).read_bytes())


def _group_rendered_requirements(rows: list[dict[str, Any]]) -> dict[str, str]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["dimension"]].append(row)
    return {
        dimension.replace(".", "_").lower() + "_requirements": "\n".join(
            _render_behavior_requirement(row, ordinal) for ordinal, row in enumerate(grouped[dimension], 1)
        )
        for dimension in DIMENSION_ORDER
    }


def _join_sections(sections: Mapping[int, str], numbers: tuple[int, ...]) -> str:
    joined = "\n\n".join(sections[number] for number in numbers)
    # The stage-specific section selection intentionally omits some source
    # sections.  Remove source numbering from the retained headings so the
    # resulting prompt does not suggest that sections were accidentally lost
    # (for example, "1" followed by "3").
    return SPEC_HEADING_NUMBER_PATTERN.sub(r"\1 ", joined).strip()


def _render_behavior_requirement(row: Mapping[str, Any], ordinal: int) -> str:
    item = _single_line(row["item"])
    objective = _candidate_objective(row["objective"])
    initial = _single_line(row["initial_state"])
    expected = _candidate_expected_transition(row["expected_transition"])
    if row["kind"] == "static":
        sentence = f'In the state "{initial}", the game must {objective} and satisfy this observable requirement: "{expected}".'
    else:
        trigger = _single_line(row["trigger"])
        sentence = f'In the state "{initial}", when "{trigger}" occurs, the game must "{expected}"; it must also {objective}.'
    return f"{ordinal}. {item}: {sentence}"


def _single_line(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def _candidate_objective(value: Any) -> str:
    objective = _single_line(value)
    match = re.match(r"^(?:verify|confirm|check|ensure)(?:\s+that)?\s+(.+)$", objective, flags=re.IGNORECASE)
    if match:
        objective = match.group(1).strip()
    if not objective:
        raise PromptBuildError("a behavior objective became empty after sanitization")
    return "ensure that " + objective[0].lower() + objective[1:]


def _candidate_expected_transition(value: Any) -> str:
    expected = _single_line(value)
    expected = re.sub(r"[.;]\s*this\s+checkpoint\s+does\s+not\s+(?:evaluate|assess).*$", "", expected, flags=re.IGNORECASE).strip()
    if not expected:
        raise PromptBuildError("a behavior requirement became empty after sanitization")
    return expected


def _render_template(template: str, values: Mapping[str, str], template_path: Path) -> str:
    placeholders = PLACEHOLDER_PATTERN.findall(template)
    unknown = sorted(set(placeholders) - set(values))
    if unknown:
        raise PromptBuildError(f"{template_path} has unknown placeholders: {unknown}")
    for key in set(placeholders):
        if not str(values[key]).strip():
            raise PromptBuildError(f"{template_path} resolved {{{key}}} to an empty value")
    return PLACEHOLDER_PATTERN.sub(lambda match: str(values[match.group(1)]), template).rstrip() + "\n"


def _validate_stage_prompt(prompt: str, *, stage: str, rows: list[dict[str, Any]], injected_sources: tuple[str, ...], spec_path: Path) -> None:
    for source in injected_sources:
        if source:
            prompt = prompt.replace(source, "<LOCKED_SOURCE_REMOVED>")
    # Game-authored labels such as "D1" may be legitimate entities (for
    # example, an enemy or obstacle).  Internal dimension labels are never
    # injected by this builder, so they do not need a blanket text rejection.
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["dimension"]].append(row)
    expected_dimensions = {"D2.1"} if stage == "state" else {"D2.2", "D2.3", "D2.4", "D2.5"} if stage == "game" else set()
    for dimension in DIMENSION_ORDER:
        expected_count = 1 if dimension in expected_dimensions else 0
        for ordinal, row in enumerate(grouped[dimension], 1):
            rendered = _render_behavior_requirement(row, ordinal)
            if prompt.count(rendered) != expected_count:
                raise PromptBuildError(f"{spec_path} {stage} rendered row {row['source_row']} an unexpected number of times")
    for literal in FORBIDDEN_CANDIDATE_LITERALS:
        if literal in prompt:
            raise PromptBuildError(f"{spec_path} leaked evaluator-only token {literal!r}")
    # The supplied checkpoint content is authoritative and includes Chinese
    # field values.  Preserve those values verbatim in the candidate prompt;
    # only evaluator-only IDs, detection methods, and rubrics are redacted.
    # "checkpoint" can be a real game mechanic in the source specification;
    # only the evaluator-only fields below are prohibited.
    for row in rows:
        if row["id"] in prompt or row["detection_method"] in prompt:
            raise PromptBuildError(f"{spec_path} leaked evaluator-only source content")
        if any(rubric in prompt for rubric in row["score_rubric"].values()):
            raise PromptBuildError(f"{spec_path} leaked a score rubric")


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PromptBuildError(f"{label} must be a non-empty string")
    return value.strip()


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PromptBuildError(f"{label} must be a mapping")
    return value


def _require_nonempty_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise PromptBuildError(f"{label} must be a non-empty list")
    return value


def _positive_int(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PromptBuildError(f"{label} must be a positive integer")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


__all__ = [
    "COMMON_TEMPLATE",
    "DEFAULT_STAGE_BUDGETS",
    "DIMENSION_ORDER",
    "GAME_SPECS",
    "PROMPTS_DIR",
    "PromptBuildError",
    "ROOT_DIR",
    "SPECS_DIR",
    "STAGED_PROMPTS_DIR",
    "STAGE_SPEC_SECTIONS",
    "STAGE_TEMPLATES",
    "StagePrompt",
    "SUPPORTED_GAMES",
    "build_stage_prompt",
    "canonical_game_slug",
    "generation_contract_sha256",
    "get_spec_path",
    "load_checkpoints",
    "load_evaluator_checkpoints",
    "load_spec",
    "render_all_prompt_contracts",
    "render_prompt_contract",
    "split_public_spec_sections",
    "validate_all_prompts",
]
