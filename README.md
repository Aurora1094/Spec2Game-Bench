# Spec2Game-Bench

Spec2Game-Bench is the benchmark implementation for testing whether large
language models can translate detailed natural-language game specifications
into complete, playable Pygame projects. It evaluates the whole artifact and
its interaction trace rather than an isolated function or a single code
snippet.

The benchmark is organized around 15 game families. Each family has one
canonical task and nine controlled variants that change rules, parameters,
maps, object types, or combinations of these factors. The variants are
designed to test specification following when the requested behavior differs
from familiar game conventions.

## Contents

- [Benchmark at a glance](#benchmark-at-a-glance)
- [Evaluation tracks](#evaluation-tracks)
- [Evaluation](#evaluation)
- [Generation protocol](#generation-protocol)
- [Installation](#installation)
- [Running the benchmark](#running-the-benchmark)
- [Repository layout](#repository-layout)
- [Data and artifacts](#data-and-artifacts)
- [Human review export](#human-review-export)
- [Documentation](#documentation)
- [Citation](#citation)

## Benchmark at a glance

| Property | Value |
| --- | --- |
| Game families | 15 |
| Difficulty split | 5 Easy, 5 Medium, 5 Hard |
| Canonical tasks | 15 |
| Controlled variants | 135 (9 per family) |
| Core-15 instances | 15 canonical tasks |
| Full-150 instances | 15 canonical tasks + 135 variants |
| Canonical checkpoints | 537 |
| Full-150 checkpoints | 5,475 |
| Evaluation dimensions | D1-D4 |
| Candidate output | Five-file Python project |
| Generation protocol | Four sequential source stages |

The checked-in catalog is ordered and hash-audited. It contains the complete
specification and checkpoint data needed to reproduce the benchmark definition;
generated candidates and evaluation traces are kept in an external workspace.

## Evaluation tracks

Core-15 and Full-150 are separate evaluation tracks. A model generates a new
candidate for every instance in the selected track; candidates, sampling
traces, compiler outputs, and scores are not reused across tracks.

| Track | Instances | Intended use | Aggregation |
| --- | ---: | --- | --- |
| **Core-15** | 15 canonical tasks | Broad model comparison at fixed task coverage | Equal mean over the 15 canonical tasks |
| **Full-150** | 150 tasks | Robustness to controlled specification changes | Equal mean over 10 instances within each family, then equal mean over 15 families |

For Full-150, the base task and its nine variants form one family. A complete
Full-150 run therefore supports both overall scoring and within-family
variant-versus-canonical analysis.

## Evaluation

Each generated project is evaluated with source, runtime, and visual evidence.

| Dimension | What it measures |
| --- | --- |
| **D1: Executability** | Whether the submitted project satisfies the runtime and interface contract. |
| **D2: Specification realization** | Whether the implemented game state, interactions, rules, dynamics, and termination behavior match the specification. D2 is decomposed into D2.1-D2.5. |
| **D3: Code quality** | Structural and semantic quality of the generated source. |
| **D4: User-facing quality** | Static appearance, dynamic feedback, and visual-question evidence from the running game. |

The official score uses the locked continuous D1 contribution factor:

```text
g(D1) = clip((D1 - 40) / 20, 0, 1)
Final = 0.20*D1 + g(D1)*(0.50*D2 + 0.15*D3 + 0.15*D4)
```

D1 controls the contribution of D2-D4 through `g(D1)`. D2-D4 are still
measured for diagnosis whenever valid evidence exists. If a valid dimension is
missing, the official total remains incomplete; the fixed weights are never
renormalized. See [Evaluation protocol](docs/evaluation-protocol.md) for the
full evidence and resume semantics.

## Generation protocol

Candidate source is generated in four locked stages. Later stages receive the
source and API summaries required by the public generation contract from
earlier stages.

| Stage | Output file | Normal limit | Hard limit |
| --- | --- | ---: | ---: |
| 1 | `state.py` | 4,000 tokens | 5,000 tokens |
| 2 | `game.py` | 7,000 tokens | 14,000 tokens |
| 3 | `rendering.py` | 5,000 tokens | 10,000 tokens |
| 4 | `main.py` | 2,000 tokens | 2,000 tokens |
| **Total** |  | **18,000** | **31,000** |

The default candidate in `configs/examples/qwen37_main.yaml` is Qwen3.7 Plus
through Alibaba DashScope. Generation uses temperature `0.2`, at most two
technical attempts per stage, a two-second retry delay, truncation detection,
and zero semantic repair attempts. Technical retries do not receive execution
feedback or score-based code repairs.

Every candidate is validated as exactly this package:

```text
candidate/
  __init__.py
  state.py
  game.py
  rendering.py
  main.py
```

The adapter must expose `init`, `action`, `snapshot`, `render`, and `close`.
Candidate processes run in isolated working directories, and evaluator-only
checkpoint IDs, contracts, prompts, and judge outputs are written after the
candidate process exits.

### Judge routing

The example configuration routes evaluation roles as follows:

| Role | Model | Provider |
| --- | --- | --- |
| Action compilation, D2, and D3 | `qwen.qwen3-235b-a22b-2507` | AWS Bedrock Mantle |
| D4 visual scoring and visual questions | `qwen.qwen3-vl-235b-a22b-instruct` | AWS Bedrock Mantle |
| D4 contract generation | `qwen.qwen3-coder-next` | AWS Bedrock Mantle |

Judge temperature is `0.0`, requests are stateless, and explicit reasoning is
disabled. The routing policy is locked into the run and recorded with its
manifest.

## Installation

The project requires Python 3.10 or newer. Install the package and development
dependencies from the repository root:

```bash
python -m pip install -e '.[dev]'
```

The distribution and catalog are named `spec2game-bench`. The package keeps
the existing `code2play` Python namespace, console entry point, and
`CODE2PLAY_*` environment-variable prefix for backward compatibility.
`python main.py ...` is equivalent when working from a source checkout.

## Running the benchmark

All mutable outputs should be placed outside the Git checkout. Set a workspace
explicitly with `CODE2PLAY_WORKSPACE` or pass `--workspace`.

### Local validation

These commands do not make paid provider requests:

```bash
python main.py validate
python main.py smoke
python main.py preflight
python -m pytest -q
python -m ruff check src scripts main.py tests
```

`smoke` and `preflight` use deterministic local checks unless `--live` is
specified. A live preflight and an official benchmark require the credentials
for the selected candidate and the locked AWS Mantle judges.

### Official run

For the checked-in example configuration, set:

```bash
export DASHSCOPE_API_KEY='...'
export AWS_MANTLE_API_KEY='...'
export CODE2PLAY_WORKSPACE=/path/to/Code2Play-Workspace
```

On PowerShell, use `$env:NAME = '...'` instead. The candidate key changes with
the selected model configuration; judge requests use `AWS_MANTLE_API_KEY` in
the example configuration.

Build and lock the D4 contracts before generating candidates:

```bash
python main.py contract build --track full150 --round-id study
```

Then run either track:

```bash
python main.py benchmark \
  --model qwen3_7_plus \
  --track core15 \
  --run-id qwen-core \
  --round-id study

python main.py benchmark \
  --model qwen3_7_plus \
  --track full150 \
  --run-id qwen-full \
  --round-id study
```

Use `--game` and `--variant` for a focused trial. `contract build --mock` is
available for local schema and lock tests only; mock contracts are not official
benchmark evidence. A run can be inspected or summarized without executing
new tasks:

```bash
python main.py status --run-id qwen-full
python main.py report --run-ids qwen-core qwen-full
```

The resume policy distinguishes missing evaluation results from an incomplete
generation stage. Use `--resume-generation` only when the run state explicitly
requests it.

## Repository layout

```text
Spec2Game-Bench/
|-- benchmark/                  # Catalog, specifications, checkpoints, schemas
|-- configs/examples/           # Reproducible runtime configurations
|-- docs/                       # Protocol, track, data, D4, and review docs
|-- experiments/                # Experiment launch helpers
|-- scripts/                    # Source-data conversion and maintenance tools
|-- src/code2play/
|   |-- config/                 # Catalog, policy, and workspace resolution
|   |-- generation/             # Staged generation and prompt contracts
|   |-- execution/              # Isolation, sampling, and resumable runs
|   |-- evaluation/             # D1-D4 evaluation and score assembly
|   |-- d4/                     # Round contracts and visual questions
|   |-- providers/              # Provider and role routing
|   |-- human_review/           # Blind questionnaire export and validation
|   |-- planning/               # No-send and live request plans
|   `-- reporting/              # Track reports and budget summaries
|-- tests/                      # Unit, integration, and compatibility tests
|-- main.py                     # Source-checkout CLI entry point
|-- pyproject.toml              # Package metadata and dependencies
`-- README.md
```

Generated candidates, contracts, traces, reports, and questionnaire bundles
are written under the external workspace:

```text
Code2Play-Workspace/
|-- private-configs/
|-- rounds/<round-id>/          # Locked D4 contracts and manifest
|-- runs/<run-id>/              # Candidates, traces, evaluations, reports
|-- candidates/                 # Candidate snapshots
`-- questionnaires/             # Public blind bundles and private mappings
```

## Data and artifacts

The checked-in `benchmark/` directory contains the normalized public catalog.
Each instance includes a specification, a game configuration, and
`checkpoints.jsonl`. The canonical catalog has 537 checkpoints; the expanded
Full-150 catalog has 5,475. `benchmark/conversion_audit.json` records source
file hashes and conversion counts. Original DOCX and CSV files remain external
and are not copied into the repository.

To rebuild the catalog from an external source directory:

```bash
python scripts/convert_benchmark_data.py \
  --source /path/to/Spec2Game-source \
  --project .
python main.py validate
```

The D4 contract is generated once per game at the beginning of a round from
the public specification and eligible checkpoint fields. Its manifest and
input hashes are locked before candidate generation; candidates never receive
the contract or evaluator-only artifacts. See
[D4 round contracts](docs/d4-round-contracts.md).

## Human review export

Human review is an export-only sidecar. It creates an anonymous public bundle
and a private mapping for internal audit; it does not host a server or alter
automatic scores.

```bash
python main.py human export \
  --task-dir /path/to/task \
  --output-dir /path/to/questionnaire-round \
  --blind-id candidate-001
python main.py human validate \
  --bundle-dir /path/to/questionnaire-round/public/candidate-001
```

See [questionnaire export](docs/questionnaire-export.md) for the fixed item
design and public/private boundary.

## Documentation

- [Evaluation protocol](docs/evaluation-protocol.md)
- [Core-15 and Full-150](docs/dual_tracks.md)
- [Data format](docs/data-format.md)
- [D4 round contracts](docs/d4-round-contracts.md)
- [Questionnaire export](docs/questionnaire-export.md)

## Citation

If you use Spec2Game-Bench, please cite the accompanying benchmark paper and
link to this repository:

```bibtex
@misc{spec2gamebench,
  title  = {Spec2Game Benchmark: Can LLMs Generate Complete Playable Games from Specifications?},
  author = {Spec2Game-Bench Authors},
  year   = {2026},
  url    = {https://github.com/Aurora1094/Spec2Game-Bench}
}
```
