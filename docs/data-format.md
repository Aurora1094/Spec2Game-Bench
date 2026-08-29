# Data format

The checked-in catalog is `benchmark/catalog.yaml`. It is serialized as
canonical JSON that is valid YAML, so it can be consumed by either YAML or JSON
loaders without changing ordering or hashes.

Each catalog entry contains:

```yaml
slug: snake
name: Snake
difficulty: easy
path: games/snake
window_size: [600, 800]
variants: []
checkpoint_count: 29
dimension_counts: {D2.1: 5, D2.2: 3, D2.3: 10, D2.4: 3, D2.5: 8}
```

Every game directory contains `game.yaml`, `spec.md`, and
`checkpoints.jsonl`. `game.yaml` reserves `variants: []`; variants are not
silently inferred or added.

## Specifications

`spec.md` starts with project metadata frontmatter and then the DOCX paragraph
body. The body is retained as UTF-8 text, including titles, lists, code spans,
numbers, and English or Chinese source values. The evaluator requires ordered
sections `# 1` through `# 7`. D4 is not embedded in the specification; its
contract is round-scoped.

## Checkpoint JSONL

Each line is one object with these fields:

```json
{
  "id": "snake.D2.2.01",
  "game_slug": "snake",
  "dimension": "D2.2",
  "item": "...",
  "objective": "...",
  "initial_state": "...",
  "trigger": "...",
  "expected_transition": "...",
  "detection_method": "...",
  "score_rubric": {"0": "...", "1": "...", "2": "..."},
  "source_order": 6
}
```

The source CSV mapping is:

| Source column | JSONL field |
| --- | --- |
| `Checkpoint ID` | `id` |
| `项目` | `item` |
| `测试目标` | `objective` |
| `Initial State` | `initial_state` |
| `Trigger/Event` | `trigger` |
| `Expected Transition` | `expected_transition` |
| `检测方式` | `detection_method` |
| `0分`, `1分`, `2分` | `score_rubric.0`, `.1`, `.2` |

The dimension is derived from the ID and checked against the explicit source
row. IDs are unique, use the game slug prefix, and are grouped in D2.1 through
D2.5 order. The official totals are 537 checkpoints: D2.1=97, D2.2=94,
D2.3=150, D2.4=66, and D2.5=130.

## Audit

`benchmark/conversion_audit.json` records each external DOCX/CSV filename and
SHA256, the converted specification-body hash, row count, and per-dimension
counts. Source files are deliberately not copied into this repository. Run
`python main.py validate` after any conversion.
