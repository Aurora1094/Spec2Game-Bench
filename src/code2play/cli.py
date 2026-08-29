"""Command-line entry points for Code2Play-Bench.

The CLI keeps benchmark artifacts outside the repository.  Commands that need
the paid provider say so explicitly in the help and all local validation and
smoke checks use deterministic data by default.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping
from uuid import uuid4

from jsonschema import Draft202012Validator
import yaml

from code2play.config.project import (
    DEFAULT_CONFIG,
    PROJECT_ROOT,
    game_by_slug,
    games,
    load_catalog,
    load_config,
    normalized_policy_sha256,
    require_locked_runtime_policy,
    resolve_workspace,
    workspace_round_dir,
    workspace_run_dir,
)


EXPECTED_SLUGS = (
    "snake",
    "dodge_blocks",
    "whack_a_mole",
    "asteroids",
    "maze_runner",
    "space_invaders",
    "simple_platformer",
    "tetris",
    "match3",
    "simple_shop",
    "carrot_defense",
    "farming_lite",
    "pipe_connection",
    "arena_shooter",
    "mini_zelda",
)
EXPECTED_DIMENSIONS = {"D2.1": 97, "D2.2": 94, "D2.3": 150, "D2.4": 66, "D2.5": 130}
CHECKPOINT_ID_RE = re.compile(r"^(?P<slug>[a-z][a-z0-9_]*)\.D2\.[1-5]\.\d{2}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _schema_errors(value: Any, schema_path: Path, label: str) -> list[str]:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return [f"{label}: unable to load schema: {type(exc).__name__}: {exc}"]
    result: list[str] = []
    for error in errors:
        location = ".".join(str(part) for part in error.absolute_path) or "root"
        result.append(f"{label}.{location}: {error.message}")
    return result


def _json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str))


def _config(args: argparse.Namespace) -> dict[str, Any]:
    return load_config(Path(args.config_path))


def _round_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"


def _mock_contract_generator(config: Mapping[str, Any]):
    from code2play.d4.contracts import eligible_d43_checkpoints
    from code2play.generation.prompt_builder import load_evaluator_checkpoints, load_spec

    eligible_by_game: dict[str, list[dict[str, Any]]] = {}
    for game in games(config):
        spec = load_spec(game.spec)
        eligible_by_game[game.slug] = eligible_d43_checkpoints(
            load_evaluator_checkpoints(spec)
        )

    def generate(slug: str, _prompt: str) -> dict[str, Any]:
        rows = eligible_by_game[slug]
        return {
            "target": "complete the current game objective",
            "allowed_operations": ["move left", "move right", "press the primary action"],
            "art_direction": [
                "use a clear playable scene",
                "separate interactive objects from the background",
                "keep text readable at the game window size",
            ],
            "art_sample_size": 8,
            "sample_seed": 41,
            "d4_3_source_checkpoint_ids": [rows[0]["id"], rows[1]["id"]],
        }

    return generate


def validate_benchmark(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate checked-in benchmark data, policy, and prompt contracts."""

    from code2play.generation.prompt_builder import (
        load_evaluator_checkpoints,
        load_spec,
        validate_all_prompts,
    )

    catalog = load_catalog(PROJECT_ROOT / "benchmark" / "catalog.yaml")
    errors: list[str] = []
    catalog_games = catalog.get("games", [])
    slugs = [str(item.get("slug")) for item in catalog_games if isinstance(item, Mapping)]
    if tuple(slugs) != EXPECTED_SLUGS:
        errors.append("catalog game order or game set is invalid")
    if catalog.get("game_count") != 15:
        errors.append("catalog game_count must be 15")
    if catalog.get("checkpoint_count") != 537:
        errors.append("catalog checkpoint_count must be 537")
    if catalog.get("dimensions") != EXPECTED_DIMENSIONS:
        errors.append("catalog dimension totals are invalid")

    total = 0
    dimensions: dict[str, int] = {}
    seen_ids: set[str] = set()
    game_reports: list[dict[str, Any]] = []
    game_schema = PROJECT_ROOT / "benchmark" / "schemas" / "game.schema.json"
    checkpoint_schema = PROJECT_ROOT / "benchmark" / "schemas" / "checkpoint.schema.json"
    for item in catalog_games:
        if not isinstance(item, Mapping):
            errors.append("catalog contains a non-object game")
            continue
        slug = str(item.get("slug"))
        game_root = PROJECT_ROOT / "benchmark" / str(item.get("path", ""))
        spec_path = game_root / "spec.md"
        checkpoint_path = game_root / "checkpoints.jsonl"
        game_yaml = game_root / "game.yaml"
        if not game_yaml.is_file() or not spec_path.is_file() or not checkpoint_path.is_file():
            errors.append(f"{slug}: game.yaml/spec.md/checkpoints.jsonl are required")
            continue
        try:
            metadata = yaml.safe_load(game_yaml.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            errors.append(f"{slug}: invalid game.yaml: {type(exc).__name__}: {exc}")
            metadata = None
        errors.extend(_schema_errors(metadata, game_schema, f"{slug}.game.yaml"))
        if isinstance(metadata, Mapping):
            expected_metadata = {
                "slug": slug,
                "name": item.get("name"),
                "difficulty": item.get("difficulty"),
                "spec": "spec.md",
                "checkpoints": "checkpoints.jsonl",
                "variants": [],
                "window_size": item.get("window_size"),
            }
            for key, expected in expected_metadata.items():
                if metadata.get(key) != expected:
                    errors.append(f"{slug}: game.yaml {key} differs from catalog")
            source_audit = metadata.get("source_audit")
            if not isinstance(source_audit, Mapping):
                errors.append(f"{slug}: game.yaml source_audit is required")
            elif (
                not SHA256_RE.fullmatch(str(source_audit.get("docx_sha256", "")))
                or not SHA256_RE.fullmatch(str(source_audit.get("csv_sha256", "")))
                or int(source_audit.get("checkpoint_count", -1)) != int(item.get("checkpoint_count", -2))
            ):
                errors.append(f"{slug}: game.yaml source_audit is invalid")
        try:
            spec = load_spec(spec_path)
            rows = load_evaluator_checkpoints(spec)
        except Exception as exc:
            errors.append(f"{slug}: {type(exc).__name__}: {exc}")
            continue
        try:
            raw_rows = [
                json.loads(line)
                for line in checkpoint_path.read_text(encoding="utf-8-sig").splitlines()
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{slug}: invalid checkpoint JSONL: {type(exc).__name__}: {exc}")
            raw_rows = []
        for row_number, raw_row in enumerate(raw_rows, start=1):
            errors.extend(_schema_errors(raw_row, checkpoint_schema, f"{slug}.checkpoints.jsonl:{row_number}"))
        if len(raw_rows) != len(rows):
            errors.append(f"{slug}: checkpoint JSONL row count differs from loaded evaluator rows")
        if spec.get("game_name") != item.get("name"):
            errors.append(f"{slug}: game name differs between catalog and spec")
        if item.get("variants") != [] or spec.get("evaluation", {}).get("d4") is not None:
            errors.append(f"{slug}: variants must be [] and D4 must be round-scoped")
        local_ids: set[str] = set()
        for row in rows:
            checkpoint_id = str(row.get("id", ""))
            if checkpoint_id in seen_ids or checkpoint_id in local_ids:
                errors.append(f"duplicate checkpoint id: {checkpoint_id}")
            local_ids.add(checkpoint_id)
            seen_ids.add(checkpoint_id)
            if CHECKPOINT_ID_RE.fullmatch(checkpoint_id) is None or not checkpoint_id.startswith(f"{slug}."):
                errors.append(f"{slug}: invalid checkpoint id {checkpoint_id}")
            for field in (
                "item",
                "objective",
                "initial_state",
                "trigger",
                "expected_transition",
                "detection_method",
            ):
                if not str(row.get(field) or "").strip():
                    errors.append(f"{checkpoint_id}: missing {field}")
            rubric = row.get("score_rubric")
            if not isinstance(rubric, Mapping) or any(
                not str(rubric.get(str(score)) or "").strip() for score in range(3)
            ):
                errors.append(f"{checkpoint_id}: score_rubric 0/1/2 is incomplete")
            dimension = str(row.get("dimension"))
            dimensions[dimension] = dimensions.get(dimension, 0) + 1
        expected_count = int(item.get("checkpoint_count", -1))
        if len(rows) != expected_count:
            errors.append(f"{slug}: checkpoint_count does not match JSONL")
        total += len(rows)
        game_reports.append({"slug": slug, "checkpoints": len(rows)})
    if total != 537 or dimensions != EXPECTED_DIMENSIONS:
        errors.append("checkpoint totals or dimension counts are invalid")
    for path in (PROJECT_ROOT / "benchmark").rglob("*"):
        if path.is_file() and path.suffix.lower() in {".docx", ".csv", ".xls", ".xlsx"}:
            errors.append(f"source file must not be checked in: {path.relative_to(PROJECT_ROOT)}")
    errors.extend(requirement for requirement in _prompt_validation_errors(config, validate_all_prompts))
    errors.extend(require_locked_errors(config))
    audit_path = PROJECT_ROOT / "benchmark" / "conversion_audit.json"
    if not audit_path.is_file():
        errors.append("benchmark/conversion_audit.json is missing")
    else:
        try:
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"conversion audit is invalid: {type(exc).__name__}: {exc}")
        else:
            if audit.get("schema_version") != 1 or audit.get("source_file_policy") != "source files are external and are not copied into the repository":
                errors.append("conversion audit schema or source-file policy is invalid")
            if audit.get("totals") != {"games": 15, "checkpoints": 537, "dimensions": EXPECTED_DIMENSIONS}:
                errors.append("conversion audit totals are invalid")
            audit_games = audit.get("games")
            if not isinstance(audit_games, list) or [item.get("slug") for item in audit_games if isinstance(item, Mapping)] != list(EXPECTED_SLUGS):
                errors.append("conversion audit game order is invalid")
            for audit_game in audit_games if isinstance(audit_games, list) else []:
                if not isinstance(audit_game, Mapping):
                    errors.append("conversion audit contains a non-object game")
                    continue
                for key in ("slug", "checkpoint_count", "dimension_counts", "spec_body_sha256"):
                    if key not in audit_game:
                        errors.append(f"conversion audit game is missing {key}")
                for hash_value in (
                    audit_game.get("spec_body_sha256"),
                    (audit_game.get("docx") or {}).get("sha256") if isinstance(audit_game.get("docx"), Mapping) else None,
                    (audit_game.get("csv") or {}).get("sha256") if isinstance(audit_game.get("csv"), Mapping) else None,
                ):
                    if not SHA256_RE.fullmatch(str(hash_value or "")):
                        errors.append(f"conversion audit hash is invalid for {audit_game.get('slug')}")
    return {
        "status": "passed" if not errors else "failed",
        "games": len(game_reports),
        "checkpoints": total,
        "dimensions": dimensions,
        "policy_sha256": normalized_policy_sha256(config),
        "errors": errors,
    }


def _prompt_validation_errors(config: Mapping[str, Any], validator: Any) -> list[str]:
    try:
        validator(config["generation"])
    except Exception as exc:
        return [f"prompt contract validation failed: {type(exc).__name__}: {exc}"]
    return []


def require_locked_errors(config: Mapping[str, Any]) -> list[str]:
    from code2play.config.project import locked_runtime_policy_errors

    return locked_runtime_policy_errors(config)


def cmd_validate(args: argparse.Namespace) -> int:
    report = validate_benchmark(_config(args))
    _json(report)
    return 0 if report["status"] == "passed" else 1


def cmd_preflight(args: argparse.Namespace) -> int:
    config = _config(args)
    report = validate_benchmark(config)
    report["workspace"] = str(resolve_workspace(args.workspace))
    report["api_key_configured"] = bool(__import__("os").environ.get("DASHSCOPE_API_KEY"))
    report["live_api_check"] = False
    if args.live:
        from code2play.providers.dashscope import create_dashscope_judge

        judge = create_dashscope_judge(
            resolve_workspace(args.workspace) / "preflight" / "model_calls",
            model="qwen3.7-plus",
            max_output_tokens=64,
            role="contract_generation",
        )
        judge.json_text(
            "Return one JSON object with an ok boolean.",
            '{"request": "Code2Play-Bench live connectivity check"}',
            "d4_contract_preflight",
        )
        report["live_api_check"] = True
    _json(report)
    return 0 if report["status"] == "passed" else 1


def cmd_contract_build(args: argparse.Namespace) -> int:
    config = _config(args)
    require_locked_runtime_policy(config)
    from code2play.d4.contracts import build_round_contracts, validate_round_manifest

    round_id = args.round_id or _round_id("round")
    round_dir = workspace_round_dir(resolve_workspace(args.workspace), round_id)
    generator = _mock_contract_generator(config) if args.mock else None
    manifest = build_round_contracts(
        round_dir,
        games(config),
        config=config,
        generator=generator,
        round_id=round_id,
    )
    validate_round_manifest(manifest, round_dir=round_dir, expected_slugs=list(EXPECTED_SLUGS))
    _json(
        {
            "status": "passed",
            "round_id": round_id,
            "manifest_sha256": manifest["manifest_sha256"],
            "manifest": str(round_dir / "contracts" / "manifest.json"),
            "mock": bool(args.mock),
        }
    )
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    from code2play.execution.benchmark import run_benchmark

    result = run_benchmark(
        repetitions=1,
        resume=args.resume,
        run_id=args.run_id,
        config_path=args.config_path,
        workspace=resolve_workspace(args.workspace),
        round_id=args.round_id,
    )
    _json(
        {
            "status": result.get("status"),
            "run_id": result.get("run_id"),
            "round_id": result.get("round_id"),
            "contract_manifest_sha256": result.get("contract_manifest_sha256"),
            "run_dir": str(workspace_run_dir(resolve_workspace(args.workspace), args.run_id)),
        }
    )
    return 0


def _ensure_round(args: argparse.Namespace, config: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
    from code2play.d4.contracts import build_round_contracts

    round_id = args.round_id or _round_id("evaluate")
    round_dir = workspace_round_dir(resolve_workspace(args.workspace), round_id)
    manifest = build_round_contracts(round_dir, games(config), config=config, round_id=round_id)
    return round_dir, manifest


def cmd_evaluate(args: argparse.Namespace) -> int:
    config = _config(args)
    require_locked_runtime_policy(config)
    from code2play.execution.benchmark import prepare_manual_project
    from code2play.evaluation.pipeline import evaluate_candidate
    from code2play.reporting.reports import write_task_reports

    round_dir, manifest = _ensure_round(args, config)
    run_dir = workspace_run_dir(resolve_workspace(args.workspace), args.run_id)
    task_dir = run_dir / "tasks" / f"{args.game}__qwen3_7_plus__r01"
    candidate = prepare_manual_project(args.candidate, task_dir)
    game = game_by_slug(config, args.game)
    result = evaluate_candidate(
        game=game,
        model_id="qwen3_7_plus",
        repetition=1,
        project=candidate,
        task_dir=task_dir,
        region=str(config["region"]),
        judge_config=dict(config["judge"]),
        d2_workers=int(config["evaluation"]["d2_workers"]),
        sampling_timeout_seconds=int(config["evaluation"]["sampling_timeout_seconds"]),
        round_dir=round_dir,
        contract_manifest_sha256=str(manifest["manifest_sha256"]),
        config=dict(config),
    )
    write_task_reports(task_dir, result)
    _json({"status": result.get("status"), "task_dir": str(task_dir), "official_total": result.get("official_total")})
    return 0


def _static_plan(config: Mapping[str, Any], game_slugs: list[str]) -> dict[str, Any]:
    limits = {str(stage["id"]): int(stage["max_output_tokens"]) for stage in config["generation"]["stages"]}
    routes = config["judge"]["routes"]
    return {
        "schema_version": 1,
        "status": "planned_not_sent",
        "model": "qwen3.7-plus",
        "games": game_slugs,
        "generation": {
            "stage_order": ["state", "game", "rendering", "main"],
            "max_output_tokens": limits,
        },
        "judge_routes": {
            role: {
                "provider": route["provider"],
                "model": route["model"],
                "api_style": route["api_style"],
                "max_output_tokens": route["max_output_tokens"],
                "send": False,
            }
            for role, route in routes.items()
        },
        "notes": [
            "This logical plan sends no request and computes no score.",
            "A live plan with --candidate also samples the candidate and requires DASHSCOPE_API_KEY.",
        ],
    }


def cmd_plan(args: argparse.Namespace) -> int:
    config = _config(args)
    slugs = [args.game] if args.game else list(EXPECTED_SLUGS)
    for slug in slugs:
        game_by_slug(config, slug)
    if args.candidate:
        from code2play.execution.candidate_project import CandidateProject
        from code2play.planning.requests import run_request_plan

        run_dir = workspace_run_dir(resolve_workspace(args.workspace), args.run_id)
        result = run_request_plan(
            game=game_by_slug(config, slugs[0]),
            candidate=CandidateProject(args.candidate),
            run_dir=run_dir,
            run_id=args.run_id,
            config=config,
            round_dir=workspace_round_dir(resolve_workspace(args.workspace), args.round_id or _round_id("plan")),
        )
    else:
        result = _static_plan(config, slugs)
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = {"status": result.get("status"), "output": str(output)}
    _json(result)
    return 0


def cmd_smoke(args: argparse.Namespace) -> int:
    config = _config(args)
    from code2play.d4.contracts import build_round_contracts, validate_round_manifest
    from code2play.generation.prompt_builder import validate_all_prompts

    with tempfile.TemporaryDirectory(prefix="code2play-smoke-") as temporary:
        round_dir = Path(temporary) / "smoke"
        generator = None if args.live else _mock_contract_generator(config)
        manifest = build_round_contracts(
            round_dir,
            games(config),
            config=config,
            generator=generator,
            round_id="smoke",
        )
        validate_round_manifest(manifest, round_dir=round_dir, expected_slugs=list(EXPECTED_SLUGS))
        prompt_reports = validate_all_prompts(config["generation"])
    _json(
        {
            "status": "passed",
            "live": bool(args.live),
            "games": len(prompt_reports),
            "checkpoints": sum(item["checkpoint_count"] for item in prompt_reports),
            "contract_manifest_sha256": manifest["manifest_sha256"],
        }
    )
    return 0


def cmd_human_export(args: argparse.Namespace) -> int:
    from code2play.human_review.artifacts import export_blind_bundle

    task_dir = Path(args.task_dir).expanduser().resolve()
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else resolve_workspace(args.workspace) / "questionnaires" / (args.round_id or "exports")
    )
    result = export_blind_bundle(
        task_dir,
        output_dir,
        blind_id=args.blind_id,
        config_path=args.config_path,
    )
    _json(result)
    return 0 if result["validation"]["status"] == "passed" else 1


def cmd_human_validate(args: argparse.Namespace) -> int:
    from code2play.human_review.artifacts import validate_blind_bundle

    result = validate_blind_bundle(args.bundle_dir)
    _json(result)
    return 0 if result["status"] == "passed" else 1


def _runtime_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", dest="config_path", default=argparse.SUPPRESS, help="config YAML path")
    parser.add_argument("--workspace", default=argparse.SUPPRESS, help="external absolute artifact workspace")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="code2play", description="Code2Play-Bench benchmark CLI")
    parser.add_argument("--config", dest="config_path", default=str(DEFAULT_CONFIG), help="config YAML path")
    parser.add_argument("--workspace", default=None, help="external absolute artifact workspace")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="validate catalog, source conversion, policy, and prompts")
    _runtime_options(validate)
    validate.set_defaults(handler=cmd_validate)

    preflight = commands.add_parser("preflight", help="run local checks; --live performs one paid Qwen check")
    _runtime_options(preflight)
    preflight.add_argument("--live", action="store_true", help="perform an explicit live DashScope request")
    preflight.set_defaults(handler=cmd_preflight)

    contract = commands.add_parser("contract", help="round-scoped D4 contract commands")
    contract_commands = contract.add_subparsers(dest="contract_command", required=True)
    build = contract_commands.add_parser("build", help="generate and lock one contract per game")
    _runtime_options(build)
    build.add_argument("--round-id")
    build.add_argument("--mock", action="store_true", help="use deterministic local contract fixtures")
    build.set_defaults(handler=cmd_contract_build)

    benchmark = commands.add_parser("benchmark", help="run the 15-game main experiment")
    _runtime_options(benchmark)
    benchmark.add_argument("--run-id", default="main_r1")
    benchmark.add_argument("--round-id")
    benchmark.add_argument("--no-resume", dest="resume", action="store_false")
    benchmark.set_defaults(handler=cmd_benchmark, resume=True)

    evaluate = commands.add_parser("evaluate", help="evaluate one manual five-file candidate")
    _runtime_options(evaluate)
    evaluate.add_argument("--game", required=True, choices=EXPECTED_SLUGS)
    evaluate.add_argument("--candidate", required=True)
    evaluate.add_argument("--run-id", default="manual_r1")
    evaluate.add_argument("--round-id")
    evaluate.set_defaults(handler=cmd_evaluate)

    plan = commands.add_parser("plan", help="write a no-send request plan or a live candidate plan")
    _runtime_options(plan)
    plan.add_argument("--game", choices=EXPECTED_SLUGS)
    plan.add_argument("--candidate")
    plan.add_argument("--run-id", default="plan_r1")
    plan.add_argument("--round-id")
    plan.add_argument("--output")
    plan.set_defaults(handler=cmd_plan)

    smoke = commands.add_parser("smoke", help="run deterministic local integration checks")
    _runtime_options(smoke)
    smoke.add_argument("--live", action="store_true", help="use real Qwen contract generation")
    smoke.set_defaults(handler=cmd_smoke)

    human = commands.add_parser("human", help="anonymous questionnaire package commands")
    human_commands = human.add_subparsers(dest="human_command", required=True)
    export = human_commands.add_parser("export", help="export public blind items plus private mapping")
    _runtime_options(export)
    export.add_argument("--task-dir", required=True)
    export.add_argument("--output-dir")
    export.add_argument("--round-id")
    export.add_argument("--blind-id")
    export.set_defaults(handler=cmd_human_export)
    human_validate = human_commands.add_parser("validate", help="validate a public export package")
    _runtime_options(human_validate)
    human_validate.add_argument("--bundle-dir", required=True)
    human_validate.set_defaults(handler=cmd_human_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except Exception as exc:
        print(f"code2play: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
