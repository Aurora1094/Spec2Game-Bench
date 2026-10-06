"""Command-line entry points for Spec2Game-Bench.

The CLI keeps benchmark artifacts outside the repository.  Commands that need
the paid provider say so explicitly in the help and all local validation and
smoke checks use deterministic data by default.
"""

from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping
from uuid import uuid4

from jsonschema import Draft202012Validator
import yaml

from spec2game.config.project import (
    DEFAULT_CONFIG,
    PROJECT_ROOT,
    game_by_slug,
    games,
    load_catalog,
    load_config,
    models,
    normalized_policy_sha256,
    require_locked_runtime_policy,
    resolve_workspace,
    select_run_config,
    task_storage_dir,
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
CHECKPOINT_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


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
    config = load_config(Path(args.config_path))
    if hasattr(args, "track"):
        config = select_run_config(config, track=args.track, model_id=args.model,
                                   game_slug=getattr(args, "game", None),
                                   variant_id=args.variant,
                                   require_model=args.command not in {"contract", "smoke"})
    return config


def _round_id(prefix: str) -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"


def _mock_contract_generator(config: Mapping[str, Any]):
    from spec2game.d4.contracts import eligible_d43_checkpoints
    from spec2game.generation.prompt_builder import load_evaluator_checkpoints, load_spec

    eligible_by_game: dict[str, list[dict[str, Any]]] = {}
    operation_policy_by_game: dict[str, dict[str, Any] | None] = {}
    for game in games(config):
        spec = load_spec(game.spec)
        checkpoints = load_evaluator_checkpoints(spec)
        from spec2game.d4.contracts import normalize_spec_operation_policy

        operation_policy = normalize_spec_operation_policy(
            spec.get("d4_operation_policy"),
            checkpoints=checkpoints,
        )
        operation_policy_by_game[game.slug] = operation_policy
        eligible_by_game[game.slug] = eligible_d43_checkpoints(
            checkpoints,
            operation_policy,
        )

    def generate(slug: str, _prompt: str) -> dict[str, Any]:
        rows = eligible_by_game[slug]
        operation_policy = operation_policy_by_game[slug]
        operations = (
            [item["description"] for item in operation_policy["operations"]]
            if operation_policy is not None
            else ["move left", "move right", "press the primary action"]
        )
        return {
            "target": "complete the current game objective",
            "allowed_operations": operations,
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

    from spec2game.generation.prompt_builder import (
        load_evaluator_checkpoints,
        load_spec,
        validate_all_prompts,
    )
    from spec2game.human_review.policy import human_review_policy_errors

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
    errors.extend(human_review_policy_errors(config))

    total = 0
    dimensions: dict[str, int] = {}
    seen_ids: set[str] = set()
    game_reports: list[dict[str, Any]] = []
    game_schema = PROJECT_ROOT / "benchmark" / "schemas" / "game.schema.json"
    checkpoint_schema = PROJECT_ROOT / "benchmark" / "schemas" / "checkpoint.schema.json"
    for item in [*catalog_games, *catalog.get("variant_instances", [])]:
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
                "variants": item.get("variants", []),
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
                or not SHA256_RE.fullmatch(str(source_audit.get("csv_sha256" if item.get("variant_id", "base") == "base" else "base_checkpoints_sha256", "")))
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
        if spec.get("evaluation", {}).get("d4") is not None:
            errors.append(f"{slug}: D4 must be round-scoped")
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
                text = str(row.get(field) or "").strip()
                if not text:
                    errors.append(f"{checkpoint_id}: missing {field}")
                elif CHECKPOINT_CJK_RE.search(text):
                    errors.append(f"{checkpoint_id}: {field} must be English")
            rubric = row.get("score_rubric")
            if not isinstance(rubric, Mapping) or any(
                not str(rubric.get(str(score)) or "").strip() for score in range(3)
            ):
                errors.append(f"{checkpoint_id}: score_rubric 0/1/2 is incomplete")
            elif any(
                CHECKPOINT_CJK_RE.search(str(rubric[str(score)])) for score in range(3)
            ):
                errors.append(f"{checkpoint_id}: score_rubric must be English")
            dimension = str(row.get("dimension"))
            dimensions[dimension] = dimensions.get(dimension, 0) + 1
        expected_count = int(item.get("checkpoint_count", -1))
        if len(rows) != expected_count:
            errors.append(f"{slug}: checkpoint_count does not match JSONL")
        total += len(rows)
        game_reports.append({"slug": slug, "checkpoints": len(rows)})
    if total != catalog.get("full_checkpoint_count") or dimensions != catalog.get("full_dimensions"):
        errors.append("checkpoint totals or dimension counts are invalid")
    from spec2game.config.variants import variant_data_errors
    errors.extend(variant_data_errors(catalog, PROJECT_ROOT / "benchmark"))
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
        "games": len(catalog_games),
        "instances": len(game_reports),
        "base_checkpoints": catalog["checkpoint_count"],
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
    from spec2game.config.project import locked_runtime_policy_errors

    return locked_runtime_policy_errors(config)


def cmd_validate(args: argparse.Namespace) -> int:
    report = validate_benchmark(_config(args))
    _json(report)
    return 0 if report["status"] == "passed" else 1


def cmd_preflight(args: argparse.Namespace) -> int:
    config = _config(args)
    report = validate_benchmark(config)
    report["selection"] = config["selection"]
    if report["status"] != "passed":
        _json(report)
        return 1
    workspace = resolve_workspace(args.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=workspace, prefix="probe-") as probe:
        path = (Path(probe) / "runs" / "r" / "tasks" / "t"
                / "evaluation/semantic_evidence/sampling_attempt_001/samples"
                / "candidate_workers/d2_worker_000/cwd/visual_frames/case_000/write-probe")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok", encoding="utf-8")
        report["workspace_writable"] = path.read_text(encoding="utf-8") == "ok"
        report["workspace_probe_path_characters"] = len(str(path))
    report["workspace"] = str(resolve_workspace(args.workspace))
    from spec2game.providers.dashscope import JudgeRouter, resolve_judge_route

    roles = ("contract_generation", "artistic_visual")
    routes = {
        role: resolve_judge_route(config["judge"], role)
        for role in roles
    }
    from spec2game.providers.dashscope import candidate_api_key_env
    api_key_envs = sorted(
        {
            str(route.get("api_key_env") or "")
            for route in routes.values()
            if str(route.get("api_key_env") or "")
        } | {candidate_api_key_env(model) for model in models(config)}
    )
    missing_api_key_envs = [name for name in api_key_envs if not os.environ.get(name)]
    report["api_key_configured"] = not missing_api_key_envs
    report["api_key_envs"] = api_key_envs
    report["judge_routes"] = {
        role: {
            "provider": route["provider"],
            "model": route["model"],
            "api_style": route.get("api_style", "chat_completions"),
        }
        for role, route in routes.items()
    }
    report["live_api_check"] = False
    if args.live:
        if missing_api_key_envs:
            raise ValueError(
                "Missing Judge API key environment variable(s): "
                + ", ".join(missing_api_key_envs)
            )
        router = JudgeRouter(
            config["judge"],
            resolve_workspace(args.workspace) / "preflight" / "model_calls",
        )
        router.for_role("contract_generation").json_text(
            "Return one JSON object with an ok boolean.",
            '{"request": "Spec2Game-Bench live connectivity check"}',
            "d4_contract_preflight",
        )
        with tempfile.NamedTemporaryFile(
            prefix="spec2game-mantle-vision-",
            suffix=".png",
            delete=False,
        ) as handle:
            probe_path = Path(handle.name)
            handle.write(
                base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAKklEQVR4nGOQr79PU8QwasGoBaMWjFowasGoBaMWjFowasGoBaMWDBULAGlq9EwJGxW7AAAAAElFTkSuQmCC"
                )
            )
        try:
            router.for_role("artistic_visual").json_vision(
                "Return one JSON object with an ok boolean.",
                '{"request": "Spec2Game-Bench visual live connectivity check"}',
                [(probe_path, "RGB preflight image")],
                "d4_1_artistic_visual_quality",
            )
        finally:
            probe_path.unlink(missing_ok=True)
        report["live_api_check"] = True
    _json(report)
    return 0 if report["status"] == "passed" else 1


def cmd_contract_build(args: argparse.Namespace) -> int:
    config = _config(args)
    require_locked_runtime_policy(config)
    from spec2game.d4.contracts import build_round_contracts, validate_round_manifest

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
    validate_round_manifest(manifest, round_dir=round_dir, expected_slugs=[game.slug for game in games(config)])
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
    from spec2game.execution.benchmark import run_benchmark

    result = run_benchmark(
        repetitions=1,
        resume=args.resume,
        resume_generation=args.resume_generation,
        run_id=args.run_id,
        config_path=args.config_path,
        workspace=resolve_workspace(args.workspace),
        round_id=args.round_id,
        game_slug=args.game,
        track=args.track,
        model_id=args.model,
        variant_id=args.variant,
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
    from spec2game.d4.contracts import build_round_contracts

    round_id = args.round_id or _round_id("evaluate")
    round_dir = workspace_round_dir(resolve_workspace(args.workspace), round_id)
    manifest = build_round_contracts(round_dir, games(config), config=config, round_id=round_id)
    return round_dir, manifest


def cmd_evaluate(args: argparse.Namespace) -> int:
    # Resolve selection and policy before touching the external workspace. This
    # keeps invalid multi-instance requests from being masked by stale locks.
    config = _config(args)
    require_locked_runtime_policy(config)
    if len(games(config)) != 1:
        raise ValueError("evaluate requires exactly one instance; select --game and --variant")
    from spec2game.execution.benchmark import _exclusive_run_lock

    run_dir = workspace_run_dir(resolve_workspace(args.workspace), args.run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    with _exclusive_run_lock(run_dir):
        return _evaluate_locked(args, config)


def _evaluate_locked(args: argparse.Namespace, config: Mapping[str, Any] | None = None) -> int:
    config = config or _config(args)
    require_locked_runtime_policy(config)
    if len(games(config)) != 1:
        raise ValueError("evaluate requires exactly one instance; select --game and --variant")
    from spec2game.execution.benchmark import prepare_manual_project
    from spec2game.evaluation.pipeline import evaluate_candidate
    from spec2game.reporting.reports import write_task_reports

    run_dir = workspace_run_dir(resolve_workspace(args.workspace), args.run_id)
    if (run_dir / "run_state.json").exists():
        raise ValueError("A benchmark already uses this run ID; choose a new run ID for evaluate")
    configured_models = models(config)
    if len(configured_models) != 1:
        raise ValueError("manual evaluation requires exactly one configured candidate model")
    candidate_model = configured_models[0]
    game = games(config)[0]
    task_dir = task_storage_dir(run_dir, f"{game.slug}__{candidate_model.id}__r01")
    from spec2game.execution.safe_artifacts import write_json
    identity_path = run_dir / "manual_evaluation.json"
    if identity_path.exists():
        prior = json.loads(identity_path.read_text(encoding="utf-8"))
        if not args.round_id:
            args.round_id = prior["round_id"]
        expected = {"selection": {**config["selection"], "scope": "subset"}, "model": config["models"][0],
                    "policy_sha256": normalized_policy_sha256(config), "round_id": args.round_id}
        if prior != expected:
            raise ValueError("Manual evaluation selection or policy changed; use a new run ID")
    round_dir, manifest = _ensure_round(args, config)
    identity = {"selection": {**config["selection"], "scope": "subset"}, "model": config["models"][0],
                "policy_sha256": normalized_policy_sha256(config), "round_id": manifest["round_id"]}
    if identity_path.exists() and json.loads(identity_path.read_text(encoding="utf-8")) != identity:
        raise ValueError("Manual evaluation selection or policy changed; use a new run ID")
    write_json(identity_path, identity)
    candidate = prepare_manual_project(args.candidate, task_dir)
    result = evaluate_candidate(
        game=game,
        model_id=candidate_model.id,
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
    result.setdefault("task", {}).update(instance_id=game.slug, family_slug=game.family_slug,
                                         variant_id=game.variant_id, track=args.track)
    write_task_reports(task_dir, result)
    _json({"status": result.get("status"), "task_dir": str(task_dir), "official_total": result.get("official_total")})
    return 0


def _static_plan(config: Mapping[str, Any], game_slugs: list[str]) -> dict[str, Any]:
    limits = {str(stage["id"]): int(stage["max_output_tokens"]) for stage in config["generation"]["stages"]}
    routes = config["judge"]["routes"]
    from spec2game.providers.dashscope import resolve_judge_route

    configured_models = models(config)
    if len(configured_models) != 1:
        raise ValueError("the locked plan requires exactly one candidate model")
    candidate_model = configured_models[0]
    return {
        "schema_version": 1,
        "status": "planned_not_sent",
        "model": candidate_model.model,
        "games": game_slugs,
        "selection": config.get("selection"),
        "instances": [{"instance_id": game.slug, "family_slug": game.family_slug,
                       "variant_id": game.variant_id, "spec": str(game.spec),
                       "checkpoints": str(game.checkpoints)} for game in games(config)],
        "generation": {
            "stage_order": ["state", "game", "rendering", "main"],
            "max_output_tokens": limits,
            "candidate_count": len(game_slugs),
            "normal_requests": len(game_slugs) * 4,
            "output_token_cap": len(game_slugs) * sum(limits.values()),
            "two_attempt_output_token_cap": len(game_slugs) * sum(limits.values()) * 2,
        },
        "judge_routes": {
            role: {
                "provider": route["provider"],
                "model": route["model"],
                "api_style": route["api_style"],
                "max_output_tokens": route["max_output_tokens"],
                "send": False,
            }
            for role, route in (
                (role, resolve_judge_route(config["judge"], role))
                for role in routes
            )
        },
        "notes": [
            "This logical plan sends no request and computes no score.",
            "A live plan with --candidate also samples the candidate and requires the configured provider key.",
        ],
    }


def cmd_plan(args: argparse.Namespace) -> int:
    config = _config(args)
    slugs = [game.slug for game in games(config)]
    for slug in slugs:
        game_by_slug(config, slug)
    if args.candidate:
        if len(slugs) != 1:
            raise ValueError("A live candidate plan requires exactly one instance")
        from spec2game.execution.candidate_project import CandidateProject
        from spec2game.planning.requests import run_request_plan

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
    from spec2game.d4.contracts import build_round_contracts, validate_round_manifest
    from spec2game.generation.prompt_builder import validate_all_prompts

    with tempfile.TemporaryDirectory(prefix="spec2game-smoke-") as temporary:
        round_dir = Path(temporary) / "smoke"
        generator = None if args.live else _mock_contract_generator(config)
        manifest = build_round_contracts(
            round_dir,
            games(config),
            config=config,
            generator=generator,
            round_id="smoke",
        )
        validate_round_manifest(manifest, round_dir=round_dir, expected_slugs=[game.slug for game in games(config)])
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
    from spec2game.human_review.artifacts import export_blind_bundle

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
    from spec2game.human_review.artifacts import validate_blind_bundle

    result = validate_blind_bundle(args.bundle_dir)
    _json(result)
    return 0 if result["status"] == "passed" else 1


def _runtime_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", dest="config_path", default=argparse.SUPPRESS, help="config YAML path")
    parser.add_argument("--workspace", default=argparse.SUPPRESS, help="external absolute artifact workspace")


def _selection_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", help="one configured candidate ID (required when several are configured)")
    parser.add_argument("--track", choices=("core15", "full150"), default="core15")
    parser.add_argument("--variant", choices=("base", *[f"var{i:02d}" for i in range(1, 10)]))


def cmd_status(args: argparse.Namespace) -> int:
    from spec2game.reporting.tracks import inspect_run
    _json(inspect_run(workspace_run_dir(resolve_workspace(args.workspace), args.run_id)))
    return 0


def cmd_budget(args: argparse.Namespace) -> int:
    from spec2game.reporting.budget import load_prices, project_budget
    config = _config(args)
    workspace = resolve_workspace(args.workspace)
    result = project_budget(config,
                            [workspace_run_dir(workspace, run_id) for run_id in args.reference_run_ids],
                            price_snapshot=load_prices(args.prices),
                            round_dir=workspace_round_dir(workspace, args.round_id) if args.round_id else None)
    _json(result)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from spec2game.reporting.tracks import combined_report
    _json(combined_report([workspace_run_dir(resolve_workspace(args.workspace), run) for run in args.run_ids]))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spec2game", description="Spec2Game-Bench benchmark CLI")
    parser.add_argument("--config", dest="config_path", default=str(DEFAULT_CONFIG), help="config YAML path")
    parser.add_argument("--workspace", default=None, help="external absolute artifact workspace")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="validate catalog, source conversion, policy, and prompts")
    _runtime_options(validate)
    validate.set_defaults(handler=cmd_validate)

    preflight = commands.add_parser("preflight", help="run local checks; --live performs one paid Judge check")
    _runtime_options(preflight)
    _selection_options(preflight)
    preflight.add_argument("--game", choices=EXPECTED_SLUGS)
    preflight.add_argument("--live", action="store_true", help="perform an explicit live Judge request")
    preflight.set_defaults(handler=cmd_preflight)

    contract = commands.add_parser("contract", help="round-scoped D4 contract commands")
    contract_commands = contract.add_subparsers(dest="contract_command", required=True)
    build = contract_commands.add_parser("build", help="generate and lock one contract per game")
    _runtime_options(build)
    _selection_options(build)
    build.add_argument("--game", choices=EXPECTED_SLUGS)
    build.add_argument("--round-id")
    build.add_argument("--mock", action="store_true", help="use deterministic local contract fixtures")
    build.set_defaults(handler=cmd_contract_build)

    benchmark = commands.add_parser("benchmark", help="run the benchmark, optionally for one game")
    _runtime_options(benchmark)
    _selection_options(benchmark)
    benchmark.add_argument("--run-id", default="main_r1")
    benchmark.add_argument("--round-id")
    benchmark.add_argument("--game", choices=EXPECTED_SLUGS, help="run one selected game")
    benchmark.add_argument("--no-resume", dest="resume", action="store_false")
    benchmark.add_argument(
        "--resume-generation",
        action="store_true",
        help="retry only a generation stage previously marked needs_regeneration",
    )
    benchmark.set_defaults(handler=cmd_benchmark, resume=True, resume_generation=False)

    evaluate = commands.add_parser("evaluate", help="evaluate one manual five-file candidate")
    _runtime_options(evaluate)
    _selection_options(evaluate)
    evaluate.add_argument("--game", required=True, choices=EXPECTED_SLUGS)
    evaluate.add_argument("--candidate", required=True)
    evaluate.add_argument("--run-id", default="manual_r1")
    evaluate.add_argument("--round-id")
    evaluate.set_defaults(handler=cmd_evaluate)

    plan = commands.add_parser("plan", help="write a no-send request plan or a live candidate plan")
    _runtime_options(plan)
    _selection_options(plan)
    plan.add_argument("--game", choices=EXPECTED_SLUGS)
    plan.add_argument("--candidate")
    plan.add_argument("--run-id", default="plan_r1")
    plan.add_argument("--round-id")
    plan.add_argument("--output")
    plan.set_defaults(handler=cmd_plan)

    smoke = commands.add_parser("smoke", help="run deterministic local integration checks")
    _runtime_options(smoke)
    _selection_options(smoke)
    smoke.add_argument("--game", choices=EXPECTED_SLUGS)
    smoke.add_argument("--live", action="store_true", help="use real Qwen contract generation")
    smoke.set_defaults(handler=cmd_smoke)

    budget = commands.add_parser("budget", help="estimate selected workload using measured pilot usage, without API calls")
    _runtime_options(budget)
    _selection_options(budget)
    budget.add_argument("--game", choices=EXPECTED_SLUGS)
    budget.add_argument("--reference-run-ids", nargs="*", default=[])
    budget.add_argument("--prices", help="dated JSON rates: as_of, models, USD per million input/output tokens")
    budget.add_argument("--round-id", help="existing shared contract round, to avoid budgeting its locked contracts again")
    budget.set_defaults(handler=cmd_budget)

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

    status = commands.add_parser("status", help="read run progress without executing or resuming tasks")
    _runtime_options(status)
    status.add_argument("--run-id", required=True)
    status.set_defaults(handler=cmd_status)
    report = commands.add_parser("report", help="read reports grouped by track and compatible evaluation cohort")
    _runtime_options(report)
    report.add_argument("--run-ids", nargs="+", required=True)
    report.set_defaults(handler=cmd_report)

    return parser


def _load_repo_dotenv() -> None:
    path = PROJECT_ROOT / ".env"
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def main(argv: list[str] | None = None) -> int:
    _load_repo_dotenv()
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except Exception as exc:
        from spec2game.d4.contracts import ContractsIncomplete
        if isinstance(exc, ContractsIncomplete):
            _json(exc.report)
            return 1
        print(f"spec2game: {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
