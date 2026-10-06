# Questionnaire export

Human review is an export-only sidecar. It does not host a web server, collect
responses, or validate filled responses. Automatic scores remain authoritative
and are not changed by export.

## Fixed ten-item design

Exports use the pre-registered fixed ten-item design. Each candidate game
always yields exactly ten independent response records:

- Five D2 functional-behavior anchors: one fixed checkpoint from each of
  D2.1 through D2.5.
- One D4.1 overall visual-quality item using the existing screenshot set.
- Two D4.2 overall dynamic-feedback items using fixed dynamic checkpoints.
- Two D4.3 records for the first visual-question slot: evidence validity and
  action choice.

If an anchor's evidence is unavailable, its record is still exported as
`cannot_rate`; it is never omitted or converted to a zero. The selected
checkpoint IDs and policy hash remain private. The public manifest carries the
design ID, policy hash, and construct counts without exposing benchmark-internal
IDs. The ten-item design produces 150 records for Core-15 and 1,500 records for
Full-150.

The source sidecar is rebuilt at `evaluation/human_review/source` whenever its
policy hash differs from the checked-in policy.

## Export command

After a task has produced its evaluation artifacts:

```powershell
python main.py human export `
  --task-dir "C:\data\Spec2Game-Workspace\runs\main_r1\tasks\snake__qwen3_7_plus__r01" `
  --output-dir "C:\data\Spec2Game-Workspace\questionnaires\round-001" `
  --blind-id candidate-001
```

The same command works in Bash with ordinary path quoting. `human validate`
checks only the public package:

```text
python main.py human validate --bundle-dir PATH/public/candidate-001
```

## Package layout

```text
<questionnaire-round>/
  public/<blind-id>/
    manifest.json
    items.jsonl
    response_template.jsonl
    asset_index.json
    assets/sha256/<prefix>/<sha256>.<ext>
  private/<blind-id>.json
```

Public item ordering, scales, `rateability`, cannot-rate distinction, and
response-template row ordering match the Spec2Game-Bench questionnaire contract.
Each image or text artifact is content-addressed by SHA256 and referenced by a
relative path. The public `items.jsonl` and response-template fields remain
unchanged, so a client that renders them dynamically needs no schema update.

## Public/private boundary

The public bundle contains no candidate or judge model name, automatic score,
judge output or rationale, internal checkpoint ID, answer key, absolute path,
run/task ID, API key, or private mapping. The private mapping contains the
candidate hash, task path, automatic evidence, and D4 answer keys for internal
audit only.

Validation checks manifest hashes, JSONL parsing, item/template identity and
order, scale/rating shape, relative asset paths, asset hashes, referenced asset
existence, candidate/model leaks, internal checkpoint identifiers, automatic
fields, answer keys, and Windows/POSIX absolute paths. A failure stops export.

When visual evidence or a judge response is unavailable, the item is exported
as `cannot_rate`; it is never converted to a zero and never attributed to the
candidate without explicit candidate evidence.
