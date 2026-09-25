# Core-15 and Full-150

Spec2Game-Bench exposes two independent evaluation tracks over the same
checked-in catalog. The candidate model is selected from the `models` section
of a runtime configuration. Judge routing is configured separately and is
locked into the run manifest.

## Track definitions

| Track | Scope | Instances per model | Generation calls per instance | Human-review records |
| --- | --- | ---: | ---: | ---: |
| **Core-15** | One canonical task from each of 15 families | 15 | 4 staged calls | 150 |
| **Full-150** | One canonical task plus nine controlled variants in each family | 150 | 4 staged calls | 1,500 |

The normal staged output limits are `4,000 / 7,000 / 5,000 / 2,000` tokens for
`state.py`, `game.py`, `rendering.py`, and `main.py`. Hard families use
`5,000 / 14,000 / 10,000 / 2,000`. Each stage allows at most two technical
attempts with a two-second retry delay. Truncation detection is enabled and
semantic repair attempts are disabled.

The one-attempt output-cap calculation is therefore:

```text
Core-15: 10 normal instances * 18,000 + 5 hard instances * 31,000 = 335,000
Full-150: 100 normal instances * 18,000 + 50 hard instances * 31,000 = 3,350,000
```

These are output limits, not expected usage. A second technical attempt or a
later explicit generation resume adds observed provider usage. The budget
command reports measured usage and does not treat caps as a spending limit.

## Independent runs

Core-15 and Full-150 are generated and evaluated independently:

- Candidate source is generated separately for every track and instance.
- Runtime traces, action-compiler outputs, visual evidence, and judge results
  are not shared across tracks.
- A round may share the locked D4 contract definitions, but each candidate is
  still sampled and evaluated independently.
- A complete Core run is averaged equally over 15 canonical tasks.
- A complete Full run is averaged equally over the 10 instances in each family,
  then equally over the 15 families.

The Full-150 family report also compares each canonical score with the mean of
its nine controlled variants. Variant IDs identify the catalog order; they do
not imply that a candidate was initialized from the canonical project.

## Selecting a candidate

The checked-in example uses Qwen3.7 Plus through Alibaba DashScope:

```yaml
models:
  - id: qwen3_7_plus
    name: Qwen3.7 Plus
    provider: alibaba_dashscope
    model: qwen3.7-plus
    api_style: chat_completions
    api_key_env: DASHSCOPE_API_KEY
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
```

Additional candidate entries can be supplied in a compatible configuration.
When more than one candidate is configured, pass one explicit model ID to
`plan`, `preflight`, `contract build`, or `benchmark`. Credentials are read
from environment variables and are never written to run artifacts.

## Inspecting a track without sending requests

`plan` writes a logical request plan and does not call a provider when no
candidate path is supplied:

```powershell
python main.py plan --model qwen3_7_plus --track core15
python main.py plan --model qwen3_7_plus --track full150
python main.py preflight --model qwen3_7_plus --track full150
```

Use `--game` to select a family. In Core-15 this selects its canonical
instance; in Full-150 it selects all ten instances in that family. Add
`--variant base` or `--variant var01` through `--variant var09` to select one
Full-150 instance. Core-15 accepts only `base`.

## Building contracts and running a track

The D4 contracts are generated and locked before candidate generation. Build a
full round once, then use the same round ID for independent track runs:

```powershell
python main.py contract build --track full150 --round-id study
python main.py benchmark --model qwen3_7_plus --track core15 `
  --run-id qwen-core --round-id study
python main.py benchmark --model qwen3_7_plus --track full150 `
  --run-id qwen-full --round-id study
```

The same commands work in Bash after replacing the PowerShell continuation
character with `\`. A focused pilot can select one family and variant:

```powershell
python main.py benchmark --model qwen3_7_plus --track full150 `
  --game snake --variant var09 --run-id pilot-snake --round-id pilot-snake
```

`contract build --mock` is a deterministic local fixture for schema and lock
tests. Mock contracts must not be used as benchmark evidence. If a round is
missing contracts, repeating the original contract command fills the missing
entries before the manifest is locked. A locked Core round cannot be expanded
in place to Full-150; start a new round.

## Resume and failure states

The run state distinguishes evaluation gaps from generation gaps:

- `needs_rescore` can be resumed with the same benchmark command after the
  missing evaluation stage is available.
- `needs_regeneration` requires `--resume-generation` and preserves completed
  earlier stages.
- A malformed or non-executable candidate is scored from its observed outcome
  under the D1-D4 protocol; no semantic repair is applied by the benchmark.
- A missing valid evaluation dimension leaves the official total incomplete.
  Fixed score weights are not renormalized.

Every resume validates the round ID, contract manifest hash, normalized policy
hash, generation-contract hashes, candidate hash, and evaluation policy. Any
drift requires a new run or task directory.

## Results, budget, and reports

```powershell
python main.py status --run-id qwen-full
python main.py report --run-ids qwen-core qwen-full
python main.py budget --model qwen3_7_plus --track full150 `
  --reference-run-ids pilot-snake
```

`track_report.json` records coverage, per-dimension scores, family-level
comparisons, and observed API usage. `report` groups runs by track and
compatible evaluation cohort. The budget report separates candidate
generation, text judging, vision judging, and shared round contracts. It uses
provider-reported usage when available and leaves cost fields empty when no
valid measurement or price snapshot exists.

## Data maintenance

`benchmark/catalog.yaml` stores the 15 canonical families and the 135 variant
instances. Each instance has a complete `spec.md`, `game.yaml`, and
`checkpoints.jsonl`; variant metadata records the source difference and its
canonical family. The submitted JSONL files are the evaluation source of
truth. The original source archives remain outside the repository.

To rebuild or import source data, use the scripts under `scripts/`, then run:

```powershell
python main.py validate
python -m pytest -q
```

The validator checks catalog order, checkpoint IDs, dimension totals, schemas,
prompt contracts, and the checked-in human-review policy.

## Human review

Each completed task can be exported as ten anonymous records: five functional
D2 anchors, one D4.1 visual item, two D4.2 dynamic-feedback items, and two
D4.3 records for evidence validity and action choice. Missing evidence remains
`cannot_rate`; it is not silently converted to a candidate zero.

```powershell
python main.py human export `
  --task-dir PATH_TO_TASK `
  --output-dir PATH_TO_QUESTIONNAIRE `
  --blind-id candidate-001
python main.py human validate `
  --bundle-dir PATH_TO_QUESTIONNAIRE/public/candidate-001
```

See [questionnaire-export.md](questionnaire-export.md) for the public/private
boundary and package schema.
