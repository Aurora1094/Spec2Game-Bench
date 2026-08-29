"""Round-scoped, Qwen-generated D4 contracts.

Contracts are created once before candidate generation.  The manifest is the
lock shared by every candidate and repetition in a main-experiment round.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from jsonschema import Draft202012Validator

from code2play.config.project import GameConfig, load_config
from code2play.generation.prompt_builder import load_evaluator_checkpoints, load_spec
from code2play.providers.dashscope import (
    DASHSCOPE_API_STYLE,
    DASHSCOPE_MODEL,
    DASHSCOPE_PROVIDER,
    create_dashscope_judge,
)


D4_CONTRACT_SCHEMA_VERSION = 1
D4_CONTRACT_VERSION = "round_v1"
D4_CONTRACT_DESIGN_VERSION = "d4_round_contract_qwen37_plus_v1"
D4_CONTRACT_POLICY = "qwen37_plus_single_pass_locally_validated"
D43_SOURCE_DIMENSION = "D2.2"
D43_QUESTION_TEXT = "Based on the current screenshot and game objective, what is the best next action?"
D41_ART_SAMPLE_SIZE = 8
D41_SAMPLE_SEED = 41
D43_QUESTION_COUNT = 2
CONTRACT_GENERATOR_MODEL = DASHSCOPE_MODEL
CONTRACT_VALIDATOR_MODELS = (DASHSCOPE_MODEL,)
MAX_REVISION_ROUNDS = 0
RUNTIME_QUESTION_POLICY = "qwen37_plus_dynamic_visual_questions_fixed_local_binding_v1"
CONTRACT_PROMPT_VERSION = "d4_round_contract_prompt_v2"
CONTRACT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[3] / "benchmark" / "schemas" / "d4_contract.schema.json"
)

_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_DISALLOWED_TERMS = ("restart", "reset", "lifecycle", "invalid", "no-op", "noop", "quit", "close")

GENERATOR_INSTRUCTIONS = """
You design the game-level evaluator contract for one Code2Play-Bench game.
The supplied specification and eligible dynamic interaction requirements are
the only source material. Return one JSON object only. Extract explicit
screenshot-judgeable art requirements, the player goal, legal concrete physical
player operations, and exactly two eligible source requirement IDs for runtime
visual questions. Do not invent scenes or answers. Do not include evaluator
instructions, scoring rules, candidate code, screenshots, or private rubric
text. Every natural-language string must be in English.

Use exactly these top-level field names and no legacy alternatives:
{
  "target": "the player's goal",
  "allowed_operations": ["one concrete physical operation"],
  "art_direction": ["one screenshot-judgeable visual requirement"],
  "art_sample_size": 8,
  "sample_seed": 41,
  "d4_3_source_checkpoint_ids": ["first eligible ID", "second eligible ID"]
}
Only include gameplay operations that can be used to pursue the target.
Exclude restart, reset, quit, close, invalid, no-op, and other lifecycle-only
controls from "allowed_operations".
""".strip()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def contract_sha256(contract: Mapping[str, Any]) -> str:
    payload = dict(contract)
    payload.pop("contract_sha256", None)
    return sha256_bytes(canonical_json(payload))


def manifest_sha256(manifest: Mapping[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("manifest_sha256", None)
    return sha256_bytes(canonical_json(payload))


def _english(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    result = value.strip()
    if _CJK_PATTERN.search(result):
        raise ValueError(f"{label} must be in English")
    return result


def _string_list(value: Any, label: str, minimum: int = 1, maximum: int = 12) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{label} must contain {minimum} through {maximum} strings")
    result = [_english(item, f"{label}[{index}]") for index, item in enumerate(value)]
    if len(set(result)) != len(result):
        raise ValueError(f"{label} must not contain duplicates")
    return result


def _contract_field(value: Mapping[str, Any], canonical: str, *legacy: str) -> Any:
    """Read a canonical field while accepting unambiguous legacy aliases."""

    present = [(name, value[name]) for name in (canonical, *legacy) if name in value]
    if not present:
        return None
    selected_name, selected = present[0]
    for name, candidate in present[1:]:
        if candidate != selected:
            raise ValueError(
                f"D4 contract fields {selected_name!r} and {name!r} conflict"
            )
    return selected


def _source_checkpoint_ids(value: Mapping[str, Any]) -> Any:
    candidates: list[tuple[str, Any]] = []
    for name in ("d4_3_source_checkpoint_ids", "eligible_source_requirement_ids"):
        if name in value:
            candidates.append((name, value[name]))
    nested = value.get("d4_3")
    if isinstance(nested, Mapping) and "source_checkpoint_ids" in nested:
        candidates.append(("d4_3.source_checkpoint_ids", nested["source_checkpoint_ids"]))
    if not candidates:
        return None
    selected_name, selected = candidates[0]
    for name, candidate in candidates[1:]:
        if candidate != selected:
            raise ValueError(
                f"D4 contract fields {selected_name!r} and {name!r} conflict"
            )
    return selected


def _canonical_checkpoint_id(source_id: Any, eligible_ids: set[str]) -> Any:
    if not isinstance(source_id, str):
        return source_id
    # Some model responses preserve Markdown escapes from the prompt.
    candidate = re.sub(r"\\([_.])", r"\1", source_id)
    if candidate in eligible_ids:
        return candidate
    matches = []
    for eligible_id in eligible_ids:
        parts = eligible_id.split(".")
        alias = "criterion_" + "_".join(parts[-2:]) if len(parts) >= 2 else ""
        if candidate == alias:
            matches.append(eligible_id)
    return matches[0] if len(matches) == 1 else candidate


def eligible_d43_checkpoints(checkpoints: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            key: row[key]
            for key in ("id", "item", "objective", "initial_state", "trigger", "expected_transition")
            if key in row
        }
        for row in checkpoints
        if row.get("dimension") == D43_SOURCE_DIMENSION and row.get("kind") == "dynamic"
    ]


def _public_input(spec_path: Path, checkpoints: Sequence[Mapping[str, Any]]) -> tuple[str, str, str]:
    spec_bytes = spec_path.read_bytes()
    checkpoint_path = spec_path.parent / "checkpoints.jsonl"
    checkpoint_bytes = checkpoint_path.read_bytes()
    input_hash = sha256_bytes(spec_bytes + b"\n" + checkpoint_bytes)
    prompt = (
        "Game specification (public):\n\n"
        + spec_bytes.decode("utf-8-sig")
        + "\n\nEligible dynamic interaction requirements (public fields only):\n"
        + json.dumps(eligible_d43_checkpoints(checkpoints), ensure_ascii=False, indent=2)
    )
    return prompt, input_hash, sha256_bytes(checkpoint_bytes)


def _normalize_generated_body(value: Any, *, game_slug: str, eligible_ids: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("D4 contract output must be an object")
    target = _english(_contract_field(value, "target", "player_goal"), "target")
    legacy_operations = "allowed_operations" not in value and "legal_physical_operations" in value
    operations = _string_list(
        _contract_field(value, "allowed_operations", "legal_physical_operations"),
        "allowed_operations",
        maximum=12,
    )
    disallowed = [
        operation
        for operation in operations
        if any(term in operation.lower() for term in _DISALLOWED_TERMS)
    ]
    if legacy_operations:
        # Older contract responses included lifecycle controls in this list.
        operations = [operation for operation in operations if operation not in disallowed]
        if not operations:
            raise ValueError("allowed_operations must contain a gameplay operation")
    elif disallowed:
        raise ValueError(f"allowed operation is disallowed: {disallowed[0]!r}")
    art_direction = _string_list(
        _contract_field(value, "art_direction", "art_requirements"),
        "art_direction",
        maximum=12,
    )
    sample_size = value.get("art_sample_size", D41_ART_SAMPLE_SIZE)
    sample_seed = value.get("sample_seed", D41_SAMPLE_SEED)
    if isinstance(sample_size, bool) or not isinstance(sample_size, int) or not 1 <= sample_size <= 12:
        raise ValueError("art_sample_size must be an integer from 1 through 12")
    if isinstance(sample_seed, bool) or not isinstance(sample_seed, int) or sample_seed < 0:
        raise ValueError("sample_seed must be a non-negative integer")
    source_ids = _source_checkpoint_ids(value)
    if not isinstance(source_ids, list) or len(source_ids) != D43_QUESTION_COUNT:
        raise ValueError("d4_3_source_checkpoint_ids must contain exactly two IDs")
    normalized_sources = []
    for index, source_id in enumerate(source_ids):
        source_id = _canonical_checkpoint_id(source_id, eligible_ids)
        source_id = _english(source_id, f"d4_3_source_checkpoint_ids[{index}]")
        if source_id not in eligible_ids:
            raise ValueError(f"D4.3 source references ineligible checkpoint {source_id!r}")
        normalized_sources.append(source_id)
    if len(set(normalized_sources)) != D43_QUESTION_COUNT:
        raise ValueError("D4.3 source checkpoint IDs must be distinct")
    return {
        "game_slug": game_slug,
        "target": target,
        "allowed_operations": operations,
        "art_direction": art_direction,
        "art_sample_size": sample_size,
        "sample_seed": sample_seed,
        "d4_3": {
            "question_count": D43_QUESTION_COUNT,
            "fixed_question": D43_QUESTION_TEXT,
            "source_checkpoint_ids": normalized_sources,
            "evidence_source": "real_d4_2_frames_for_dynamic_d2_2",
            "requires_distinct_evidence": True,
            "runtime_question_policy": RUNTIME_QUESTION_POLICY,
        },
    }


def validate_d4_contract(
    contract: Mapping[str, Any],
    *,
    game_slug: str | None = None,
    d2_checkpoints: Sequence[Mapping[str, Any]] = (),
    expected_input_sha256: str | None = None,
) -> dict[str, Any]:
    if CONTRACT_SCHEMA_PATH.is_file():
        schema = json.loads(CONTRACT_SCHEMA_PATH.read_text(encoding="utf-8"))
        schema_errors = sorted(
            Draft202012Validator(schema).iter_errors(dict(contract)),
            key=lambda error: list(error.absolute_path),
        )
        if schema_errors:
            location = ".".join(str(part) for part in schema_errors[0].absolute_path) or "root"
            raise ValueError(f"D4 contract JSON schema violation at {location}: {schema_errors[0].message}")
    if contract.get("schema_version") != D4_CONTRACT_SCHEMA_VERSION:
        raise ValueError("D4 contract schema_version is invalid")
    if contract.get("contract_version") != D4_CONTRACT_VERSION:
        raise ValueError("D4 contract contract_version is invalid")
    if contract.get("design_version") != D4_CONTRACT_DESIGN_VERSION:
        raise ValueError("D4 contract design_version is invalid")
    slug = str(contract.get("game_slug", ""))
    if game_slug is not None and slug != game_slug:
        raise ValueError("D4 contract game_slug is invalid")
    if not slug:
        raise ValueError("D4 contract game_slug is required")
    if expected_input_sha256 is not None and contract.get("input_sha256") != expected_input_sha256:
        raise ValueError("D4 contract input hash is invalid")
    body = _normalize_generated_body(contract, game_slug=slug, eligible_ids={row["id"] for row in eligible_d43_checkpoints(d2_checkpoints)})
    for key, expected in body.items():
        if contract.get(key) != expected:
            raise ValueError(f"D4 contract field {key!r} is not normalized")
    expected_hash = contract_sha256(contract)
    if contract.get("contract_sha256") != expected_hash:
        raise ValueError("D4 contract SHA256 does not match its content")
    return dict(contract)


def _invoke_generator(
    generator: Any,
    prompt: str,
    slug: str,
    *,
    validator: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if callable(generator) and not hasattr(generator, "json_text"):
        try:
            value = generator(slug, prompt)
        except TypeError:
            value = generator(prompt)
    else:
        purpose = f"d4_contract_generation_{slug}"
        validated = getattr(generator, "json_text_validated", None)
        if validator is not None and callable(validated):
            value = validated(GENERATOR_INSTRUCTIONS, prompt, purpose, validator)
        else:
            value = generator.json_text(GENERATOR_INSTRUCTIONS, prompt, purpose)
    if not isinstance(value, dict):
        raise ValueError("contract generator must return a JSON object")
    return value


def _contract_prompt_version() -> str:
    return CONTRACT_PROMPT_VERSION


def _new_round_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(path)


def _existing_round(round_dir: Path, games: Sequence[GameConfig]) -> dict[str, Any] | None:
    manifest_path = round_dir / "contracts" / "manifest.json"
    if not manifest_path.is_file():
        return None
    manifest = _read_json(manifest_path)
    validate_round_manifest(manifest, round_dir=round_dir, expected_slugs=[game.slug for game in games])
    for game in games:
        spec = load_spec(game.spec)
        checkpoints = load_evaluator_checkpoints(spec)
        _prompt, input_hash, checkpoint_hash = _public_input(game.spec, checkpoints)
        input_record = manifest["inputs"].get(game.slug, {})
        if (
            input_record.get("input_sha256") != input_hash
            or input_record.get("checkpoint_jsonl_sha256") != checkpoint_hash
        ):
            raise ValueError(
                f"Existing D4 round input changed for {game.slug}; use a new round ID"
            )
        record = manifest["contracts"][game.slug]
        contract = _read_json(round_dir / "contracts" / str(record["path"]))
        validate_d4_contract(
            contract,
            game_slug=game.slug,
            d2_checkpoints=checkpoints,
            expected_input_sha256=input_hash,
        )
    return manifest


def build_round_contracts(
    round_dir: str | Path,
    games: Sequence[GameConfig] | None = None,
    *,
    config: Mapping[str, Any] | None = None,
    generator: Any | None = None,
    round_id: str | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Generate, validate, and lock one contract for every configured game."""

    active_config = dict(config) if config is not None else load_config()
    active_games = list(games or [])
    if not active_games:
        from code2play.config.project import games as configured_games

        active_games = configured_games(active_config)
    round_root = Path(round_dir).expanduser().resolve()
    round_id = round_id or round_root.name
    if not round_id or Path(round_id).name != round_id:
        raise ValueError("round_id must be a simple directory name")
    if round_root.name != round_id:
        raise ValueError("round_id must match the round directory name")
    existing = _existing_round(round_root, active_games)
    if existing is not None:
        return existing
    if generator is None:
        judge = create_dashscope_judge(
            round_root / "contracts" / "model_calls",
            model=DASHSCOPE_MODEL,
            max_output_tokens=int(active_config["judge"]["routes"]["contract_generation"]["max_output_tokens"]),
            enable_thinking=False,
            attempts=2,
            retry_delays_seconds=(2,),
            role="contract_generation",
        )
        generator = judge
    contract_records: dict[str, Any] = {}
    input_records: dict[str, Any] = {}
    for game in active_games:
        spec = load_spec(game.spec)
        checkpoints = load_evaluator_checkpoints(spec)
        eligible = eligible_d43_checkpoints(checkpoints)
        if len(eligible) < D43_QUESTION_COUNT:
            raise ValueError(f"{game.slug} does not have two eligible dynamic D2.2 checkpoints")
        prompt, input_hash, checkpoint_hash = _public_input(game.spec, checkpoints)
        eligible_ids = {row["id"] for row in eligible}

        def normalize(value: Any) -> dict[str, Any]:
            return _normalize_generated_body(
                value,
                game_slug=game.slug,
                eligible_ids=eligible_ids,
            )

        raw = _invoke_generator(generator, prompt, game.slug, validator=normalize)
        body = _normalize_generated_body(
            raw,
            game_slug=game.slug,
            eligible_ids=eligible_ids,
        )
        contract = {
            "schema_version": D4_CONTRACT_SCHEMA_VERSION,
            "contract_version": D4_CONTRACT_VERSION,
            "design_version": D4_CONTRACT_DESIGN_VERSION,
            "policy": D4_CONTRACT_POLICY,
            "round_id": round_id,
            "game_slug": game.slug,
            **body,
            "input_sha256": input_hash,
            "checkpoint_jsonl_sha256": checkpoint_hash,
            "generator": {
                "provider": DASHSCOPE_PROVIDER,
                "model": DASHSCOPE_MODEL,
                "api_style": DASHSCOPE_API_STYLE,
                "temperature": 0.0,
                "prompt_version": _contract_prompt_version(),
            },
        }
        contract["contract_sha256"] = contract_sha256(contract)
        validate_d4_contract(contract, game_slug=game.slug, d2_checkpoints=checkpoints, expected_input_sha256=input_hash)
        contract_records[game.slug] = contract
        input_records[game.slug] = {
            "input_sha256": input_hash,
            "checkpoint_jsonl_sha256": checkpoint_hash,
            "prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
        }
    contract_dir = round_root / "contracts"
    contract_dir.mkdir(parents=True, exist_ok=True)
    for slug, contract in contract_records.items():
        _write_json(contract_dir / f"{slug}.json", contract)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "round_id": round_id,
        "design_version": D4_CONTRACT_DESIGN_VERSION,
        "policy": D4_CONTRACT_POLICY,
        "provider": DASHSCOPE_PROVIDER,
        "model": DASHSCOPE_MODEL,
        "api_style": DASHSCOPE_API_STYLE,
        "temperature": 0.0,
        "prompt_version": _contract_prompt_version(),
        "created_at": timestamp or datetime.now(timezone.utc).isoformat(),
        "games": [game.slug for game in active_games],
        "inputs": input_records,
        "contracts": {slug: {"path": f"{slug}.json", "contract_sha256": value["contract_sha256"]} for slug, value in contract_records.items()},
    }
    manifest["manifest_sha256"] = manifest_sha256(manifest)
    _write_json(contract_dir / "manifest.json", manifest)
    # Keep a round-level pointer for workspace tooling while the canonical
    # manifest remains beside the contract files.
    _write_json(round_root / "manifest.json", manifest)
    return manifest


def build_contracts_for_round(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return build_round_contracts(*args, **kwargs)


def validate_round_manifest(manifest: Mapping[str, Any], *, round_dir: str | Path | None = None, expected_slugs: Sequence[str] | None = None) -> dict[str, Any]:
    if manifest.get("schema_version") != 1 or manifest.get("design_version") != D4_CONTRACT_DESIGN_VERSION:
        raise ValueError("D4 round manifest schema/design is invalid")
    if (
        manifest.get("policy") != D4_CONTRACT_POLICY
        or manifest.get("provider") != DASHSCOPE_PROVIDER
        or manifest.get("model") != DASHSCOPE_MODEL
        or manifest.get("api_style") != DASHSCOPE_API_STYLE
        or manifest.get("temperature") != 0.0
        or manifest.get("prompt_version") != CONTRACT_PROMPT_VERSION
    ):
        raise ValueError("D4 round manifest is not Qwen-only")
    round_id = manifest.get("round_id")
    if not isinstance(round_id, str) or not round_id or Path(round_id).name != round_id:
        raise ValueError("D4 round manifest round_id is invalid")
    if manifest.get("manifest_sha256") != manifest_sha256(manifest):
        raise ValueError("D4 round manifest SHA256 does not match")
    slugs = list(manifest.get("games", []))
    if not slugs or any(not isinstance(slug, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", slug) for slug in slugs) or len(set(slugs)) != len(slugs):
        raise ValueError("D4 round manifest game list is invalid")
    if expected_slugs is not None and slugs != list(expected_slugs):
        raise ValueError("D4 round manifest game order differs from the catalog")
    contracts = manifest.get("contracts")
    if not isinstance(contracts, Mapping) or set(contracts) != set(slugs):
        raise ValueError("D4 round manifest contracts are incomplete")
    inputs = manifest.get("inputs")
    if not isinstance(inputs, Mapping) or set(inputs) != set(slugs):
        raise ValueError("D4 round manifest inputs are incomplete")
    if round_dir is not None:
        root = Path(round_dir).expanduser().resolve()
        if root.name != str(round_id):
            raise ValueError("D4 round manifest round_id does not match its directory")
        pointer_path = root / "manifest.json"
        pointer = _read_json(pointer_path) if pointer_path.is_file() else None
        if pointer is None or pointer.get("manifest_sha256") != manifest.get("manifest_sha256"):
            raise ValueError("D4 round root manifest pointer does not match the locked manifest")
        if manifest_sha256(pointer) != manifest.get("manifest_sha256"):
            raise ValueError("D4 round root manifest pointer content is invalid")
        for slug in slugs:
            record = contracts[slug]
            if not isinstance(record, Mapping):
                raise ValueError(f"D4 contract record is invalid for {slug}")
            relative = Path(str(record.get("path") or ""))
            if relative.is_absolute() or ".." in relative.parts or relative.name != f"{slug}.json":
                raise ValueError(f"D4 contract path is unsafe for {slug}")
            path = root / "contracts" / relative
            contract = _read_json(path)
            if contract.get("round_id") != manifest.get("round_id") or contract.get("game_slug") != slug or contract.get("contract_sha256") != record.get("contract_sha256"):
                raise ValueError(f"D4 contract lock mismatch for {slug}")
            if contract_sha256(contract) != record.get("contract_sha256"):
                raise ValueError(f"D4 contract content hash mismatch for {slug}")
            required = (
                "schema_version", "contract_version", "design_version", "target",
                "allowed_operations", "art_direction", "art_sample_size", "sample_seed",
                "d4_3", "input_sha256", "checkpoint_jsonl_sha256",
            )
            if any(key not in contract for key in required):
                raise ValueError(f"D4 contract schema is incomplete for {slug}")
            if (
                contract.get("schema_version") != D4_CONTRACT_SCHEMA_VERSION
                or contract.get("contract_version") != D4_CONTRACT_VERSION
                or contract.get("design_version") != D4_CONTRACT_DESIGN_VERSION
                or contract.get("policy") != D4_CONTRACT_POLICY
            ):
                raise ValueError(f"D4 contract schema/version is invalid for {slug}")
            input_record = inputs[slug]
            if not isinstance(input_record, Mapping) or (
                contract.get("input_sha256") != input_record.get("input_sha256")
                or contract.get("checkpoint_jsonl_sha256") != input_record.get("checkpoint_jsonl_sha256")
            ):
                raise ValueError(f"D4 contract input hash is invalid for {slug}")
            generator = contract.get("generator")
            if (
                not isinstance(generator, Mapping)
                or generator.get("provider") != DASHSCOPE_PROVIDER
                or generator.get("model") != DASHSCOPE_MODEL
                or generator.get("api_style") != DASHSCOPE_API_STYLE
                or generator.get("temperature") != 0.0
                or generator.get("prompt_version") != CONTRACT_PROMPT_VERSION
            ):
                raise ValueError(f"D4 contract generator is not Qwen-only for {slug}")
    return dict(manifest)


def load_round_contract(round_dir: str | Path, game_slug: str, *, expected_manifest_sha256: str | None = None, d2_checkpoints: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    root = Path(round_dir).expanduser().resolve()
    manifest = validate_round_manifest(_read_json(root / "contracts" / "manifest.json"), round_dir=root)
    if expected_manifest_sha256 is not None and manifest["manifest_sha256"] != expected_manifest_sha256:
        raise ValueError("D4 round manifest hash drifted")
    record = manifest["contracts"].get(game_slug)
    if not isinstance(record, Mapping):
        raise KeyError(f"No D4 contract for {game_slug}")
    contract = _read_json(root / "contracts" / str(record["path"]))
    if d2_checkpoints:
        validate_d4_contract(contract, game_slug=game_slug, d2_checkpoints=d2_checkpoints)
    return contract


def assert_round_contract_manifest(round_dir: str | Path, expected_manifest_sha256: str) -> dict[str, Any]:
    manifest = validate_round_manifest(_read_json(Path(round_dir) / "contracts" / "manifest.json"), round_dir=round_dir)
    if manifest["manifest_sha256"] != expected_manifest_sha256:
        raise ValueError("D4 round manifest hash drifted")
    return manifest


__all__ = [
    "CONTRACT_GENERATOR_MODEL",
    "CONTRACT_PROMPT_VERSION",
    "CONTRACT_SCHEMA_PATH",
    "CONTRACT_VALIDATOR_MODELS",
    "D41_ART_SAMPLE_SIZE",
    "D41_SAMPLE_SEED",
    "D43_QUESTION_COUNT",
    "D43_QUESTION_TEXT",
    "D43_SOURCE_DIMENSION",
    "D4_CONTRACT_DESIGN_VERSION",
    "D4_CONTRACT_POLICY",
    "D4_CONTRACT_SCHEMA_VERSION",
    "D4_CONTRACT_VERSION",
    "GENERATOR_INSTRUCTIONS",
    "MAX_REVISION_ROUNDS",
    "RUNTIME_QUESTION_POLICY",
    "assert_round_contract_manifest",
    "build_contracts_for_round",
    "build_round_contracts",
    "contract_sha256",
    "eligible_d43_checkpoints",
    "load_round_contract",
    "manifest_sha256",
    "validate_d4_contract",
    "validate_round_manifest",
]
