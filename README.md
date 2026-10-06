# Spec2Game-Bench

[![Paper](https://img.shields.io/badge/Paper-2610.04253-b31b1b.svg)](https://arxiv.org/abs/2610.04253)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](pyproject.toml)
[![Docs](https://img.shields.io/badge/Docs-Documentation-0A7EA4.svg)](docs/)
[![Dataset](https://img.shields.io/badge/Dataset-Benchmark-2E8B57.svg)](benchmark/)
[![Leaderboard](https://img.shields.io/badge/Leaderboard-coming%20soon-lightgrey.svg)](#results-and-leaderboard)

Spec2Game-Bench is a benchmark for testing whether large language models can translate detailed natural-language game specifications into complete, playable Pygame projects. It evaluates the whole artifact and its interaction trace rather than an isolated function or a single code snippet.

The benchmark is organized around 15 game families. Each family has one canonical task and nine controlled variants that change rules, parameters, maps, object types, or combinations of these factors. The variants test specification following when the requested behavior differs from familiar game conventions.

## Contents

- [Benchmark at a glance](#benchmark-at-a-glance)
- [Evaluation tracks](#evaluation-tracks)
- [Evaluation](#evaluation)
- [Quick start](#quick-start)
- [Generation and judging](#generation-and-judging)
- [Running the benchmark](#running-the-benchmark)
- [Repository layout](#repository-layout)
- [Data and artifacts](#data-and-artifacts)
- [Human review export](#human-review-export)
- [Results and leaderboard](#results-and-leaderboard)
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
renormalized. See [Evaluation protocol](docs/evaluation-protocol.md) for full
evidence and resume semantics.

## Quick start

The local checks below do not make paid provider requests:

```bash
python -m pip install -e '.[dev]'
python main.py validate
python main.py smoke
python main.py preflight
python -m pytest -q
python -m ruff check src scripts main.py tests
```

`smoke` and `preflight` use deterministic local checks unless `--live` is
specified. A live preflight and an official benchmark require credentials for
the selected candidate and the locked AWS Mantle judges.

## Generation and judging

Candidate source is generated in four locked stages (`state.py`, `game.py`,
`rendering.py`, and `main.py`) and validated as a five-file Python project.
The default example uses Qwen3.7 Plus through Alibaba DashScope. The complete
stage limits, retry policy, candidate interface, and isolation rules are in
[Generation protocol](docs/generation-protocol.md).

Evaluation roles, model routing, temperature, stateless request policy, and
run-manifest requirements are documented in [Judge routing](docs/judge-routing.md).
The D4 contract lifecycle and evaluator-only boundary are documented in
[D4 round contracts](docs/d4-round-contracts.md).

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

For the checked-in example configuration, set the candidate and judge keys and
then build the D4 contracts before generating candidates:

```bash
export DASHSCOPE_API_KEY='...'
export AWS_MANTLE_API_KEY='...'
export CODE2PLAY_WORKSPACE=/path/to/Code2Play-Workspace

python main.py contract build --track full150 --round-id study
python main.py benchmark \
  --model qwen3_7_plus \
  --track core15 \
  --run-id qwen-core \
  --round-id study
```

On PowerShell, use `$env:NAME = '...'` instead. The candidate key changes with
the selected model configuration; judge requests use `AWS_MANTLE_API_KEY` in
the example configuration. Use `--track full150` for the Full-150 run and
`--game`/`--variant` for a focused trial. `contract build --mock` is available
for local schema and lock tests only; mock contracts are not official evidence.

A run can be inspected without executing new tasks:

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

## Human review export

Human review is an export-only sidecar. It creates an anonymous public bundle
and a private mapping for internal audit; it does not host a server or alter
automatic scores. See [Questionnaire export](docs/questionnaire-export.md) for
the fixed item design and public/private boundary.

```bash
python main.py human export \
  --task-dir /path/to/task \
  --output-dir /path/to/questionnaire-round \
  --blind-id candidate-001
python main.py human validate \
  --bundle-dir /path/to/questionnaire-round/public/candidate-001
```

## Results and leaderboard

Official benchmark results and the public leaderboard will be linked here with
the paper release. Until then, use the reporting commands above for local run
summaries. Results from mock contracts or partial runs should not be reported
as official benchmark evidence.

## Documentation

- [Evaluation protocol](docs/evaluation-protocol.md)
- [Generation protocol](docs/generation-protocol.md)
- [Judge routing](docs/judge-routing.md)
- [Core-15 and Full-150](docs/dual_tracks.md)
- [Data format](docs/data-format.md)
- [D4 round contracts](docs/d4-round-contracts.md)
- [Questionnaire export](docs/questionnaire-export.md)
- [Final acceptance report](docs/final-acceptance-report.md)

## Citation

If you use Spec2Game-Bench, please cite the accompanying benchmark paper and
link to this repository. The accompanying preprint is available at
<https://arxiv.org/abs/2610.04253>.

```bibtex
@misc{spec2gamebench,
  title  = {Spec2Game Benchmark: Can LLMs Generate Complete Playable Games from Specifications?},
  author = {Spec2Game-Bench Authors},
  year   = {2026},
  url    = {https://github.com/Aurora1094/Spec2Game-Bench},
  eprint = {2610.04253},
  archivePrefix = {arXiv}
}
```
