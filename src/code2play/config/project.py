"""Project configuration and external workspace resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ROOT = PROJECT_ROOT
DEFAULT_CONFIG = PROJECT_ROOT / "configs" / "examples" / "qwen37_main.yaml"
WORKSPACE_ENV = "CODE2PLAY_WORKSPACE"


@dataclass(frozen=True)
class GameConfig:
    slug: str
    name: str
    spec: Path
    checkpoints: Path
    difficulty: str = ""
    window_size: tuple[int, int] = (600, 800)
    variants: tuple[str, ...] = field(default_factory=tuple)
    d4_configured: bool = True


@dataclass(frozen=True)
class ModelConfig:
    id: str
    name: str
    provider: str
    model: str
    api_style: str = "chat_completions"


def load_catalog(path: str | Path | None = None) -> dict[str, Any]:
    catalog_path = Path(path or PROJECT_ROOT / "benchmark" / "catalog.yaml").expanduser().resolve()
    data = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("games"), list):
        raise ValueError(f"Benchmark catalog must contain a games list: {catalog_path}")
    return data


def load_config(path: str | Path = DEFAULT_CONFIG) -> dict[str, Any]:
    config_path = Path(path).expanduser().resolve()
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Configuration must be a mapping: {config_path}")
    project_root = PROJECT_ROOT
    catalog_path = project_root / str(data.get("catalog_path", "benchmark/catalog.yaml"))
    catalog = load_catalog(catalog_path)
    data = dict(data)
    data["games"] = [
        {
            "slug": item["slug"],
            "name": item["name"],
            "difficulty": item.get("difficulty", ""),
            "spec": f"benchmark/{item['path']}/spec.md",
            "checkpoints": f"benchmark/{item['path']}/checkpoints.jsonl",
            "window_size": item.get("window_size", [600, 800]),
            "variants": item.get("variants", []),
            "d4_configured": True,
        }
        for item in catalog["games"]
    ]
    data["catalog"] = catalog
    data["_config_path"] = str(config_path)
    data["_project_root"] = str(project_root)
    data["_catalog_path"] = str(catalog_path)
    return data


def resolve_workspace(explicit: str | Path | None = None) -> Path:
    """Return the external artifact root; never resolves inside this repository by default."""

    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    configured = os.environ.get(WORKSPACE_ENV)
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / "Code2Play-Workspace").resolve()


def workspace_round_dir(workspace: str | Path, round_id: str) -> Path:
    if not round_id or Path(round_id).name != round_id or round_id in {".", ".."}:
        raise ValueError(f"Invalid round id: {round_id!r}")
    return Path(workspace).expanduser().resolve() / "rounds" / round_id


def workspace_run_dir(workspace: str | Path, run_id: str) -> Path:
    if not run_id or Path(run_id).name != run_id or run_id in {".", ".."}:
        raise ValueError(f"Invalid run id: {run_id!r}")
    return Path(workspace).expanduser().resolve() / "runs" / run_id


def locked_runtime_policy_errors(config: Mapping[str, Any]) -> list[str]:
    """Validate the immutable benchmark semantics and Qwen-only route."""

    errors: list[str] = []
    expected_generation = {
        "protocol": "staged_project_v1",
        "temperature": 0.2,
        "attempts": 2,
        "retry_delays_seconds": [2],
        "stop_on_truncation": True,
        "semantic_retries": 0,
        "total_max_output_tokens": 16000,
        "stages": [
            {"id": "state", "target": "state.py", "max_output_tokens": 3000},
            {"id": "game", "target": "game.py", "max_output_tokens": 7000},
            {"id": "rendering", "target": "rendering.py", "max_output_tokens": 4000},
            {"id": "main", "target": "main.py", "max_output_tokens": 2000},
        ],
    }
    if config.get("schema_version") != 3:
        errors.append("configuration schema_version must be 3")
    if config.get("generation") != expected_generation:
        errors.append("generation parameters differ from the locked benchmark policy")
    judge = config.get("judge")
    if not isinstance(judge, Mapping):
        errors.append("judge configuration must be a mapping")
    else:
        if judge.get("policy") != "optimized_qwen_single_pass_v2":
            errors.append("judge policy must be optimized_qwen_single_pass_v2")
        if judge.get("attempts") != 2 or judge.get("retry_delays_seconds") != [2]:
            errors.append("judge retry policy must be two attempts with one 2-second delay")
        if judge.get("scoring_repetitions") != 1:
            errors.append("every scoring item must have exactly one valid response")
        if judge.get("aggregation") != "single_valid_response":
            errors.append("judge aggregation must be single_valid_response")
        if judge.get("temperature") != 0.0 or judge.get("stateless") is not True:
            errors.append("judge requests must be stateless at temperature zero")
        if judge.get("visual") != {
            "max_transitions_per_batch": 4,
            "max_images_per_batch": 12,
        }:
            errors.append("visual judge batch limits differ from the locked benchmark policy")
        routing = judge.get("routing", {})
        expected_modalities = {
            "action_compiler": "text",
            "functionality": "text",
            "specification_deviation": "text",
            "code_quality": "text",
            "artistic_visual": "vision",
            "dynamic_visual": "vision",
            "question_generation": "vision",
            "question_answering": "vision",
            "contract_generation": "text",
        }
        if not isinstance(routing, Mapping) or routing.get("strategy") != "role_profile_v1":
            errors.append("judge routing must use role_profile_v1")
        else:
            profiles = routing.get("profiles", {})
            roles = routing.get("roles", {})
            role_modalities = routing.get("role_modalities", {})
            qwen = profiles.get("qwen") if isinstance(profiles, Mapping) else None
            if not isinstance(qwen, Mapping) or any(
                qwen.get(key) != value
                for key, value in {
                    "provider": "alibaba_dashscope",
                    "model": "qwen3.7-plus",
                    "api_style": "chat_completions",
                    "api_key_env": "DASHSCOPE_API_KEY",
                    "response_format": {"type": "json_object"},
                }.items()
            ):
                errors.append("judge routing must define the qwen profile")
            if not isinstance(roles, Mapping) or not roles.get("text") or not roles.get("vision"):
                errors.append("active text and vision judge profiles must be configured")
            elif not isinstance(profiles, Mapping) or any(
                not isinstance(profiles.get(roles.get(modality)), Mapping)
                or profiles[roles.get(modality)].get("provider") not in {"alibaba_dashscope", "openrouter"}
                or not profiles[roles.get(modality)].get("model")
                or profiles[roles.get(modality)].get("response_format") != {"type": "json_object"}
                for modality in ("text", "vision")
            ):
                errors.append("active judge profiles must use a supported provider, model, and JSON mode")
            if not isinstance(role_modalities, Mapping) or any(
                role_modalities.get(role) != modality
                for role, modality in expected_modalities.items()
            ):
                errors.append("judge role modalities are incomplete or invalid")
        routes = judge.get("routes", {})
        expected_limits = {
            "action_compiler": 6000,
            "functionality": 2000,
            "specification_deviation": 800,
            "code_quality": 1200,
            "artistic_visual": 800,
            "dynamic_visual": 2000,
            "question_generation": 1000,
            "question_answering": 500,
            "contract_generation": 2000,
        }
        for role, output_limit in expected_limits.items():
            route = routes.get(role) if isinstance(routes, Mapping) else None
            if not isinstance(route, Mapping) or any(
                route.get(key) != value
                for key, value in {
                    "provider": "alibaba_dashscope",
                    "model": "qwen3.7-plus",
                    "api_style": "chat_completions",
                    "enable_thinking": False,
                    "max_output_tokens": output_limit,
                }.items()
            ):
                errors.append(f"judge route {role} differs from the Qwen single-pass policy")
    expected_models = [
        {
            "id": "qwen3_7_plus",
            "name": "Qwen3.7 Plus",
            "provider": "alibaba_dashscope",
            "model": "qwen3.7-plus",
            "api_style": "chat_completions",
        }
    ]
    if config.get("models") != expected_models:
        errors.append("candidate model matrix must contain only qwen3.7-plus")
    evaluation = config.get("evaluation", {})
    if evaluation.get("d1_gate_mode") != "contribution_only":
        errors.append("D1 gate must control contributions only, not D2-D4 measurement")
    if evaluation.get("d2_workers") != 4:
        errors.append("D2 worker count must be 4")
    if evaluation.get("sampling_timeout_seconds") != 45:
        errors.append("sampling timeout must be 45 seconds")
    if evaluation.get("weights") != {"D1": 0.2, "D2": 0.5, "D3": 0.15, "D4": 0.15}:
        errors.append("official D1-D4 weights are invalid")
    return errors


def require_locked_runtime_policy(config: Mapping[str, Any]) -> None:
    errors = locked_runtime_policy_errors(config)
    if errors:
        raise ValueError("; ".join(errors))


def normalized_policy_sha256(config: Mapping[str, Any]) -> str:
    payload = {
        key: value
        for key, value in config.items()
        if key in {"schema_version", "generation", "judge", "evaluation", "models"}
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def games(config: Mapping[str, Any]) -> list[GameConfig]:
    root = Path(str(config.get("_project_root", PROJECT_ROOT))).resolve()
    result: list[GameConfig] = []
    for item in config.get("games", []):
        if not isinstance(item, Mapping):
            raise ValueError("each game configuration must be a mapping")
        size = item.get("window_size", [600, 800])
        result.append(
            GameConfig(
                slug=str(item["slug"]),
                name=str(item["name"]),
                spec=(root / str(item["spec"])).resolve(),
                checkpoints=(root / str(item["checkpoints"])).resolve(),
                difficulty=str(item.get("difficulty", "")),
                window_size=(int(size[0]), int(size[1])),
                variants=tuple(str(value) for value in item.get("variants", [])),
                d4_configured=bool(item.get("d4_configured", True)),
            )
        )
    return result


def models(config: Mapping[str, Any]) -> list[ModelConfig]:
    return [ModelConfig(**dict(item)) for item in config.get("models", [])]


def game_by_slug(config: Mapping[str, Any], slug: str) -> GameConfig:
    for item in games(config):
        if item.slug == slug:
            return item
    raise KeyError(f"Unknown game slug: {slug}")


def model_by_id(config: Mapping[str, Any], model_id: str) -> ModelConfig:
    for item in models(config):
        if item.id == model_id or item.model == model_id:
            return item
    raise KeyError(f"Unknown model id: {model_id}")


__all__ = [
    "DEFAULT_CONFIG",
    "GameConfig",
    "ModelConfig",
    "PROJECT_ROOT",
    "ROOT",
    "game_by_slug",
    "games",
    "load_catalog",
    "load_config",
    "model_by_id",
    "models",
    "normalized_policy_sha256",
    "require_locked_runtime_policy",
    "resolve_workspace",
    "workspace_round_dir",
    "workspace_run_dir",
]
