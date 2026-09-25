# D4 round contracts

D4 is intentionally round-scoped. A contract is generated at the start of
each main-experiment round for every catalog game, before candidate generation
or repeat evaluation.

## Inputs and output

The contract-generation request contains only:

- the selected game's `spec.md`; and
- the selected game's `checkpoints.jsonl`, restricted to public fields for
  eligible dynamic D2.2 requirements.

It does not contain candidate source, screenshots, prior scores, or judge
outputs. Qwen returns the target, legal physical operations, art direction,
art sample seed/size, and exactly two eligible D2.2 checkpoint IDs for D4.3.
Natural-language contract fields are validated as non-empty English strings.

The contract schema is `benchmark/schemas/d4_contract.schema.json` and has
version `round_v1`. Each contract records:

```text
round_id
game_slug
input_sha256
checkpoint_jsonl_sha256
generator provider/model/api_style/temperature/prompt_version
contract_sha256
```

## Manifest lock

The external round directory is:

```text
rounds/<round-id>/
  manifest.json
  contracts/
    manifest.json
    <game-slug>.json
    model_calls/
```

`contracts/manifest.json` is canonical; the round-level `manifest.json` is a
workspace pointer with the same content. The manifest records the round ID,
all 15 games in catalog order, model/policy identity, prompt version, input
hash records, contract hashes, and its own `manifest_sha256`.

Every benchmark task stores the same round ID and manifest hash. Before a
candidate is generated, sampled, resumed, or evaluated, the manifest and each
contract are revalidated. Hash drift or game-order drift is a hard error.

## Runtime use

The candidate never receives the contract. D4 sampling reuses the functionality
compiler programs and records the locked contract path and hashes in an
evaluator-only sample manifest. Candidates and repetitions in the same round
therefore see the same D4 contract while screenshots and visual questions stay
candidate-specific.

The default local smoke command uses deterministic mock contract output only
to test schema and lock behavior. Mock contracts are not official benchmark
evidence. Use `AWS_MANTLE_API_KEY` and `code2play contract build` for an
official round. The contract route is `qwen.qwen3-coder-next` in the checked-in
configuration.
