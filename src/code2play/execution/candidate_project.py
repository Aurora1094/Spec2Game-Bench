"""Immutable multi-file candidate artifact helpers."""

from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any


PROJECT_FILES = ("__init__.py", "state.py", "game.py", "rendering.py", "main.py")
GENERATED_FILES = ("state.py", "game.py", "rendering.py", "main.py")
STAGE_TARGETS = {
    "state": "state.py",
    "game": "game.py",
    "rendering": "rendering.py",
    "main": "main.py",
}
BENCHMARK_INIT_SOURCE = '"""Benchmark-managed candidate package."""\n'

_PROJECT_MODULES = {"candidate", "state", "game", "rendering", "main"}
_ALLOWED_PROJECT_IMPORTS = {
    "state": set(),
    "game": {"state"},
    "rendering": {"state"},
    "main": {"state", "game", "rendering"},
}
_REQUIRED_SYMBOLS = {
    "state": {
        "classes": {"GameState"},
        "functions": {"create_initial_state", "state_to_dict"},
        "methods": {},
    },
    "game": {
        "classes": {"GameEngine"},
        "functions": set(),
        "methods": {
            "GameEngine": {"__init__", "reset", "action", "snapshot", "state"}
        },
    },
    "rendering": {
        "classes": {"GameRenderer"},
        "functions": set(),
        "methods": {"GameRenderer": {"render", "close"}},
    },
    "main": {
        "classes": {"GameBenchAdapter"},
        "functions": {"create_gamebench_adapter", "main"},
        "methods": {
            "GameBenchAdapter": {"init", "action", "snapshot", "render", "close"}
        },
    },
}


@dataclass(frozen=True)
class ProjectValidation:
    valid: bool
    structure_valid: bool
    files: dict[str, dict[str, Any]]
    missing_files: tuple[str, ...]
    extra_paths: tuple[str, ...]
    symlink_paths: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _node_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args: list[str] = []
    positional = [*node.args.posonlyargs, *node.args.args]
    default_offset = len(positional) - len(node.args.defaults)
    for index, argument in enumerate(positional):
        rendered = argument.arg
        if index >= default_offset:
            rendered += "=..."
        args.append(rendered)
    if node.args.vararg is not None:
        args.append("*" + node.args.vararg.arg)
    elif node.args.kwonlyargs:
        args.append("*")
    for argument, default in zip(node.args.kwonlyargs, node.args.kw_defaults):
        args.append(argument.arg + ("=..." if default is not None else ""))
    if node.args.kwarg is not None:
        args.append("**" + node.args.kwarg.arg)
    return f"{node.name}({', '.join(args)})"


def _property_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str | None:
    is_property = any(
        isinstance(decorator, ast.Name) and decorator.id == "property"
        for decorator in node.decorator_list
    )
    if not is_property:
        return None
    annotation = (
        ast.unparse(node.returns)
        if node.returns is not None
        else "unspecified"
    )
    return f"{node.name}: {annotation} (read-only property; access without parentheses)"


def _project_imports(tree: ast.AST) -> tuple[set[str], set[str]]:
    dependencies: set[str] = set()
    absolute_project_imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in _PROJECT_MODULES:
                    dependencies.add(root)
                    absolute_project_imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".", 1)[0] if module else ""
            if node.level:
                if root:
                    dependencies.add(root)
                else:
                    dependencies.update(
                        alias.name for alias in node.names if alias.name in _PROJECT_MODULES
                    )
            elif root in _PROJECT_MODULES:
                dependencies.add(root)
                absolute_project_imports.add(module)
    dependencies.discard("candidate")
    return dependencies, absolute_project_imports


def diagnose_stage_source(stage: str, source: str) -> dict[str, Any]:
    """Return non-blocking syntax, interface, and dependency diagnostics."""

    if stage not in STAGE_TARGETS:
        raise ValueError(f"Unknown generation stage: {stage}")
    result: dict[str, Any] = {
        "stage": stage,
        "target": STAGE_TARGETS[stage],
        "source_sha256": _sha256_text(source),
        "syntax_valid": False,
        "syntax_error": None,
        "interface_valid": False,
        "missing_symbols": [],
        "dependency_valid": False,
        "project_dependencies": [],
        "forbidden_project_dependencies": [],
        "absolute_project_imports": [],
        "pygame_allowed": stage in {"rendering", "main"},
        "pygame_imported": False,
    }
    try:
        tree = ast.parse(source, filename=STAGE_TARGETS[stage])
    except SyntaxError as exc:
        result["syntax_error"] = {
            "message": exc.msg,
            "line": exc.lineno,
            "offset": exc.offset,
        }
        return result

    result["syntax_valid"] = True
    classes = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing: list[str] = []
    required = _REQUIRED_SYMBOLS[stage]
    for name in sorted(required["classes"] - classes.keys()):
        missing.append(f"class {name}")
    for name in sorted(required["functions"] - functions.keys()):
        missing.append(f"function {name}")
    for class_name, method_names in required["methods"].items():
        class_node = classes.get(class_name)
        present = (
            {
                item.name
                for item in class_node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
            if class_node is not None
            else set()
        )
        for name in sorted(method_names - present):
            missing.append(f"{class_name}.{name}")
    result["missing_symbols"] = missing
    result["interface_valid"] = not missing

    dependencies, absolute = _project_imports(tree)
    forbidden = dependencies - _ALLOWED_PROJECT_IMPORTS[stage]
    pygame_imported = any(
        (
            isinstance(node, ast.Import)
            and any(alias.name.split(".", 1)[0] == "pygame" for alias in node.names)
        )
        or (
            isinstance(node, ast.ImportFrom)
            and (node.module or "").split(".", 1)[0] == "pygame"
        )
        for node in ast.walk(tree)
    )
    result["project_dependencies"] = sorted(dependencies)
    result["forbidden_project_dependencies"] = sorted(forbidden)
    result["absolute_project_imports"] = sorted(absolute)
    result["pygame_imported"] = pygame_imported
    result["dependency_valid"] = not forbidden and not absolute and (
        result["pygame_allowed"] or not pygame_imported
    )
    return result


def _public_api_for_source(filename: str, source: str) -> dict[str, Any]:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return {
            "available": False,
            "error": f"SyntaxError: {exc.msg} at line {exc.lineno}",
            "classes": [],
            "functions": [],
        }
    classes: list[dict[str, Any]] = []
    functions: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            public_members = [
                item
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and not (item.name.startswith("_") and item.name != "__init__")
            ]
            properties = [
                signature
                for item in public_members
                if (signature := _property_signature(item)) is not None
            ]
            methods = [
                _node_signature(item)
                for item in public_members
                if _property_signature(item) is None
            ]
            classes.append(
                {"name": node.name, "methods": methods, "properties": properties}
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            functions.append(_node_signature(node))
    return {
        "available": True,
        "error": None,
        "classes": classes,
        "functions": functions,
    }


@dataclass(frozen=True)
class CandidateProject:
    root: Path
    entrypoint: str = "candidate.main"
    factory: str = "create_gamebench_adapter"

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root).resolve())

    def path(self, filename: str) -> Path:
        if filename not in PROJECT_FILES:
            raise ValueError(f"Unsupported candidate filename: {filename}")
        return self.root / filename

    def validate(self) -> ProjectValidation:
        if not self.root.is_dir():
            return ProjectValidation(
                valid=False,
                structure_valid=False,
                files={},
                missing_files=PROJECT_FILES,
                extra_paths=(),
                symlink_paths=(),
            )
        actual = sorted(
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
        )
        symlinks = tuple(
            value
            for value in actual
            if (self.root / Path(value)).is_symlink()
        )
        files = {
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        missing = tuple(name for name in PROJECT_FILES if name not in files)
        extra = tuple(value for value in actual if value not in PROJECT_FILES)
        diagnostics: dict[str, dict[str, Any]] = {}
        for stage, filename in STAGE_TARGETS.items():
            path = self.root / filename
            if path.is_file() and not path.is_symlink():
                diagnostics[filename] = diagnose_stage_source(
                    stage, path.read_text(encoding="utf-8-sig", errors="replace")
                )
            else:
                diagnostics[filename] = {
                    "stage": stage,
                    "target": filename,
                    "syntax_valid": False,
                    "syntax_error": {"message": "missing file"},
                    "interface_valid": False,
                    "missing_symbols": [],
                    "dependency_valid": False,
                }
        init_path = self.root / "__init__.py"
        init_valid = init_path.is_file() and not init_path.is_symlink() and (
            init_path.read_text(encoding="utf-8-sig", errors="replace")
            == BENCHMARK_INIT_SOURCE
        )
        diagnostics["__init__.py"] = {
            "benchmark_managed": True,
            "content_valid": init_valid,
        }
        structure_valid = not missing and not extra and not symlinks and init_valid
        semantic_valid = all(
            item.get("syntax_valid")
            and item.get("interface_valid")
            and item.get("dependency_valid")
            for filename, item in diagnostics.items()
            if filename != "__init__.py"
        )
        return ProjectValidation(
            valid=bool(structure_valid and semantic_valid),
            structure_valid=bool(structure_valid),
            files=diagnostics,
            missing_files=missing,
            extra_paths=extra,
            symlink_paths=symlinks,
        )

    def assert_safe_structure(self) -> None:
        validation = self.validate()
        if not validation.structure_valid:
            raise ValueError(
                "Candidate project structure is unsafe or incomplete: "
                + json.dumps(validation.to_dict(), ensure_ascii=False, sort_keys=True)
            )

    def file_hashes(self) -> dict[str, str]:
        self.assert_safe_structure()
        return {
            filename: _sha256_bytes(self.path(filename).read_bytes())
            for filename in PROJECT_FILES
        }

    def project_sha256(self) -> str:
        records = "".join(
            f"{filename}\0{digest}\n"
            for filename, digest in self.file_hashes().items()
        )
        return _sha256_text(records)

    def source_bundle(self) -> str:
        self.assert_safe_structure()
        parts = []
        for filename in GENERATED_FILES:
            source = self.path(filename).read_text(
                encoding="utf-8-sig", errors="replace"
            ).lstrip("\ufeff")
            parts.append(f"# ===== FILE: {filename} =====\n{source.rstrip()}\n")
        return "\n".join(parts)

    def public_api_summary(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for filename in ("state.py", "game.py", "rendering.py"):
            path = self.path(filename)
            if not path.is_file():
                result[filename] = {
                    "available": False,
                    "error": "missing file",
                    "classes": [],
                    "functions": [],
                }
            else:
                result[filename] = _public_api_for_source(
                    filename,
                    path.read_text(encoding="utf-8-sig", errors="replace"),
                )
        return result

    def copy_to_isolated(self, target: Path) -> Path:
        self.assert_safe_structure()
        destination = Path(target).resolve()
        if destination.exists() and any(destination.iterdir()):
            raise FileExistsError(f"Isolated candidate target is not empty: {destination}")
        destination.mkdir(parents=True, exist_ok=True)
        for filename in PROJECT_FILES:
            shutil.copyfile(self.path(filename), destination / filename)
        copied = CandidateProject(destination, entrypoint=self.entrypoint, factory=self.factory)
        copied.assert_safe_structure()
        if copied.project_sha256() != self.project_sha256():
            raise ValueError("Candidate project hash changed during isolated copy")
        return destination


def initialize_candidate_project(root: Path | str) -> CandidateProject:
    directory = Path(root).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    init_path = directory / "__init__.py"
    if init_path.exists():
        if init_path.is_symlink() or init_path.read_text(
            encoding="utf-8-sig", errors="replace"
        ) != BENCHMARK_INIT_SOURCE:
            raise ValueError("Existing candidate/__init__.py is not benchmark-managed")
    else:
        init_path.write_text(BENCHMARK_INIT_SOURCE, encoding="utf-8", newline="\n")
    return CandidateProject(directory)


__all__ = [
    "BENCHMARK_INIT_SOURCE",
    "CandidateProject",
    "GENERATED_FILES",
    "PROJECT_FILES",
    "ProjectValidation",
    "STAGE_TARGETS",
    "diagnose_stage_source",
    "initialize_candidate_project",
]
