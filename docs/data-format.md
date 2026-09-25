# Data format

The checked-in catalog is `benchmark/catalog.yaml`. It is serialized as
canonical JSON that is also valid YAML, so YAML and JSON loaders preserve the
same ordering and hashes.

## Catalog entries

Each canonical family entry contains:

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

Every instance directory contains `game.yaml`, `spec.md`, and
`checkpoints.jsonl`. Canonical entries reserve the ordered list of their nine
variant slugs. Variant entries have `variant_id` and `family_slug` fields and
do not infer additional variants at load time.

The complete catalog contains 15 canonical instances and 135 variants. The
canonical checkpoint totals are:

| Dimension | Checkpoints |
| --- | ---: |
| D2.1 | 97 |
| D2.2 | 94 |
| D2.3 | 150 |
| D2.4 | 66 |
| D2.5 | 130 |
| **Total** | **537** |

Across Full-150, the corresponding totals are D2.1 `992`, D2.2 `952`, D2.3
`1,540`, D2.4 `672`, and D2.5 `1,319`, for `5,475` checkpoints in total.

## Specifications

`spec.md` begins with project metadata frontmatter and then preserves the
source document body as UTF-8 text. Paragraph order, headings, lists, code
spans, numbers, and source-language values are retained. The evaluator expects
the ordered specification sections `# 1` through `# 7`.

D4 is not embedded in an instance specification. Its visual contract is
generated and locked at round scope from the public specification and eligible
checkpoint fields.

## Checkpoint JSONL

Each line in `checkpoints.jsonl` is one checkpoint object:

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

The converter maps the source spreadsheet fields for checkpoint ID, project
item, test objective, initial state, trigger/event, expected transition,
detection method, and the 0/1/2-point rubric to the normalized fields above.
The dimension is derived from the checkpoint ID and checked against the source
row. IDs are unique, use the game slug prefix, and are ordered by D2.1 through
D2.5 within each instance.

## Variants

Variant directories use the same three-file instance format. Their
`variation.json` records the source difference, changed or added checkpoints,
and the canonical correspondence. Variation types include parameter, rule,
map, object type, object count, and combinations of these categories.

The final submitted JSONL is the evaluation source of truth. Variant import
and audit scripts can reconstruct the checked-in files from an external source
archive, but official evaluation does not call a model to generate rubrics or
checkpoint definitions.

## Conversion audit

`benchmark/conversion_audit.json` records each external specification and
checkpoint source filename and SHA256, the converted specification-body hash,
row count, and per-dimension counts. Source archives are deliberately kept
outside the repository.

After importing or rebuilding data, run:

```bash
python main.py validate
```

Validation checks catalog order, instance counts, checkpoint schemas, ID
prefixes, dimension totals, specification sections, conversion hashes, prompt
contracts, and the locked evaluation policy.
