from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
import shutil
import subprocess
import sys
from threading import Thread
from typing import Any, Callable

from code2play.execution.candidate_project import CandidateProject

from code2play.generation.prompt_builder import load_spec

from code2play.evaluation.checkpoint_compiler import (
    compile_checkpoint_program_batch,
    compile_checkpoint_program_once,
    normalize_compiled_program,
    same_state_schema,
    state_schema,
)
from code2play.d4.compiler import compile_visual_program, normalize_visual_program
from code2play.providers.dashscope import SemanticJudge
from code2play.d4.visual_difference import (
    VISUAL_DIFFERENCE_POLICY,
    analyze_visual_difference,
    select_materially_distinct_frames,
)

RPC_WORKER_PATH = Path(__file__).with_name("protocol_rpc_worker.py")
_COMPILER_ATTEMPT_PURPOSE = re.compile(r"^(?P<base>.+)_attempt_\d{2}$")
VISUAL_DISTINCTNESS_PROBE_DELAYS_SECONDS = (0.15, 0.35, 0.5)
VISUAL_DISTINCTNESS_POLICY = "deterministic_post_measurement_time_probe_v2"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _distinct_visual_hashes(frames: list[dict[str, Any]]) -> set[str]:
    hashes: set[str] = set()
    for frame in frames:
        image_sha256 = frame.get("image_sha256")
        if isinstance(image_sha256, str) and image_sha256:
            hashes.add(image_sha256)
            continue
        path_value = frame.get("path")
        if isinstance(path_value, str):
            path = Path(path_value)
            if path.is_file():
                hashes.add(_file_sha256(path))
    return hashes


def _isolated_worker_python() -> str:
    """Select an interpreter whose isolated mode contains pygame."""
    configured = os.getenv("CODE2PLAY_PYTHON")
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path(sys.executable),
        Path(__file__).resolve().parents[1] / ".venv" / "Scripts" / "python.exe",
        Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python",
    ]
    checked: list[str] = []
    for candidate in candidates:
        if candidate is None or not candidate.is_file():
            continue
        resolved = str(candidate.resolve())
        if resolved in checked:
            continue
        checked.append(resolved)
        probe = subprocess.run(
            [resolved, "-I", "-B", "-c", "import pygame"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        if probe.returncode == 0:
            return resolved
    raise RuntimeError(
        "No isolated Python interpreter can import pygame. Run with the project "
        "environment or set CODE2PLAY_PYTHON to a Python executable with pygame installed; "
        f"checked: {checked}"
    )


def load_evaluation_contract(spec_path: Path | str) -> dict[str, Any]:
    spec = load_spec(spec_path)
    contract = spec.get("evaluation")
    if not isinstance(contract, dict):
        raise ValueError(f"{spec_path} does not define an evaluation contract")
    return json.loads(json.dumps(contract, ensure_ascii=False))



class _CandidateRpc:
    """Run candidate code without revealing D2 checkpoint ids or scoring data."""

    def __init__(
        self,
        project: CandidateProject,
        *,
        cwd: Path,
        stderr_path: Path,
        timeout_sec: int,
    ) -> None:
        self.timeout_sec = timeout_sec
        self.request_index = 0
        self.transcript: list[dict[str, Any]] = []
        self.stderr_path = stderr_path
        cwd.mkdir(parents=True, exist_ok=True)
        isolated_worker = cwd / "_gamebench_rpc_worker.py"
        isolated_project = cwd / "candidate"
        shutil.copyfile(RPC_WORKER_PATH, isolated_worker)
        project.copy_to_isolated(isolated_project)
        candidate_env = {
            key: os.environ[key]
            for key in (
                "COMSPEC",
                "PATH",
                "PATHEXT",
                "SYSTEMROOT",
                "TEMP",
                "TMP",
                "WINDIR",
            )
            if key in os.environ
        }
        candidate_env.update(
            {
                "PYTHONDONTWRITEBYTECODE": "1",
                "SDL_VIDEODRIVER": "dummy",
                "SDL_AUDIODRIVER": "dummy",
            }
        )
        worker_python = _isolated_worker_python()
        self._stderr_handle = stderr_path.open("w", encoding="utf-8")
        try:
            self.process = subprocess.Popen(
                [
                    worker_python,
                    "-I",
                    "-B",
                    str(isolated_worker),
                    "--project",
                    str(isolated_project),
                ],
                cwd=str(cwd),
                env=candidate_env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self._stderr_handle,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except Exception:
            self._stderr_handle.close()
            raise
        if self.process.stdin is None or self.process.stdout is None:
            self.process.terminate()
            self._stderr_handle.close()
            raise RuntimeError("Could not create candidate RPC pipes")
        self._responses: Queue[str | None] = Queue()
        self._reader = Thread(target=self._read_stdout, daemon=True)
        self._reader.start()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self._responses.put(line)
        self._responses.put(None)

    def _stderr_tail(self) -> str:
        try:
            self._stderr_handle.flush()
        except (OSError, ValueError):
            pass
        try:
            text = self.stderr_path.read_text(
                encoding="utf-8",
                errors="replace",
            ).strip()
        except OSError:
            return ""
        if not text:
            return ""
        tail = "\n".join(text.splitlines()[-12:])
        if len(tail) > 2000:
            tail = "..." + tail[-2000:]
        return tail

    def _closed_error(self, operation: str) -> RuntimeError:
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        message = (
            f"Candidate RPC closed during {operation!r}; "
            f"exit={self.process.poll()}"
        )
        stderr_tail = self._stderr_tail()
        if stderr_tail:
            message += f"; worker stderr tail:\n{stderr_tail}"
        return RuntimeError(message)

    def call(self, operation: str, **payload: Any) -> Any:
        if self.process.poll() is not None:
            raise self._closed_error(operation)
        self.request_index += 1
        request = {
            "request_id": self.request_index,
            "op": operation,
            **payload,
        }
        assert self.process.stdin is not None
        try:
            self.process.stdin.write(
                json.dumps(request, ensure_ascii=False) + "\n"
            )
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise self._closed_error(operation) from exc
        try:
            raw_response = self._responses.get(timeout=self.timeout_sec)
        except Empty as exc:
            self.process.kill()
            raise RuntimeError(f"Candidate RPC timed out during {operation!r}") from exc
        if raw_response is None:
            raise self._closed_error(operation)
        response = json.loads(raw_response)
        self.transcript.append({"request": request, "response": response})
        if response.get("request_id") != self.request_index:
            raise RuntimeError("Candidate RPC returned a mismatched request id")
        if not response.get("ok"):
            error = response.get("error", {})
            raise RuntimeError(
                f"Candidate RPC {operation!r} failed: "
                f"{error.get('type')}: {error.get('message')}"
            )
        return response.get("result")

    def close(self) -> None:
        if self.process.poll() is None:
            try:
                self.call("close")
            except Exception:
                self.process.kill()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        if self.process.stdin is not None:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        if self.process.stdout is not None:
            try:
                self.process.stdout.close()
            except OSError:
                pass
        try:
            self._stderr_handle.close()
        except OSError:
            pass



def _protocol_audit(rpc: _CandidateRpc, seed: int) -> dict[str, Any]:
    """Verify the minimal init/snapshot/action state contract."""
    initialized = rpc.call("init", seed=seed)
    snapshot_after_init = rpc.call("snapshot")
    stable_snapshot = rpc.call("snapshot")
    initial_schema = state_schema(initialized)
    noop_command = {
        "keys_down": [],
        "keys_up": [],
        "held_keys": [],
        "mouse_position": None,
        "mouse_buttons_down": [],
        "mouse_buttons_up": [],
        "dt": 0.0,
    }
    action_state = rpc.call("action", command=noop_command)
    snapshot_after_action = rpc.call("snapshot")
    schema_consistent = same_state_schema(initialized, snapshot_after_action)
    passed = (
        initialized == snapshot_after_init
        and snapshot_after_init == stable_snapshot
        and action_state == snapshot_after_action
        and schema_consistent
    )
    reasons: list[str] = []
    if initialized != snapshot_after_init:
        reasons.append("init() must return the immediate snapshot() state")
    if snapshot_after_init != stable_snapshot:
        reasons.append("snapshot() must not mutate game state")
    if action_state != snapshot_after_action:
        reasons.append("action() must return the immediate snapshot() state")
    if not schema_consistent:
        reasons.append("init() and post-action snapshot() schemas differ")
    return {
        "passed": passed,
        "reason": "minimal state contract satisfied" if passed else "; ".join(reasons),
        "initialized": initialized,
        "snapshot_after_init": snapshot_after_init,
        "snapshot_stable": snapshot_after_init == stable_snapshot,
        "noop_action": noop_command,
        "action_state_matches_snapshot": action_state == snapshot_after_action,
        "snapshot_after_action": snapshot_after_action,
        "state_schema": initial_schema,
        "schema_consistent": schema_consistent,
    }



def _resolve_d2_worker_count(requested: int | None, checkpoint_count: int) -> int:
    if checkpoint_count < 1:
        raise ValueError("D2 plan must contain at least one checkpoint")
    if requested is None:
        configured = os.getenv("CODE2PLAY_D2_WORKERS")
        if configured:
            try:
                requested = int(configured)
            except ValueError as exc:
                raise ValueError(
                    "CODE2PLAY_D2_WORKERS must be a positive integer"
                ) from exc
        else:
            requested = min(4, os.cpu_count() or 1)
    if isinstance(requested, bool) or not isinstance(requested, int) or requested < 1:
        raise ValueError("d2_max_workers must be a positive integer")
    return min(requested, checkpoint_count)


def _load_validated_compiler_cache(
    *,
    compiler: SemanticJudge,
    normalizers: dict[str, Callable[[Any], dict[str, Any]]],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Reuse prior stateless compiler calls that pass current validation."""

    raw_log_dir = getattr(compiler, "log_dir", None)
    if raw_log_dir is None:
        return {}, {}
    log_dir = Path(raw_log_dir).resolve()
    current_attempt = log_dir.parent
    evidence_root = current_attempt.parent
    if (
        log_dir.name != "compiler_llm_calls"
        or not current_attempt.name.startswith("sampling_attempt_")
        or not evidence_root.is_dir()
    ):
        return {}, {}

    cached: dict[str, dict[str, Any]] = {}
    sources: dict[str, str] = {}
    prior_attempts = sorted(
        (
            path
            for path in evidence_root.glob("sampling_attempt_*")
            if path.is_dir() and path.resolve() != current_attempt.resolve()
        ),
        key=lambda path: path.name,
        reverse=True,
    )
    for attempt_dir in prior_attempts:
        calls_dir = attempt_dir / "compiler_llm_calls"
        if not calls_dir.is_dir():
            continue
        call_dirs = sorted(
            calls_dir.iterdir(),
            key=lambda path: path.name,
            reverse=True,
        )
        for call_dir in call_dirs:
            if not call_dir.is_dir():
                continue
            input_path = call_dir / "raw_input.json"
            parsed_path = call_dir / "parsed_output.json"
            if not input_path.is_file() or not parsed_path.is_file():
                continue
            try:
                request = json.loads(input_path.read_text(encoding="utf-8"))
                match = _COMPILER_ATTEMPT_PURPOSE.fullmatch(
                    str(request.get("purpose", ""))
                )
                base_purpose = match.group("base") if match else ""
                normalize = normalizers.get(base_purpose)
                if normalize is None or base_purpose in cached:
                    continue
                parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
                cached[base_purpose] = normalize(parsed)
                sources[base_purpose] = str(parsed_path.resolve())
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue

    if cached:
        log_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": 1,
            "strategy": "reuse_prior_validated_stateless_compiler_output",
            "entries": [
                {"purpose": purpose, "source": sources[purpose]}
                for purpose in sorted(cached)
            ],
        }
        (log_dir / "cache_reuse_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return cached, sources


def _compile_checkpoint_programs(
    *,
    checkpoints: list[dict[str, Any]],
    game_description: str,
    functional_requirements: list[dict[str, Any]],
    candidate_source: str,
    initial_snapshot: dict[str, Any],
    initial_schema: dict[str, Any],
    compiler: SemanticJudge,
    max_workers: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    programs_by_index: dict[int, dict[str, Any]] = {}
    normalizers = {
        f"d2_compile_{checkpoint['id']}": (
            lambda raw, checkpoint=checkpoint: normalize_compiled_program(
                raw, checkpoint
            )
        )
        for checkpoint in checkpoints
    }
    cached, cache_sources = _load_validated_compiler_cache(
        compiler=compiler,
        normalizers=normalizers,
    )
    missing: list[tuple[int, dict[str, Any]]] = []
    for index, checkpoint in enumerate(checkpoints):
        purpose = f"d2_compile_{checkpoint['id']}"
        if purpose in cached:
            programs_by_index[index] = cached[purpose]
        else:
            missing.append((index, checkpoint))

    batches: list[tuple[str, list[tuple[int, dict[str, Any]]]]] = []
    for dimension in ("D2.1", "D2.2", "D2.3", "D2.4", "D2.5"):
        dimension_rows = [row for row in missing if row[1]["dimension"] == dimension]
        for start in range(0, len(dimension_rows), 8):
            rows = dimension_rows[start : start + 8]
            batches.append((f"{dimension}_{start // 8 + 1:02d}", rows))

    effective_workers = _resolve_d2_worker_count(max_workers, len(batches)) if batches else 0
    repair_rows: list[tuple[int, dict[str, Any]]] = []
    if batches:
        with ThreadPoolExecutor(max_workers=effective_workers, thread_name_prefix="gamebench-d2-compiler-batch") as executor:
            futures = {
                executor.submit(
                    compile_checkpoint_program_batch,
                    [checkpoint for _index, checkpoint in rows],
                    game_description=game_description,
                    functional_requirements=functional_requirements,
                    candidate_source=candidate_source,
                    initial_snapshot=initial_snapshot,
                    initial_schema=initial_schema,
                    compiler=compiler,
                    batch_id=batch_id,
                ): (batch_id, rows)
                for batch_id, rows in batches
            }
            for future in as_completed(futures):
                batch_id, rows = futures[future]
                try:
                    valid, repair_ids = future.result()
                except Exception as exc:
                    for pending in futures:
                        pending.cancel()
                    raise RuntimeError(f"Evaluator-side LLM failed to compile batch {batch_id}") from exc
                index_by_id = {checkpoint["id"]: index for index, checkpoint in rows}
                checkpoint_by_id = {checkpoint["id"]: checkpoint for _index, checkpoint in rows}
                for checkpoint_id, program in valid.items():
                    programs_by_index[index_by_id[checkpoint_id]] = program
                repair_rows.extend((index_by_id[item], checkpoint_by_id[item]) for item in repair_ids)

    for index, checkpoint in repair_rows:
        try:
            programs_by_index[index] = compile_checkpoint_program_once(
                checkpoint,
                game_description=game_description,
                functional_requirements=functional_requirements,
                candidate_source=candidate_source,
                initial_snapshot=initial_snapshot,
                initial_schema=initial_schema,
                compiler=compiler,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Evaluator-side LLM failed to repair D2 checkpoint {checkpoint['id']}"
            ) from exc

    programs = [programs_by_index[index] for index in range(len(checkpoints))]
    return programs, {
        "strategy": "parallel_dimension_batches_with_single_item_repair_v1",
        "effective_workers": effective_workers,
        "checkpoint_count": len(checkpoints),
        "base_batch_count": len(batches),
        "max_checkpoints_per_batch": 8,
        "repair_count": len(repair_rows),
        "repair_checkpoint_ids": [checkpoint["id"] for _index, checkpoint in repair_rows],
        "reused_validated_count": len(cached),
        "newly_compiled_count": len(missing),
        "cache_sources": cache_sources,
        "result_order": "checkpoint_contract_order",
    }


def _compile_d4_programs(
    *,
    d2_checkpoints: list[dict[str, Any]],
    d4_contract: dict[str, Any],
    game_description: str,
    functional_requirements: list[dict[str, Any]],
    candidate_source: str,
    initial_snapshot: dict[str, Any],
    initial_schema: dict[str, Any],
    compiler: SemanticJudge,
    max_workers: int,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    transition_tasks = [
        {
            "id": checkpoint["id"],
            "task_type": "d4_2_transition",
            "textual_checkpoint": {
                key: checkpoint[key]
                for key in (
                    "id",
                    "dimension",
                    "item",
                    "objective",
                    "initial_state",
                    "trigger",
                    "expected_transition",
                )
                if key in checkpoint
            },
        }
        for checkpoint in d2_checkpoints
        if checkpoint.get("kind") == "dynamic"
    ]
    if not transition_tasks:
        raise ValueError("D4.2 requires at least one dynamic D2 checkpoint")
    tagged_tasks = [
        ("d4_2", index, task) for index, task in enumerate(transition_tasks)
    ]
    programs: dict[str, dict[int, dict[str, Any]]] = {
        "d4_2": {},
    }
    normalizers = {
        f"d4_compile_{task['task_type']}_{task['id']}": (
            lambda raw, task=task: normalize_visual_program(raw, task)
        )
        for _group, _index, task in tagged_tasks
    }
    cached, cache_sources = _load_validated_compiler_cache(
        compiler=compiler,
        normalizers=normalizers,
    )
    missing: list[tuple[str, int, dict[str, Any]]] = []
    for group, index, task in tagged_tasks:
        purpose = f"d4_compile_{task['task_type']}_{task['id']}"
        if purpose in cached:
            programs[group][index] = cached[purpose]
        else:
            missing.append((group, index, task))

    effective_workers = (
        _resolve_d2_worker_count(max_workers, len(missing)) if missing else 0
    )
    if missing:
        with ThreadPoolExecutor(
            max_workers=effective_workers,
            thread_name_prefix="gamebench-d4-compiler",
        ) as executor:
            futures = {
                executor.submit(
                    compile_visual_program,
                    task,
                    game_description=game_description,
                    functional_requirements=functional_requirements,
                    candidate_source=candidate_source,
                    initial_snapshot=initial_snapshot,
                    initial_schema=initial_schema,
                    compiler=compiler,
                ): (group, index, task["id"])
                for group, index, task in missing
            }
            try:
                for future in as_completed(futures):
                    group, index, task_id = futures[future]
                    try:
                        programs[group][index] = future.result()
                    except Exception as exc:
                        for pending in futures:
                            pending.cancel()
                        raise RuntimeError(
                            f"Evaluator-side LLM failed to compile {group} task "
                            f"{task_id}"
                        ) from exc
            finally:
                for future in futures:
                    future.cancel()

    ordered = {
        "d4_2": [programs["d4_2"][index] for index in range(len(transition_tasks))],
        "d4_3": [],
    }
    return ordered, {
        "strategy": "parallel_evaluator_llm_d4_2_transition_compilation",
        "effective_workers": effective_workers,
        "d4_2_dynamic_checkpoint_count": len(transition_tasks),
        "d4_3_scene_count": 0,
        "d4_3_strategy": "reuse_real_d4_2_d2_2_evidence",
        "d4_2_selection": "kind_dynamic_only",
        "reused_validated_count": len(cached),
        "newly_compiled_count": len(missing),
        "cache_sources": cache_sources,
        "result_order": "dynamic_d2_checkpoint_order",
    }


def _sample_one_compiled_checkpoint(
    *,
    worker_index: int,
    project: CandidateProject,
    checkpoint: dict[str, Any],
    program: dict[str, Any],
    seed: int,
    sample_dir: Path,
    timeout_sec: int,
) -> tuple[int, dict[str, Any], dict[str, Any]]:
    """Execute one finite evaluator-compiled program against a fresh game."""
    worker_name = f"d2_worker_{worker_index:03d}"
    worker_root = sample_dir / "candidate_workers" / worker_name
    candidate_cwd = worker_root / "cwd"
    candidate_cwd.mkdir(parents=True, exist_ok=True)
    rpc = _CandidateRpc(
        project,
        cwd=candidate_cwd,
        stderr_path=worker_root / "stderr.txt",
        timeout_sec=timeout_sec,
    )
    case_records: list[dict[str, Any]] = []
    visual_frames: list[dict[str, Any]] = []
    visual_errors: list[dict[str, Any]] = []
    sampling_error: dict[str, str] | None = None

    def capture_frame(
        *,
        case_index: int,
        case_name: str,
        phase: str,
        offset_seconds: float,
        snapshot: dict[str, Any],
    ) -> bool:
        frame_dir = candidate_cwd / "visual_frames" / f"case_{case_index:03d}"
        path = frame_dir / f"frame_{len(visual_frames):03d}.png"
        try:
            frame_dir.mkdir(parents=True, exist_ok=True)
            rendered_path = _render_frame(rpc, path)
            visual_frames.append(
                {
                    "path": rendered_path,
                    "case": case_name,
                    "phase": phase,
                    "offset_seconds": round(offset_seconds, 6),
                    "snapshot": snapshot,
                    "image_sha256": _file_sha256(Path(rendered_path)),
                }
            )
            return True
        except Exception as exc:
            visual_errors.append(
                {
                    "case": case_name,
                    "phase": phase,
                    "offset_seconds": round(offset_seconds, 6),
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
            )
            return False
    try:
        for case_index, case in enumerate(program["cases"]):
            initialized = rpc.call("init", seed=seed + case_index)
            before = rpc.call("snapshot")
            elapsed = 0.0
            case_frame_start = len(visual_frames)
            visual_probe = {
                "policy": VISUAL_DISTINCTNESS_POLICY,
                "visual_difference_policy": VISUAL_DIFFERENCE_POLICY,
                "status": "not_applicable_static",
                "attempts": [],
                "distinct_image_count_before": 0,
                "distinct_image_count_after": 0,
                "materially_distinct_image_count_before": 0,
                "materially_distinct_image_count_after": 0,
            }
            if checkpoint.get("kind") == "dynamic":
                capture_frame(
                    case_index=case_index,
                    case_name=case["name"],
                    phase="before",
                    offset_seconds=elapsed,
                    snapshot=before,
                )
            observations: list[dict[str, Any]] = []
            for operation_index, operation in enumerate(case["actions"]):
                for repetition in range(operation["repeat"]):
                    action_state = rpc.call(
                        "action",
                        command=operation["command"],
                    )
                    elapsed += float(operation["command"].get("dt", 0.0))
                    if operation["capture_each"]:
                        snapshot = rpc.call("snapshot")
                        observations.append(
                            {
                                "operation_index": operation_index,
                                "repetition": repetition,
                                "command": operation["command"],
                                "action_state": action_state,
                                "snapshot": snapshot,
                            }
                        )
                        if checkpoint.get("kind") == "dynamic":
                            capture_frame(
                                case_index=case_index,
                                case_name=case["name"],
                                phase="transition",
                                offset_seconds=elapsed,
                                snapshot=snapshot,
                            )
            after = rpc.call("snapshot")
            if checkpoint.get("kind") == "dynamic":
                capture_frame(
                    case_index=case_index,
                    case_name=case["name"],
                    phase="after",
                    offset_seconds=elapsed,
                    snapshot=after,
                )
                case_frames = visual_frames[case_frame_start:]
                distinct_before = len(_distinct_visual_hashes(case_frames))
                material_before = len(select_materially_distinct_frames(case_frames))
                visual_probe["distinct_image_count_before"] = distinct_before
                visual_probe["materially_distinct_image_count_before"] = (
                    material_before
                )
                if not case_frames:
                    visual_probe["status"] = "not_run_no_rendered_frame"
                elif material_before >= 2:
                    visual_probe["status"] = (
                        "not_needed_already_materially_distinct"
                    )
                else:
                    visual_probe["status"] = (
                        "completed_frames_still_near_duplicate"
                    )
                    for probe_dt in VISUAL_DISTINCTNESS_PROBE_DELAYS_SECONDS:
                        probe_command = {
                            "keys_down": [],
                            "keys_up": [],
                            "held_keys": [],
                            "mouse_position": None,
                            "mouse_buttons_down": [],
                            "mouse_buttons_up": [],
                            "dt": probe_dt,
                        }
                        attempt = {
                            "dt": probe_dt,
                            "offset_seconds": round(elapsed + probe_dt, 6),
                        }
                        try:
                            rpc.call("action", command=probe_command)
                            elapsed += probe_dt
                            probe_snapshot = rpc.call("snapshot")
                            attempt["rendered"] = capture_frame(
                                case_index=case_index,
                                case_name=case["name"],
                                phase="visual_probe",
                                offset_seconds=elapsed,
                                snapshot=probe_snapshot,
                            )
                            if attempt["rendered"]:
                                newest = visual_frames[-1]
                                attempt["difference_from_first_frame"] = (
                                    analyze_visual_difference(
                                        visual_frames[case_frame_start]["path"],
                                        newest["path"],
                                    )
                                )
                        except Exception as exc:
                            attempt.update(
                                {
                                    "rendered": False,
                                    "error_type": type(exc).__name__,
                                    "error_message": str(exc),
                                }
                            )
                            visual_errors.append(
                                {
                                    "case": case["name"],
                                    "phase": "visual_probe",
                                    "offset_seconds": round(elapsed + probe_dt, 6),
                                    "type": type(exc).__name__,
                                    "message": str(exc),
                                }
                            )
                            visual_probe["attempts"].append(attempt)
                            visual_probe["status"] = "probe_action_failed"
                            break
                        visual_probe["attempts"].append(attempt)
                        case_frames = visual_frames[case_frame_start:]
                        if len(select_materially_distinct_frames(case_frames)) >= 2:
                            visual_probe["status"] = (
                                "completed_materially_distinct_frame_obtained"
                            )
                            break
                visual_probe["distinct_image_count_after"] = len(
                    _distinct_visual_hashes(visual_frames[case_frame_start:])
                )
                visual_probe["materially_distinct_image_count_after"] = len(
                    select_materially_distinct_frames(
                        visual_frames[case_frame_start:]
                    )
                )
            case_records.append(
                {
                    "case": case["name"],
                    "init_state": initialized,
                    "before": before,
                    "operations": case["actions"],
                    "observations": observations,
                    "after": after,
                    "schema_consistent": same_state_schema(initialized, after),
                    "visual_probe": visual_probe,
                }
            )
    except Exception as exc:
        sampling_error = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
    finally:
        rpc.close()
        (worker_root / "rpc_transcript.json").write_text(
            json.dumps(rpc.transcript, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    checkpoint_id = checkpoint["id"]
    record = {
        "id": checkpoint_id,
        "dimension": checkpoint["dimension"],
        "kind": checkpoint["kind"],
        "status": "sampling_failed" if sampling_error else "completed",
        "sampling_authority": "evaluator_llm_compiled_program",
        "candidate_received_checkpoint_id": False,
        "worker_index": worker_index,
        "compiled_program": program,
        "cases": case_records,
        "frames": visual_frames,
        "visual_probe_policy": (
            VISUAL_DISTINCTNESS_POLICY
            if checkpoint.get("kind") == "dynamic"
            else None
        ),
        "visual_distinct_image_count": len(_distinct_visual_hashes(visual_frames)),
        "visual_difference_policy": (
            VISUAL_DIFFERENCE_POLICY
            if checkpoint.get("kind") == "dynamic"
            else None
        ),
        "visual_materially_distinct_image_count": len(
            select_materially_distinct_frames(visual_frames)
        ),
        "visual_probe_summary": [
            {
                "case": case.get("case"),
                **case.get("visual_probe", {}),
            }
            for case in case_records
            if isinstance(case.get("visual_probe"), dict)
        ],
        "visual_status": (
            "completed"
            if visual_frames and not visual_errors
            else "partial_render_failure"
            if visual_frames
            else "unevaluable_render_failure"
            if checkpoint.get("kind") == "dynamic"
            else "not_applicable_static"
        ),
        "visual_errors": visual_errors,
    }
    if sampling_error:
        record["sampling_error"] = sampling_error
    transcript_record = {
        "worker_index": worker_index,
        "worker_name": worker_name,
        "status": record["status"],
        "sampling_error": sampling_error,
        "transcript_path": str((worker_root / "rpc_transcript.json").resolve()),
        "stderr_path": str((worker_root / "stderr.txt").resolve()),
        # The child sees normalized physical commands, never checkpoint text/id.
        "rpc": rpc.transcript,
    }
    return worker_index, record, transcript_record


def _sample_compiled_d2_parallel(
    *,
    project: CandidateProject,
    checkpoints: list[dict[str, Any]],
    programs: list[dict[str, Any]],
    seed: int,
    sample_dir: Path,
    timeout_sec: int,
    d2_max_workers: int | None,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    if len(checkpoints) != len(programs):
        raise ValueError("Compiled D2 program count does not match checkpoints")
    effective_workers = _resolve_d2_worker_count(d2_max_workers, len(checkpoints))
    records_by_index: dict[int, dict[str, Any]] = {}
    transcripts_by_index: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(
        max_workers=effective_workers,
        thread_name_prefix="gamebench-d2",
    ) as executor:
        futures = {
            executor.submit(
                _sample_one_compiled_checkpoint,
                worker_index=index,
                project=project,
                checkpoint=checkpoint,
                program=program,
                seed=seed,
                sample_dir=sample_dir,
                timeout_sec=timeout_sec,
            ): (index, checkpoint["id"])
            for index, (checkpoint, program) in enumerate(zip(checkpoints, programs))
        }
        try:
            for future in as_completed(futures):
                index, checkpoint_id = futures[future]
                try:
                    completed_index, record, transcript = future.result()
                except Exception as exc:
                    for pending in futures:
                        pending.cancel()
                    raise RuntimeError(
                        f"D2 compiled checkpoint sampling failed for {checkpoint_id}"
                    ) from exc
                records_by_index[completed_index] = record
                transcripts_by_index[completed_index] = transcript
        finally:
            for future in futures:
                future.cancel()

    return (
        [records_by_index[index] for index in range(len(checkpoints))],
        {
            "strategy": "one_candidate_process_per_compiled_checkpoint",
            "requested_workers": d2_max_workers,
            "environment_override": os.getenv("CODE2PLAY_D2_WORKERS"),
            "effective_workers": effective_workers,
            "checkpoint_count": len(checkpoints),
            "result_order": "checkpoint_contract_order",
        },
        [transcripts_by_index[index] for index in range(len(checkpoints))],
    )



def _render_frame(rpc: _CandidateRpc, path: Path) -> str:
    rpc.call("render", path=str(path.resolve()))
    if not path.is_file():
        raise RuntimeError(f"Candidate did not render expected frame: {path}")
    return str(path.resolve())


def _sample_one_compiled_d4_task(
    *,
    worker_index: int,
    project: CandidateProject,
    group: str,
    program: dict[str, Any],
    seed: int,
    sample_dir: Path,
    timeout_sec: int,
) -> tuple[int, str, dict[str, Any], dict[str, Any]]:
    worker_name = f"d4_worker_{worker_index:03d}"
    worker_root = sample_dir / "candidate_workers" / worker_name
    candidate_cwd = worker_root / "cwd"
    candidate_cwd.mkdir(parents=True, exist_ok=True)
    rpc = _CandidateRpc(
        project,
        cwd=candidate_cwd,
        stderr_path=worker_root / "stderr.txt",
        timeout_sec=timeout_sec,
    )
    case_records: list[dict[str, Any]] = []
    sampling_error: dict[str, str] | None = None
    try:
        for case_index, case in enumerate(program["cases"]):
            rpc.call("init", seed=seed + case_index)
            setup_results: list[dict[str, Any]] = []
            for operation_index, operation in enumerate(case["setup_actions"]):
                for repetition in range(operation["repeat"]):
                    setup_results.append(
                        {
                            "operation_index": operation_index,
                            "repetition": repetition,
                            "command": operation["command"],
                            "action_state": rpc.call(
                                "action", command=operation["command"]
                            ),
                        }
                    )

            frame_dir = candidate_cwd / "frames" / f"case_{case_index:03d}"
            frames = [
                {
                    "case": case["name"],
                    "phase": "before",
                    "offset_seconds": 0.0,
                    "snapshot": rpc.call("snapshot"),
                    "path": _render_frame(rpc, frame_dir / "frame_000.png"),
                }
            ]
            action_results: list[dict[str, Any]] = []
            elapsed = 0.0
            frame_index = 1
            for sequence_name, phase in (
                ("transition_actions", "transition"),
                ("observation_actions", "observation"),
            ):
                sequence_start_frames = len(frames)
                for operation_index, operation in enumerate(case[sequence_name]):
                    for repetition in range(operation["repeat"]):
                        action_state = rpc.call("action", command=operation["command"])
                        elapsed += float(operation["command"]["dt"])
                        action_results.append(
                            {
                                "sequence": sequence_name,
                                "operation_index": operation_index,
                                "repetition": repetition,
                                "command": operation["command"],
                                "action_state": action_state,
                            }
                        )
                        if operation["capture_each"]:
                            frames.append(
                                {
                                    "case": case["name"],
                                    "phase": phase,
                                    "offset_seconds": elapsed,
                                    "snapshot": rpc.call("snapshot"),
                                    "path": _render_frame(
                                        rpc,
                                        frame_dir / f"frame_{frame_index:03d}.png",
                                    ),
                                }
                            )
                            frame_index += 1
                if case[sequence_name] and len(frames) == sequence_start_frames:
                    frames.append(
                        {
                            "case": case["name"],
                            "phase": phase,
                            "offset_seconds": elapsed,
                            "snapshot": rpc.call("snapshot"),
                            "path": _render_frame(
                                rpc,
                                frame_dir / f"frame_{frame_index:03d}.png",
                            ),
                        }
                    )
                    frame_index += 1
            case_records.append(
                {
                    "case": case["name"],
                    "setup_results": setup_results,
                    "action_results": action_results,
                    "frames": frames,
                }
            )
    except Exception as exc:
        sampling_error = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
    finally:
        rpc.close()

    record = {
        "id": program["task_id"],
        "task_type": program["task_type"],
        "status": "sampling_failed" if sampling_error else "completed",
        "sampling_authority": "evaluator_llm_compiled_program",
        "candidate_received_task_id": False,
        "worker_index": worker_index,
        "compiled_program": program,
        "cases": case_records,
        "frames": [
            frame for case_record in case_records for frame in case_record["frames"]
        ],
    }
    if sampling_error:
        record["sampling_error"] = sampling_error
    transcript_record = {
        "worker_index": worker_index,
        "worker_name": worker_name,
        "status": record["status"],
        "sampling_error": sampling_error,
        "transcript_path": str((worker_root / "rpc_transcript.json").resolve()),
        "stderr_path": str((worker_root / "stderr.txt").resolve()),
        "rpc": rpc.transcript,
    }
    return worker_index, group, record, transcript_record


def _sample_compiled_d4_parallel(
    *,
    project: CandidateProject,
    programs: dict[str, list[dict[str, Any]]],
    seed: int,
    sample_dir: Path,
    timeout_sec: int,
    d4_max_workers: int | None,
) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, Any],
    list[dict[str, Any]],
]:
    tagged_programs = [("d4_2", program) for program in programs["d4_2"]]
    effective_workers = _resolve_d2_worker_count(d4_max_workers, len(tagged_programs))
    records_by_group: dict[str, dict[int, dict[str, Any]]] = {
        "d4_2": {},
    }
    transcripts_by_index: dict[int, dict[str, Any]] = {}
    group_index_by_worker: dict[int, tuple[str, int]] = {}
    group_counts = {"d4_2": 0}
    with ThreadPoolExecutor(
        max_workers=effective_workers,
        thread_name_prefix="gamebench-d4",
    ) as executor:
        futures = {}
        for worker_index, (group, program) in enumerate(tagged_programs):
            group_index = group_counts[group]
            group_counts[group] += 1
            group_index_by_worker[worker_index] = (group, group_index)
            future = executor.submit(
                _sample_one_compiled_d4_task,
                worker_index=worker_index,
                project=project,
                group=group,
                program=program,
                seed=seed,
                sample_dir=sample_dir,
                timeout_sec=timeout_sec,
            )
            futures[future] = (worker_index, group, program["task_id"])
        try:
            for future in as_completed(futures):
                worker_index, group, task_id = futures[future]
                try:
                    (
                        completed_index,
                        completed_group,
                        record,
                        transcript,
                    ) = future.result()
                except Exception as exc:
                    for pending in futures:
                        pending.cancel()
                    raise RuntimeError(
                        f"D4 compiled sampling failed for {group} task " f"{task_id}"
                    ) from exc
                if completed_group != group:
                    raise RuntimeError("D4 worker returned a mismatched group")
                _, group_index = group_index_by_worker[completed_index]
                records_by_group[group][group_index] = record
                transcripts_by_index[completed_index] = transcript
        finally:
            for future in futures:
                future.cancel()

    records = {
        group: [records_by_group[group][index] for index in range(group_counts[group])]
        for group in ("d4_2",)
    }
    records["d4_3"] = []
    return (
        records,
        {
            "strategy": "one_candidate_process_per_compiled_visual_task",
            "requested_workers": d4_max_workers,
            "environment_override": os.getenv("CODE2PLAY_D2_WORKERS"),
            "effective_workers": effective_workers,
            "d4_2_task_count": group_counts["d4_2"],
            "d4_3_task_count": 0,
            "d4_3_strategy": "reuse_real_d4_2_d2_2_evidence",
            "result_order": "dynamic_d2_checkpoint_order",
        },
        [transcripts_by_index[index] for index in range(len(tagged_programs))],
    )





def _run_candidate_phase(
    *,
    project: CandidateProject,
    spec: dict[str, Any],
    contract: dict[str, Any],
    checkpoints: list[dict[str, Any]],
    protocol_audit: dict[str, Any],
    candidate_source: str,
    sample_dir: Path,
    timeout_sec: int,
    d2_max_workers: int | None,
    checkpoint_compiler: SemanticJudge,
) -> dict[str, Any]:
    """Compile and sample while sensitive evaluator artifacts stay in memory."""
    compiler_workers = _resolve_d2_worker_count(d2_max_workers, len(checkpoints))
    programs, compiler_parallelism = _compile_checkpoint_programs(
        checkpoints=checkpoints,
        game_description=spec.get("body", ""),
        functional_requirements=list(spec["checkpoints"]),
        candidate_source=candidate_source,
        initial_snapshot=protocol_audit["snapshot_after_init"],
        initial_schema=protocol_audit["state_schema"],
        compiler=checkpoint_compiler,
        max_workers=compiler_workers,
    )

    d2_records, d2_parallelism, d2_transcripts = _sample_compiled_d2_parallel(
        project=project,
        checkpoints=checkpoints,
        programs=programs,
        seed=int(contract.get("seed", 17)),
        sample_dir=sample_dir,
        timeout_sec=timeout_sec,
        d2_max_workers=d2_max_workers,
    )

    d4_programs = {"d4_2": [], "d4_3": []}
    d4_compiler_parallelism = None
    d4_records = {
        "d4_2": [
            {
                "id": record["id"],
                "status": (
                    "completed"
                    if record.get("status") == "completed" and record.get("frames")
                    else "visual_evidence_unavailable"
                ),
                "sampling_authority": "reused_functionality_action_execution",
                "compiled_program": record.get("compiled_program"),
                "frames": record.get("frames", []),
                "visual_status": record.get("visual_status"),
                "visual_probe_policy": record.get("visual_probe_policy"),
                "visual_distinct_image_count": record.get(
                    "visual_distinct_image_count", 0
                ),
                "visual_difference_policy": record.get(
                    "visual_difference_policy"
                ),
                "visual_materially_distinct_image_count": record.get(
                    "visual_materially_distinct_image_count", 0
                ),
                "visual_probe_summary": record.get("visual_probe_summary", []),
                "visual_errors": record.get("visual_errors", []),
                "sampling_error": record.get("sampling_error"),
            }
            for checkpoint, record in zip(checkpoints, d2_records)
            if checkpoint.get("kind") == "dynamic"
        ],
        "d4_3": [],
    }
    d4_sampling_parallelism = None
    d4_transcripts = []

    return {
        "d2_programs": programs,
        "d2_compiler_parallelism": compiler_parallelism,
        "d2_records": d2_records,
        "d2_sampling_parallelism": d2_parallelism,
        "d2_transcripts": d2_transcripts,
        "d4_programs": d4_programs,
        "d4_compiler_parallelism": d4_compiler_parallelism,
        "d4_records": d4_records,
        "d4_sampling_parallelism": d4_sampling_parallelism,
        "d4_transcripts": d4_transcripts,
    }


def _protocol_failure_phase(
    checkpoints: list[dict[str, Any]],
    contract: dict[str, Any],
    error: dict[str, str],
) -> dict[str, Any]:
    status = "not_run_adapter_contract"
    parallelism = {"status": status, "effective_workers": 0}
    d2_records = [
        {
            "id": checkpoint["id"],
            "dimension": checkpoint["dimension"],
            "kind": checkpoint["kind"],
            "status": status,
            "sampling_authority": "evaluator_llm_compiled_program",
            "candidate_received_checkpoint_id": False,
            "compiled_program": None,
            "cases": [],
            "sampling_error": error,
        }
        for checkpoint in checkpoints
    ]
    d4_contract = contract.get("d4")
    if isinstance(d4_contract, dict):
        d4_2 = [
            {
                "id": checkpoint["id"],
                "task_type": "d4_2_transition",
                "status": status,
                "sampling_authority": "evaluator_llm_compiled_program",
                "candidate_received_task_id": False,
                "compiled_program": None,
                "cases": [],
                "frames": [],
                "sampling_error": error,
            }
            for checkpoint in checkpoints
            if checkpoint.get("kind") == "dynamic"
        ]
        d4_3 = []
    else:
        d4_2 = []
        d4_3 = []
    return {
        "d2_programs": [],
        "d2_compiler_parallelism": parallelism,
        "d2_records": d2_records,
        "d2_sampling_parallelism": parallelism,
        "d2_transcripts": [],
        "d4_programs": {"d4_2": [], "d4_3": []},
        "d4_compiler_parallelism": parallelism if isinstance(d4_contract, dict) else None,
        "d4_records": {"d4_2": d4_2, "d4_3": d4_3},
        "d4_sampling_parallelism": parallelism if isinstance(d4_contract, dict) else None,
        "d4_transcripts": [],
    }


def _sample_protocol(
    project: CandidateProject,
    spec_path: Path,
    evidence_dir: Path,
    timeout_sec: int,
    d2_max_workers: int | None,
    checkpoint_compiler: SemanticJudge,
) -> dict[str, Any]:
    """Compile textual checkpoints with an evaluator LLM, then sample them."""
    spec = load_spec(spec_path)
    contract = spec["evaluation"]
    d2 = contract["d2"]
    checkpoints = list(d2["checkpoints"])
    sample_dir = evidence_dir / "samples"
    sample_dir.mkdir(parents=True, exist_ok=True)
    workers_root = sample_dir / "candidate_workers"

    audit_root = workers_root / "protocol_audit"
    audit_cwd = audit_root / "cwd"
    audit_cwd.mkdir(parents=True, exist_ok=True)
    audit_rpc = _CandidateRpc(
        project,
        cwd=audit_cwd,
        stderr_path=audit_root / "stderr.txt",
        timeout_sec=timeout_sec,
    )
    protocol_audit: dict[str, Any] | None = None
    try:
        protocol_audit = _protocol_audit(audit_rpc, int(contract.get("seed", 17)))
    except Exception as exc:
        protocol_audit = {
            "passed": False,
            "status": "failed",
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
            },
        }
    finally:
        audit_rpc.close()
        (audit_root / "rpc_transcript.json").write_text(
            json.dumps(
                audit_rpc.transcript,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
    if protocol_audit is not None:
        (sample_dir / "protocol_audit.json").write_text(
            json.dumps(protocol_audit, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    if not protocol_audit or not protocol_audit["passed"]:
        error = (
            protocol_audit.get("error")
            if isinstance(protocol_audit, dict)
            else None
        )
        if not isinstance(error, dict):
            error = {
                "type": "RuntimeError",
                "message": "Candidate failed protocol-v4 init/snapshot/action audit",
            }
        phase_result = _protocol_failure_phase(checkpoints, contract, error)
    else:
        candidate_source = project.source_bundle()
        defer_logs = getattr(checkpoint_compiler, "defer_logs", None)
        log_context = defer_logs() if callable(defer_logs) else nullcontext()
        with log_context:
            phase_result = _run_candidate_phase(
                project=project,
                spec=spec,
                contract=contract,
                checkpoints=checkpoints,
                protocol_audit=protocol_audit,
                candidate_source=candidate_source,
                sample_dir=sample_dir,
                timeout_sec=timeout_sec,
                d2_max_workers=d2_max_workers,
                checkpoint_compiler=checkpoint_compiler,
            )

    # Only now, after every candidate process has exited, persist checkpoint
    # ids, compiled programs, action transcripts, and textual contracts.
    (sample_dir / "compiled_checkpoint_programs.json").write_text(
        json.dumps(phase_result["d2_programs"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (sample_dir / "compiled_d4_programs.json").write_text(
        json.dumps(phase_result["d4_programs"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for record, transcript in zip(
        phase_result["d2_records"], phase_result["d2_transcripts"]
    ):
        transcript_path = Path(transcript["transcript_path"])
        transcript_path.write_text(
            json.dumps(transcript["rpc"], ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        trace_path = sample_dir / "d2" / f"{record['id']}.json"
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        trace_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        record["trace_path"] = str(trace_path.resolve())
    for transcript in phase_result["d4_transcripts"]:
        Path(transcript["transcript_path"]).write_text(
            json.dumps(
                transcript["rpc"],
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
    for group in ("d4_2", "d4_3"):
        for record in phase_result["d4_records"][group]:
            frame_dir = sample_dir / "screenshots" / group / record["id"]
            frame_dir.mkdir(parents=True, exist_ok=True)
            for frame_index, frame in enumerate(record["frames"]):
                destination = frame_dir / f"frame_{frame_index:03d}.png"
                shutil.copyfile(Path(frame["path"]), destination)
                frame["path"] = str(destination.resolve())
            trace_path = sample_dir / "d4" / group / f"{record['id']}.json"
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            trace_path.write_text(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                encoding="utf-8",
            )
            record["trace_path"] = str(trace_path.resolve())

    combined_transcript = {
        "checkpoint_ids_included": False,
        "d4_task_ids_included": False,
        "protocol_audit": audit_rpc.transcript,
        "d2_workers": phase_result["d2_transcripts"],
        "d4_workers": phase_result["d4_transcripts"],
    }
    (sample_dir / "candidate_rpc_transcript.json").write_text(
        json.dumps(
            combined_transcript,
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    (sample_dir / "evaluation_contract.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest = {
        "protocol_version": 4,
        "sampling_authority": "evaluator_llm_compiled_program",
        "checkpoint_compiler": "evaluator_side_llm",
        "d4_compiler": "reused_functionality_compiled_programs",
        "d4_2_checkpoint_selection": "kind_dynamic_only",
        "compiler_received_textual_checkpoints": bool(protocol_audit.get("passed")),
        "candidate_received_checkpoint_ids": False,
        "candidate_received_d4_task_ids": False,
        "candidate_received_scoring_contract": False,
        "candidate_project_copied_to_isolated_cwd": True,
        "candidate_environment_sanitized": True,
        "sensitive_evaluator_artifacts_written_after_candidate_exit": True,
        "candidate_project_sha256": project.project_sha256(),
        "protocol_audit": protocol_audit,
        "compiler_parallelism": phase_result["d2_compiler_parallelism"],
        "d2_parallelism": phase_result["d2_sampling_parallelism"],
        "d4_compiler_parallelism": phase_result["d4_compiler_parallelism"],
        "d4_sampling_parallelism": phase_result["d4_sampling_parallelism"],
        "d2": phase_result["d2_records"],
        "d4_2": phase_result["d4_records"]["d4_2"],
        "d4_3": phase_result["d4_records"]["d4_3"],
    }
    manifest_path = sample_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    manifest["manifest_path"] = str(manifest_path)
    return manifest



def sample_evaluation_protocol(
    project: CandidateProject | Path | str,
    spec_path: Path | str,
    evidence_dir: Path | str,
    timeout_sec: int = 45,
    d2_max_workers: int | None = None,
    checkpoint_compiler: SemanticJudge | None = None,
) -> dict[str, Any]:
    """Sample a game through the optimized evaluator-compiled protocol v4."""
    candidate = project if isinstance(project, CandidateProject) else CandidateProject(project)
    spec_path = Path(spec_path).resolve()
    evidence_dir = Path(evidence_dir).resolve()
    contract = load_evaluation_contract(spec_path)
    if contract.get("protocol_version") != 4:
        raise ValueError("Formal evaluation requires protocol_version: 4")
    if checkpoint_compiler is None:
        raise ValueError(
            "Protocol v4 requires an evaluator-side checkpoint compiler LLM"
        )
    return _sample_protocol(
        candidate,
        spec_path,
        evidence_dir,
        timeout_sec,
        d2_max_workers,
        checkpoint_compiler,
    )


