# Questionnaire export

Human review is an export-only sidecar. It does not host a web server, collect
responses, or validate filled responses. Automatic scores remain authoritative
and are not changed by export.

## Export command

After a task has produced its evaluation artifacts:

```powershell
python main.py human export `
  --task-dir "C:\data\Code2Play-Workspace\runs\main_r1\tasks\snake__qwen3_7_plus__r01" `
  --output-dir "C:\data\Code2Play-Workspace\questionnaires\round-001" `
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
response-template row ordering match the Code2Play-Bench questionnaire contract.
Each image or text artifact is content-addressed by SHA256 and referenced by a
relative path.

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
