"""Deterministic D1 checks for a staged candidate project."""

from __future__ import annotations

import ast
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import textwrap
from typing import Any

from code2play.execution.candidate_project import CandidateProject, GENERATED_FILES


WINDOW_MARKER = "__D1_WINDOW_CREATED__"
SURFACE_MARKER = "__D1_WINDOW_SURFACE__"
EVENT_MARKER = "__D1_EVENT_FETCH__"
QUIT_MARKER = "__D1_QUIT_POSTED__"

INDICATOR_ORDER: list[tuple[str, str]] = [
    ("python_syntax_correct", "All generated modules parse"),
    ("dependency_initialization_complete", "pygame imports in the evaluator environment"),
    ("window_creation", "The entrypoint creates a pygame Surface"),
    ("event_handling_mechanism", "The entrypoint reads pygame events"),
    ("short_runtime_stable", "The interactive loop remains alive during the probe"),
    ("process_controllability", "The loop exits after an injected QUIT event"),
]

WRAPPER_CODE = textwrap.dedent(
    r"""
    import os
    from pathlib import Path
    import runpy
    import sys
    import threading
    import time
    import traceback

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    project_root = Path(sys.argv[1]).resolve()
    mode = sys.argv[2]
    sys.path.insert(0, str(project_root.parent))
    emitted = set()

    def emit_once(marker):
        if marker not in emitted:
            emitted.add(marker)
            print(marker, flush=True)

    try:
        import pygame
        original_set_mode = pygame.display.set_mode
        original_get = pygame.event.get
        original_poll = pygame.event.poll

        def set_mode(*args, **kwargs):
            surface = original_set_mode(*args, **kwargs)
            emit_once("__D1_WINDOW_CREATED__")
            if isinstance(surface, pygame.Surface):
                emit_once("__D1_WINDOW_SURFACE__")
            return surface

        def event_get(*args, **kwargs):
            emit_once("__D1_EVENT_FETCH__")
            return original_get(*args, **kwargs)

        def event_poll(*args, **kwargs):
            emit_once("__D1_EVENT_FETCH__")
            return original_poll(*args, **kwargs)

        pygame.display.set_mode = set_mode
        pygame.event.get = event_get
        pygame.event.poll = event_poll

        def post_quit():
            time.sleep(1.0)
            deadline = time.time() + 3.0
            while time.time() < deadline:
                try:
                    pygame.event.post(pygame.event.Event(pygame.QUIT))
                    emit_once("__D1_QUIT_POSTED__")
                except Exception:
                    pass
                time.sleep(0.1)

        if mode == "quit":
            threading.Thread(target=post_quit, daemon=True).start()
        runpy.run_module("candidate.main", run_name="__main__")
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 0 if exc.code is None else 1
        raise SystemExit(code)
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)
    finally:
        try:
            import pygame
            pygame.quit()
        except Exception:
            pass
    """
)


def _empty_indicators() -> dict[str, int]:
    return {key: 0 for key, _label in INDICATOR_ORDER}


def _attribute_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _attribute_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _imports_pygame(trees: list[ast.AST]) -> bool:
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                alias.name.split(".", 1)[0] == "pygame" for alias in node.names
            ):
                return True
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(
                ".", 1
            )[0] == "pygame":
                return True
    return False


def _has_event_shape(trees: list[ast.AST]) -> bool:
    calls = {
        _attribute_name(node.func)
        for tree in trees
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    return bool({"pygame.event.get", "pygame.event.poll"} & calls)


def _pygame_importable(timeout_sec: int = 5) -> bool:
    env = os.environ.copy()
    env.setdefault("SDL_VIDEODRIVER", "dummy")
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import pygame"],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=env,
        )
    except Exception:
        return False
    return result.returncode == 0


def _run_probe(project: CandidateProject, mode: str, timeout_sec: int) -> dict[str, Any]:
    env = os.environ.copy()
    env.setdefault("SDL_VIDEODRIVER", "dummy")
    env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    process = subprocess.Popen(
        [sys.executable, "-c", WRAPPER_CODE, str(project.root), mode],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        cwd=str(project.root.parent),
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        timed_out = True
        process.kill()
        stdout, stderr = process.communicate(timeout=2)
    return {
        "mode": mode,
        "returncode": process.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
        "window_created": WINDOW_MARKER in stdout,
        "surface_returned": SURFACE_MARKER in stdout,
        "event_fetch_seen": EVENT_MARKER in stdout,
        "quit_posted": QUIT_MARKER in stdout,
    }


def _failure_reason(indicators: dict[str, int]) -> str:
    failed = [label for key, label in INDICATOR_ORDER if not indicators[key]]
    return "All D1 checks passed." if not failed else "Failed: " + "; ".join(failed)


def evaluate_dimension1(
    project: CandidateProject | Path | str,
    runtime_sec: int = 5,
) -> dict[str, Any]:
    candidate = project if isinstance(project, CandidateProject) else CandidateProject(project)
    validation = candidate.validate()
    indicators = _empty_indicators()
    trees: list[ast.AST] = []
    syntax_errors: dict[str, str] = {}
    if validation.structure_valid:
        for filename in GENERATED_FILES:
            try:
                trees.append(
                    ast.parse(
                        candidate.path(filename).read_text(
                            encoding="utf-8-sig", errors="replace"
                        ),
                        filename=filename,
                    )
                )
            except SyntaxError as exc:
                syntax_errors[filename] = f"{exc.msg} at line {exc.lineno}"
    indicators["python_syntax_correct"] = int(
        validation.structure_valid and not syntax_errors and len(trees) == len(GENERATED_FILES)
    )

    pygame_available = importlib.util.find_spec("pygame") is not None
    pygame_import_ok = pygame_available and _pygame_importable()
    dependency_direction_valid = all(
        bool(validation.files.get(filename, {}).get("dependency_valid"))
        for filename in GENERATED_FILES
    )
    stability: dict[str, Any] | None = None
    quit_probe: dict[str, Any] | None = None
    if indicators["python_syntax_correct"]:
        indicators["dependency_initialization_complete"] = int(
            _imports_pygame(trees)
            and pygame_import_ok
            and dependency_direction_valid
        )
    if indicators["dependency_initialization_complete"]:
        stability = _run_probe(candidate, "stability", runtime_sec)
        indicators["window_creation"] = int(stability["surface_returned"])
        indicators["event_handling_mechanism"] = int(
            stability["event_fetch_seen"] or _has_event_shape(trees)
        )
        indicators["short_runtime_stable"] = int(stability["timed_out"])
        if indicators["short_runtime_stable"]:
            quit_probe = _run_probe(candidate, "quit", runtime_sec)
            indicators["process_controllability"] = int(
                quit_probe["quit_posted"]
                and quit_probe["returncode"] == 0
                and not quit_probe["timed_out"]
            )

    passed = 0
    for key, _label in INDICATOR_ORDER:
        if not indicators[key]:
            break
        passed += 1
    return {
        "score": 100.0 * passed / len(INDICATOR_ORDER),
        "max_score": 100.0,
        "score_scale": "0-100",
        "raw_pass_count": sum(indicators.values()),
        "pipeline_steps_passed": passed,
        "gate_pass": passed == len(INDICATOR_ORDER),
        "indicators": indicators,
        "step_order": INDICATOR_ORDER,
        "project_validation": validation.to_dict(),
        "syntax_errors": syntax_errors,
        "runtime": {
            "pygame_available": pygame_available,
            "pygame_import_ok": pygame_import_ok,
            "dependency_direction_valid": dependency_direction_valid,
            "stability_probe": stability,
            "quit_probe": quit_probe,
        },
        "reason": _failure_reason(indicators),
    }


__all__ = ["INDICATOR_ORDER", "evaluate_dimension1"]
