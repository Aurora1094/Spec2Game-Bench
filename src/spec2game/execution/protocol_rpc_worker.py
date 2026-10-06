from __future__ import annotations

import argparse
from collections.abc import Mapping
from contextlib import redirect_stdout
import importlib
import json
import os
from pathlib import Path
import sys
import traceback
from typing import Any, Sequence


def _install_windows_sysfont_fallback() -> None:
    """Neutralize a host registry parsing failure without masking game errors."""

    import pygame

    original_sys_font = pygame.font.SysFont

    def safe_sys_font(
        name: Any,
        size: int,
        bold: bool = False,
        italic: bool = False,
        constructor: Any | None = None,
    ) -> Any:
        try:
            return original_sys_font(name, size, bold, italic, constructor)
        except TypeError:
            font = pygame.font.Font(None, size)
            font.set_bold(bool(bold))
            font.set_italic(bool(italic))
            return font

    pygame.font.SysFont = safe_sys_font


def _load_module(project_root: Path) -> Any:
    sys.path.insert(0, str(project_root.parent))
    with redirect_stdout(sys.stderr):
        return importlib.import_module("candidate.main")


def _method(adapter: Any, name: str) -> Any:
    value = (
        adapter.get(name)
        if isinstance(adapter, Mapping)
        else getattr(adapter, name, None)
    )
    if not callable(value):
        raise AttributeError(f"GameBench adapter is missing callable {name}()")
    return value


def _json_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must return a dict")
    json.dumps(value)
    return value


def _dispatch(adapter: Any, request: dict[str, Any]) -> Any:
    operation = request.get("op")
    if operation == "init":
        state = _method(adapter, "init")(int(request["seed"]))
        return _json_dict(state, "init()")
    if operation == "action":
        command = request.get("command")
        if not isinstance(command, dict):
            raise TypeError("action command must be a mapping")
        state = _method(adapter, "action")(command)
        return _json_dict(state, "action()")
    if operation == "snapshot":
        return _json_dict(_method(adapter, "snapshot")(), "snapshot()")
    if operation == "render":
        import pygame

        surface = _method(adapter, "render")()
        if not isinstance(surface, pygame.Surface):
            raise TypeError("adapter.render() must return pygame.Surface")
        path = Path(str(request["path"])).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        pygame.image.save(surface, str(path))
        return {"path": str(path)}
    if operation == "close":
        close = (
            adapter.get("close")
            if isinstance(adapter, Mapping)
            else getattr(adapter, "close", None)
        )
        if callable(close):
            close()
        return None
    raise ValueError(f"Unsupported RPC operation: {operation!r}")


def run(project_root: Path) -> int:
    # Assignment, rather than setdefault, makes headless execution deterministic.
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
    with redirect_stdout(sys.stderr):
        _install_windows_sysfont_fallback()
        import pygame

        pygame.init()
    module = _load_module(project_root)
    factory = getattr(module, "create_gamebench_adapter", None)
    if not callable(factory):
        raise AttributeError(
            "Generated game must expose create_gamebench_adapter(seed: int = 0)"
        )
    with redirect_stdout(sys.stderr):
        adapter = factory(seed=0)

    try:
        for raw_line in sys.stdin:
            try:
                request = json.loads(raw_line)
                if not isinstance(request, dict):
                    raise TypeError("RPC request must be a JSON object")
                with redirect_stdout(sys.stderr):
                    result = _dispatch(adapter, request)
                response = {
                    "request_id": request.get("request_id"),
                    "ok": True,
                    "result": result,
                }
            except Exception as exc:
                response = {
                    "request_id": (
                        request.get("request_id")
                        if isinstance(locals().get("request"), dict)
                        else None
                    ),
                    "ok": False,
                    "error": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                }
            sys.stdout.write(
                json.dumps(response, ensure_ascii=False, default=str) + "\n"
            )
            sys.stdout.flush()
            if (
                isinstance(locals().get("request"), dict)
                and request.get("op") == "close"
            ):
                break
    finally:
        try:
            import pygame

            pygame.quit()
        except Exception:
            pass
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Candidate-only JSON-RPC worker for trusted GameBench sampling"
    )
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args(argv)
    return run(args.project.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
