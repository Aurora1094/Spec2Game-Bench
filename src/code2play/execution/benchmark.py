"""Sequential single-Qwen benchmark runner with immutable generation artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
from functools import wraps
import json
import os
from pathlib import Path
import time
import traceback
from typing import Any, Callable, Mapping
from uuid import uuid4

from code2play.execution.candidate_project import CandidateProject
from code2play.evaluation.pipeline import evaluate_candidate, sha256_file
from code2play.config.project import (
    ROOT,
    GameConfig,
    ModelConfig,
    games,
    load_config,
    models,
    normalized_policy_sha256,
    require_locked_runtime_policy,
    resolve_workspace,
    workspace_round_dir,
    workspace_run_dir,
)
from code2play.providers.dashscope import resolve_judge_route
from code2play.execution.protocol_policy import (
    runtime_protocol_descriptor,
    sha256_json,
)
from code2play.d4.contracts import build_round_contracts, validate_round_manifest
from code2play.execution.safe_artifacts import redact_text, scan_for_secret_leaks, write_json
from code2play.generation.staged import generate_candidate_project


DEFAULT_RUN_ID = "main_r1"
TERMINAL_FAILURE_POLICY_VERSION = 2
TERMINAL_CANDIDATE_FAILURE_PREFIXES = (
    "Candidate RPC closed during 'init'",
    "Candidate RPC 'init' failed:",
    "Candidate failed protocol-v4 init/snapshot/action audit",
)


def _clear_failure_metadata(record: dict[str, Any]) -> None:
    for key in ("error", "error_type", "failed_at", "failed_stage"):
        record.pop(key, None)


def _clear_terminal_failure_metadata(record: dict[str, Any]) -> None:
    record.pop("terminal_failure", None)
    record.pop("terminal_failure_policy_version", None)


def _has_current_terminal_failure(record: dict[str, Any]) -> bool:
    return (
        record.get("terminal_failure") is True
        and record.get("terminal_failure_policy_version")
        == TERMINAL_FAILURE_POLICY_VERSION
    )


def _is_terminal_candidate_failure(value: BaseException | str) -> bool:
    message = str(value)
    return any(
        message.startswith(prefix) for prefix in TERMINAL_CANDIDATE_FAILURE_PREFIXES
    )


def _archive_resolved_failure(task_dir: Path) -> None:
    failure_path = task_dir / "failure.json"
    if not failure_path.is_file():
        return
    archive_dir = task_dir / "superseded_evidence" / "resolved_failures"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    failure_path.replace(archive_dir / f"failure_{stamp}.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid_is_running(pid: int) -> bool:
    if pid < 1:
        return False
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError):
        return False
    return True


@contextmanager
def _exclusive_run_lock(run_dir: Path):
    """Prevent two resume processes from mutating the same batch."""

    lock_path = run_dir / "benchmark.lock.json"
    owner = {"pid": os.getpid(), "created_at": _now()}
    while True:
        try:
            descriptor = os.open(
                lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            )
        except FileExistsError:
            try:
                existing = _read_json(lock_path)
                existing_pid = int(existing.get("pid", 0))
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                existing_pid = 0
            if _pid_is_running(existing_pid):
                raise RuntimeError(
                    f"Benchmark run is already active in PID {existing_pid}: {run_dir.name}"
                )
            stale = run_dir / (
                "benchmark.lock.stale."
                + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                + ".json"
            )
            lock_path.replace(stale)
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(owner, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        break
    try:
        yield
    finally:
        try:
            current = _read_json(lock_path)
            if int(current.get("pid", 0)) == os.getpid():
                lock_path.unlink()
        except (FileNotFoundError, OSError, ValueError, TypeError, json.JSONDecodeError):
            pass


def _serialized_benchmark(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        run_id = str(kwargs.get("run_id", DEFAULT_RUN_ID))
        run_dir = workspace_run_dir(resolve_workspace(kwargs.get("workspace")), run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        with _exclusive_run_lock(run_dir):
            return function(*args, **kwargs)

    return wrapper


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected object in {path}")
    return value


def validate_batch_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the current resumable batch-state contract before execution."""

    value = dict(state)
    if value.get("schema_version") != 3:
        raise ValueError("Batch run_state schema_version is not supported")
    required = {
        "run_id",
        "round_id",
        "contract_manifest_sha256",
        "policy_sha256",
        "policy_descriptor",
        "matrix",
    }
    missing = sorted(key for key in required if key not in value)
    if missing:
        raise ValueError("Batch run_state is missing: " + ", ".join(missing))
    for key in ("run_id", "round_id", "contract_manifest_sha256", "policy_sha256"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError(f"Batch run_state field {key} is invalid")
    if not isinstance(value.get("policy_descriptor"), Mapping):
        raise ValueError("Batch run_state policy_descriptor is invalid")
    matrix = value.get("matrix")
    if not isinstance(matrix, list) or not matrix:
        raise ValueError("Batch run_state matrix is invalid")
    required_record = {"game", "model", "repetition", "task_id", "status"}
    for index, record in enumerate(matrix, start=1):
        if not isinstance(record, Mapping):
            raise ValueError(f"Batch run_state matrix row {index} is invalid")
        missing_record = sorted(required_record - set(record))
        if missing_record:
            raise ValueError(
                f"Batch run_state matrix row {index} is missing: "
                + ", ".join(missing_record)
            )
    return value


def validate_task_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the current resumable per-task state contract."""

    value = dict(state)
    if value.get("schema_version") != 3:
        raise ValueError("Task run_state schema_version is not supported")
    task = value.get("task")
    if not isinstance(task, Mapping):
        raise ValueError("Task run_state task descriptor is invalid")
    required_task = {"game", "model_id", "repetition"}
    missing_task = sorted(required_task - set(task))
    if missing_task:
        raise ValueError("Task run_state task is missing: " + ", ".join(missing_task))
    required = {
        "round_id",
        "contract_manifest_sha256",
        "policy_sha256",
        "policy_descriptor",
        "stages",
    }
    missing = sorted(key for key in required if key not in value)
    if missing:
        raise ValueError("Task run_state is missing: " + ", ".join(missing))
    for key in ("round_id", "contract_manifest_sha256", "policy_sha256"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError(f"Task run_state field {key} is invalid")
    if not isinstance(value.get("policy_descriptor"), Mapping):
        raise ValueError("Task run_state policy_descriptor is invalid")
    if not isinstance(value.get("stages"), Mapping):
        raise ValueError("Task run_state stages are invalid")
    return value


def _save_state(path: Path, state: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    write_json(temporary, state)
    for attempt in range(8):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(min(0.05 * (2**attempt), 0.5))


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _d4_contract_policy_entry(game: GameConfig) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "configured": game.d4_configured,
        "round_id": None,
        "manifest_sha256": None,
        "file_sha256": None,
        "contract_sha256": None,
        "contract_version": None,
        "design_version": None,
    }
    return entry


def _d4_contract_policy(
    config: dict[str, Any], manifest: Mapping[str, Any] | None = None
) -> dict[str, dict[str, Any]]:
    contract_records = manifest.get("contracts", {}) if isinstance(manifest, Mapping) else {}
    return {
        game.slug: {
            **_d4_contract_policy_entry(game),
            "round_id": manifest.get("round_id") if isinstance(manifest, Mapping) else None,
            "manifest_sha256": manifest.get("manifest_sha256") if isinstance(manifest, Mapping) else None,
            "contract_sha256": (
                contract_records.get(game.slug, {}).get("contract_sha256")
                if isinstance(contract_records.get(game.slug), Mapping)
                else None
            ),
            "status": "locked" if game.slug in contract_records else "missing",
        }
        for game in games(config)
    }


def _batch_policy_descriptor(
    config: dict[str, Any],
    manifest: Mapping[str, Any] | None = None,
    *,
    selected_game_slugs: list[str] | None = None,
) -> dict[str, Any]:
    locked = {
        key: config[key]
        for key in ("region", "generation", "judge", "evaluation", "games", "models")
    }
    locked["d4_contracts"] = _d4_contract_policy(config, manifest)
    locked["runtime_protocol"] = runtime_protocol_descriptor()
    descriptor: dict[str, Any] = {
        "schema_version": 1,
        "locked_policy": locked,
    }
    if selected_game_slugs is not None:
        descriptor["selected_game_slugs"] = list(selected_game_slugs)
    return descriptor


def _policy_sha256(config: dict[str, Any], manifest: Mapping[str, Any] | None = None) -> str:
    return sha256_json(_batch_policy_descriptor(config, manifest))


def _task_policy_descriptor(
    config: dict[str, Any],
    game: GameConfig,
    manifest: Mapping[str, Any] | None = None,
    *,
    selected_game_slugs: list[str] | None = None,
) -> dict[str, Any]:
    batch_descriptor = _batch_policy_descriptor(
        config,
        manifest,
        selected_game_slugs=selected_game_slugs,
    )
    return {
        "schema_version": 1,
        "batch_policy_sha256": sha256_json(batch_descriptor),
        "runtime_protocol": batch_descriptor["locked_policy"]["runtime_protocol"],
        "game": game.slug,
        "spec_sha256": sha256_file(game.spec),
        "d4_contract": _d4_contract_policy(config, manifest).get(game.slug),
    }


def _task_policy_sha256(
    config: dict[str, Any],
    game: GameConfig,
    *,
    selected_game_slugs: list[str] | None = None,
) -> str:
    return sha256_json(
        _task_policy_descriptor(
            config,
            game,
            selected_game_slugs=selected_game_slugs,
        )
    )


def _render_prompt_contract(
    game: GameConfig,
    prompt_dir: Path,
    generation_config: dict[str, Any],
) -> dict[str, Any]:
    from code2play.generation.prompt_builder import render_prompt_contract

    return render_prompt_contract(
        game.slug,
        output_dir=prompt_dir,
        generation_config=generation_config,
    )


def _initial_task_state(
    game: GameConfig,
    model: ModelConfig,
    repetition: int,
    policy_sha256: str,
    round_id: str,
    contract_manifest_sha256: str,
    policy_descriptor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    state = {
        "schema_version": 3,
        "task": {
            "game": game.slug,
            "game_name": game.name,
            "model_id": model.id,
            "model_name": model.name,
            "provider": model.provider,
            "requested_model": model.model,
            "repetition": repetition,
            "region": "us-east-1",
        },
        "status": "pending",
        "policy_sha256": policy_sha256,
        "round_id": round_id,
        "contract_manifest_sha256": contract_manifest_sha256,
        "created_at": _now(),
        "stages": {
            "prompt": {"status": "pending"},
            "generation": {"status": "pending"},
            "evaluation": {"status": "pending"},
            "reporting": {"status": "pending"},
        },
    }
    if policy_descriptor is not None:
        state["policy_descriptor"] = policy_descriptor
    return state


def _set_stage(
    state: dict[str, Any],
    state_path: Path,
    stage: str,
    status: str,
    **values: Any,
) -> None:
    state["status"] = "running" if status in {"running", "completed"} else status
    record = state["stages"].setdefault(stage, {})
    if status in {"running", "completed"}:
        _clear_failure_metadata(record)
    record.update({"status": status, "updated_at": _now(), **values})
    _save_state(state_path, state)


def run_task(
    *,
    run_dir: Path,
    game: GameConfig,
    model: ModelConfig,
    repetition: int,
    config: dict[str, Any],
    round_id: str,
    round_dir: Path,
    contract_manifest_sha256: str,
    resume: bool,
    progress: Callable[[str], None] = print,
    experimental_single_model: str | None = None,
    selected_game_slugs: list[str] | None = None,
) -> dict[str, Any]:
    task_id = f"{game.slug}__{model.id}__r{repetition:02d}"
    task_dir = run_dir / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    state_path = task_dir / "run_state.json"
    round_manifest = validate_round_manifest(
        _read_json(round_dir / "contracts" / "manifest.json"),
        round_dir=round_dir,
        expected_slugs=[item.slug for item in games(config)],
    )
    if round_manifest.get("round_id") != round_id or round_manifest.get("manifest_sha256") != contract_manifest_sha256:
        raise ValueError("D4 round contract manifest hash drifted before candidate execution")
    task_policy_descriptor = _task_policy_descriptor(
        config,
        game,
        round_manifest,
        selected_game_slugs=selected_game_slugs,
    )
    task_policy_sha256 = sha256_json(task_policy_descriptor)
    state = (
        _read_json(state_path)
        if state_path.is_file()
        else _initial_task_state(
            game,
            model,
            repetition,
            task_policy_sha256,
            round_id,
            contract_manifest_sha256,
            task_policy_descriptor,
        )
    )
    validate_task_state(state)
    state["normalized_config_sha256"] = normalized_policy_sha256(config)
    if state.get("round_id") != round_id or state.get("contract_manifest_sha256") != contract_manifest_sha256:
        raise ValueError("Task belongs to a different D4 round contract manifest")
    if (
        state.get("policy_sha256") != task_policy_sha256
        or state.get("policy_descriptor") != task_policy_descriptor
    ):
        raise ValueError("Task evidence belongs to a different benchmark/Judge policy; use a new run ID")
    if state.get("status") == "completed" and resume and (task_dir / "summary.json").is_file():
        _clear_failure_metadata(state)
        _clear_terminal_failure_metadata(state)
        _archive_resolved_failure(task_dir)
        _save_state(state_path, state)
        progress(f"[skip] {task_id} already completed")
        return _read_json(task_dir / "summary.json")

    try:
        prompt_bundle: dict[str, Any]
        prompt_stage = state["stages"].get("prompt", {})
        contract_manifest = (
            task_dir / "generation" / "contract" / "generation_contract_manifest.json"
        )
        if prompt_stage.get("status") == "completed" and contract_manifest.is_file():
            prompt_bundle = _read_json(contract_manifest)
            locked_contract_hash = str(
                prompt_stage.get("generation_contract_sha256", "")
            )
            if prompt_bundle.get("generation_contract_sha256") != locked_contract_hash:
                raise ValueError("Generation contract changed after it was locked")
        else:
            _set_stage(state, state_path, "prompt", "running")
            prompt_bundle = _render_prompt_contract(
                game,
                task_dir / "generation" / "contract",
                dict(config["generation"]),
            )
            _set_stage(
                state,
                state_path,
                "prompt",
                "completed",
                generation_contract_sha256=prompt_bundle[
                    "generation_contract_sha256"
                ],
            )

        candidate_project = CandidateProject(task_dir / "candidate")
        generation_stage = state["stages"].get("generation", {})
        if generation_stage.get("status") == "completed":
            locked_hash = str(generation_stage.get("project_sha256", ""))
            actual_hash = candidate_project.project_sha256()
            if not locked_hash or actual_hash != locked_hash:
                raise ValueError("Candidate project changed after generation")
            progress(f"[locked] {task_id} generation {actual_hash[:12]}")
        else:
            _set_stage(state, state_path, "generation", "running")
            candidate_project = generate_candidate_project(
                game=game,
                model=model,
                task_dir=task_dir,
                config=config,
                resume=resume,
                progress=progress,
            )
            project_hash = candidate_project.project_sha256()
            _set_stage(
                state,
                state_path,
                "generation",
                "completed",
                project_sha256=project_hash,
                generation_contract_sha256=prompt_bundle[
                    "generation_contract_sha256"
                ],
            )
            progress(f"[generated] {task_id} {project_hash[:12]}")

        _set_stage(state, state_path, "evaluation", "running")
        judge_config = config["judge"]
        evaluation_config = config["evaluation"]
        result = evaluate_candidate(
            game=game,
            model_id=model.id,
            repetition=repetition,
            project=candidate_project,
            task_dir=task_dir,
            region=str(config["region"]),
            judge_config=judge_config,
            d2_workers=int(evaluation_config["d2_workers"]),
            sampling_timeout_seconds=int(evaluation_config["sampling_timeout_seconds"]),
            runtime_protocol=task_policy_descriptor["runtime_protocol"],
            experimental_single_model=experimental_single_model,
            round_dir=round_dir,
            contract_manifest_sha256=contract_manifest_sha256,
            config=config,
        )
        evaluation_status = (
            "needs_rescore" if result.get("status") == "needs_rescore" else "completed"
        )
        _set_stage(state, state_path, "evaluation", evaluation_status)

        _set_stage(state, state_path, "reporting", "running")
        from code2play.reporting.reports import write_task_reports

        write_task_reports(task_dir, result)
        _set_stage(state, state_path, "reporting", "completed")
        state.update(
            {
                "status": result.get("status", "completed"),
                "finished_at": _now(),
                "official_total": result.get("official_total"),
            }
        )
        _clear_failure_metadata(state)
        _clear_terminal_failure_metadata(state)
        _archive_resolved_failure(task_dir)
        _save_state(state_path, state)
        progress(
            f"[{result.get('status', 'completed')}] {task_id} "
            f"total={result.get('official_total')}"
        )
        return result
    except BaseException as exc:
        terminal_failure = _is_terminal_candidate_failure(exc)
        active = next(
            (
                name
                for name, record in state.get("stages", {}).items()
                if record.get("status") == "running"
            ),
            "unknown",
        )
        state.update(
            {
                "status": "failed",
                "failed_at": _now(),
                "failed_stage": active,
                "terminal_failure": terminal_failure,
                "terminal_failure_policy_version": TERMINAL_FAILURE_POLICY_VERSION,
            }
        )
        if active in state.get("stages", {}):
            state["stages"][active].update(
                {"status": "failed", "error_type": type(exc).__name__, "error": redact_text(str(exc))}
            )
        _save_state(state_path, state)
        write_json(
            task_dir / "failure.json",
            {
                "task_id": task_id,
                "stage": active,
                "error_type": type(exc).__name__,
                "error": redact_text(str(exc)),
                "traceback": redact_text(traceback.format_exc()),
                "timestamp": _now(),
                "candidate_locked": state["stages"].get("generation", {}).get("status") == "completed",
                "project_sha256": state["stages"].get("generation", {}).get("project_sha256"),
                "terminal_failure": terminal_failure,
                "terminal_failure_policy_version": TERMINAL_FAILURE_POLICY_VERSION,
            },
        )
        progress(f"[failed] {task_id} at {active}: {type(exc).__name__}: {redact_text(str(exc))}")
        raise


@_serialized_benchmark
def run_benchmark(
    *,
    repetitions: int = 1,
    resume: bool = True,
    run_id: str = DEFAULT_RUN_ID,
    config_path: str | Path | None = None,
    workspace: str | Path | None = None,
    round_id: str | None = None,
    game_slug: str | None = None,
    progress: Callable[[str], None] = print,
) -> dict[str, Any]:
    config = load_config(config_path) if config_path else load_config()
    if repetitions != 1:
        raise ValueError("This locked benchmark requires exactly one repetition")
    require_locked_runtime_policy(config)
    workspace_root = resolve_workspace(workspace)
    run_dir = workspace_run_dir(workspace_root, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    configured_games = games(config)
    selected_games = configured_games
    if game_slug is not None:
        selected_games = [game for game in configured_games if game.slug == game_slug]
        if not selected_games:
            raise ValueError(f"Unknown configured game: {game_slug}")
    existing_batch_state_path = run_dir / "run_state.json"
    existing_batch_state = (
        _read_json(existing_batch_state_path)
        if resume and existing_batch_state_path.is_file()
        else None
    )
    if existing_batch_state is not None:
        validate_batch_state(existing_batch_state)
    required_api_keys = {
        str(resolve_judge_route(config["judge"], role).get("api_key_env") or (
            "DASHSCOPE_API_KEY"
            if resolve_judge_route(config["judge"], role).get("provider") == "alibaba_dashscope"
            else "OPENROUTER_API_KEY"
        ))
        for role in config["judge"]["routes"]
    }
    missing_api_keys = sorted(name for name in required_api_keys if not os.getenv(name))
    if missing_api_keys:
        raise ValueError("Missing judge API key environment variable(s): " + ", ".join(missing_api_keys))
    active_round_id = str(existing_batch_state.get("round_id")) if existing_batch_state and existing_batch_state.get("round_id") else (round_id or f"{run_id}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}")
    round_dir = workspace_round_dir(workspace_root, active_round_id)
    round_manifest = build_round_contracts(
        round_dir,
        configured_games,
        config=config,
        round_id=active_round_id,
    )
    contract_manifest_sha256 = str(round_manifest["manifest_sha256"])
    batch_state_path = run_dir / "run_state.json"
    batch_policy_descriptor = _batch_policy_descriptor(
        config,
        round_manifest,
        selected_game_slugs=(
            [game.slug for game in selected_games] if game_slug is not None else None
        ),
    )
    batch_policy_sha256 = sha256_json(batch_policy_descriptor)
    matrix = [
        {
            "game": game.slug,
            "model": model.id,
            "repetition": repetition,
            "task_id": f"{game.slug}__{model.id}__r{repetition:02d}",
            "status": "pending",
            "round_id": active_round_id,
            "contract_manifest_sha256": contract_manifest_sha256,
            "d4_contract": _d4_contract_policy(config, round_manifest).get(game.slug),
        }
        for game in selected_games
        for model in models(config)
        for repetition in range(1, repetitions + 1)
    ]
    batch_state = (
        _read_json(batch_state_path)
        if resume and batch_state_path.is_file()
        else {
            "schema_version": 3,
            "run_id": run_id,
            "round_id": active_round_id,
            "contract_manifest_sha256": contract_manifest_sha256,
            "created_at": _now(),
            "status": "running",
            "region": config["region"],
            "repetitions": repetitions,
            "policy_sha256": batch_policy_sha256,
            "normalized_config_sha256": normalized_policy_sha256(config),
            "policy_descriptor": batch_policy_descriptor,
            "d4_contracts": _d4_contract_policy(config, round_manifest),
            "matrix": matrix,
        }
    )
    validate_batch_state(batch_state)
    if batch_state.get("schema_version") != 3 or batch_state.get("round_id") != active_round_id or batch_state.get("contract_manifest_sha256") != contract_manifest_sha256:
        raise ValueError("Existing batch belongs to a different D4 round; use a new run ID")
    if (
        batch_state.get("policy_sha256") != batch_policy_sha256
        or batch_state.get("policy_descriptor") != batch_policy_descriptor
    ):
        raise ValueError("Existing batch belongs to a different benchmark/Judge policy; use a new run ID")
    batch_state["status"] = "running"
    for key in ("finished_at", "completed_count", "failed_count"):
        batch_state.pop(key, None)
    records_by_id = {item["task_id"]: item for item in batch_state["matrix"]}
    results: list[dict[str, Any]] = []
    _save_state(batch_state_path, batch_state)

    for game in selected_games:
        for model in models(config):
            for repetition in range(1, repetitions + 1):
                task_id = f"{game.slug}__{model.id}__r{repetition:02d}"
                record = records_by_id[task_id]
                if (
                    resume
                    and record.get("status") == "failed"
                    and _has_current_terminal_failure(record)
                ):
                    progress(f"[skip-terminal] {task_id} candidate protocol failure")
                    _save_state(batch_state_path, batch_state)
                    continue
                _clear_failure_metadata(record)
                _clear_terminal_failure_metadata(record)
                record.update({"status": "running", "started_at": _now()})
                _save_state(batch_state_path, batch_state)
                try:
                    result = run_task(
                        run_dir=run_dir,
                        game=game,
                        model=model,
                        repetition=repetition,
                        config=config,
                        round_id=active_round_id,
                        round_dir=round_dir,
                        contract_manifest_sha256=contract_manifest_sha256,
                        resume=resume,
                        progress=progress,
                        selected_game_slugs=(
                            [item.slug for item in selected_games]
                            if game_slug is not None
                            else None
                        ),
                    )
                    record.update(
                        {
                            "status": result.get("status", "completed"),
                            "finished_at": _now(),
                            "official_total": result.get("official_total"),
                        }
                    )
                    _clear_failure_metadata(record)
                    _clear_terminal_failure_metadata(record)
                    results.append(result)
                except BaseException as exc:
                    terminal_failure = _is_terminal_candidate_failure(exc)
                    record.update(
                        {
                            "status": "failed",
                            "finished_at": _now(),
                            "error_type": type(exc).__name__,
                            "error": redact_text(str(exc)),
                            "terminal_failure": terminal_failure,
                            "terminal_failure_policy_version": (
                                TERMINAL_FAILURE_POLICY_VERSION
                            ),
                        }
                    )
                _save_state(batch_state_path, batch_state)

    batch_state["status"] = (
        "completed_with_judge_gaps"
        if any(item["status"] == "needs_rescore" for item in batch_state["matrix"])
        else "completed"
    )
    batch_state["finished_at"] = _now()
    batch_state["completed_count"] = sum(item["status"] == "completed" for item in batch_state["matrix"])
    batch_state["failed_count"] = sum(item["status"] == "failed" for item in batch_state["matrix"])
    batch_state["needs_rescore_count"] = sum(
        item["status"] == "needs_rescore" for item in batch_state["matrix"]
    )
    _save_state(batch_state_path, batch_state)
    from code2play.reporting.reports import write_batch_reports, write_failure_reports

    write_failure_reports(run_dir, batch_state["matrix"])
    write_batch_reports(run_dir, batch_state["matrix"])
    leaks = scan_for_secret_leaks(run_dir)
    write_json(run_dir / "secret_scan.json", {"status": "passed" if not leaks else "failed", "hits": leaks})
    if leaks:
        raise RuntimeError("Credential leak scan failed; see secret_scan.json")
    return batch_state


def prepare_manual_project(source: str | Path, task_dir: str | Path) -> CandidateProject:
    source_project = CandidateProject(Path(source).resolve())
    source_project.assert_safe_structure()
    target_dir = Path(task_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "candidate"
    if target.is_dir() and any(target.iterdir()):
        locked = CandidateProject(target)
        locked.assert_safe_structure()
        if locked.project_sha256() != source_project.project_sha256():
            raise ValueError("Manual task already contains a different locked project")
        return locked
    source_project.copy_to_isolated(target)
    return CandidateProject(target)
