# Code2Play-Bench

Code2Play-Bench is a reproducible benchmark for staged Python game generation.
The checked-in benchmark contains 15 game specifications and 537 evaluator
checkpoints. Candidate generation, action compilation, D1-D4 semantic judging,
round-contract generation, and dynamic visual-question generation all use
`alibaba_dashscope/qwen3.7-plus`.

## Quick start

PowerShell:

```powershell
python -m pip install -e ".[dev]"
python main.py validate
python main.py smoke
```

Bash:

```bash
python -m pip install -e '.[dev]'
python main.py validate
python main.py smoke
```

The console entry point is equivalent after installation:

```text
code2play validate
python main.py validate
```

`validate` and the default `smoke` command make no paid API request. Use
`smoke --live` only when a real provider check is wanted.

## Provider and workspace

The API key is read only from `DASHSCOPE_API_KEY`; it is never written to a
config file or artifact. The OpenAI-compatible client is used only as the
DashScope transport. No alternate model adapter or AWS credential module is
part of this project.

All mutable experiment artifacts belong in an external workspace. Set the
workspace explicitly or use `CODE2PLAY_WORKSPACE`:

```powershell
$env:DASHSCOPE_API_KEY = "..."
$env:CODE2PLAY_WORKSPACE = "C:\data\Code2Play-Workspace"
python main.py contract build --round-id round-001
python main.py benchmark --run-id main_r1 --round-id round-001
```

```bash
export DASHSCOPE_API_KEY='...'
export CODE2PLAY_WORKSPACE=/data/Code2Play-Workspace
python main.py contract build --round-id round-001
python main.py benchmark --run-id main_r1 --round-id round-001
```

The workspace contains `private-configs/`, `rounds/<round-id>/`,
`runs/<run-id>/`, `candidates/`, and `questionnaires/`. The repository never
creates root-level `runs/`, checkpoint exports, rendered prompts, or candidate
projects.

## Commands

```text
code2play validate
code2play preflight [--live]
code2play contract build [--round-id ID]
code2play benchmark [--run-id ID] [--round-id ID]
code2play evaluate --game SLUG --candidate PATH
code2play plan [--game SLUG] [--candidate PATH]
code2play smoke [--live]
code2play human export --task-dir PATH --output-dir PATH
code2play human validate --bundle-dir PATH
```

`contract build` creates and validates one D4 contract for every game before a
benchmark run. `contract build --mock` is a local fixture mode only and must
not be used for official results. `plan` without `--candidate` writes a
no-send logical request plan; the candidate form samples a real candidate and
therefore requires the API key.

There is no questionnaire server and no command that validates or collects
filled human responses. The human-review surface is limited to anonymous
export and public-package integrity validation.

## Candidate interface

Every candidate is exactly this five-file package:

```text
candidate/
  __init__.py
  state.py
  game.py
  rendering.py
  main.py
```

The required factory is `create_gamebench_adapter(seed=0)`. The returned
adapter implements `init`, `action`, `snapshot`, `render`, and `close`.
State snapshots must be JSON serializable. Generation is performed in this
order, with the locked dependency source injected only into later stages:
`state.py`, `game.py`, `rendering.py`, `main.py`.

## Data and evaluation

The official data files are under `benchmark/games/<slug>/`. `spec.md`
preserves the DOCX body, while `checkpoints.jsonl` is the normalized source
of truth for all checkpoint fields and rubrics. The original DOCX and CSV
files remain external and are represented by hashes in
`benchmark/conversion_audit.json`. See [data-format.md](docs/data-format.md).

The official score uses D1-D4 weights `0.20/0.50/0.15/0.15`. D1 controls
contributions only; D2-D4 are still measured when valid evidence exists. The
sampling worker copies candidates into an isolated working directory and
candidate code never receives checkpoint IDs, contracts, scoring prompts, or
judge artifacts. See [evaluation-protocol.md](docs/evaluation-protocol.md).

D4 contracts are generated from only the public game specification and
checkpoint JSONL at the start of each main-experiment round. A manifest hash
locks those contracts for every candidate and repetition in that round. See
[d4-round-contracts.md](docs/d4-round-contracts.md).

## Re-converting source data

The converter requires the external source directory containing the 15 DOCX
and 15 CSV files. It does not copy those files into the repository:

```powershell
python scripts/convert_benchmark_data.py `
  --source "C:\path\to\Code2Play bench" `
  --project .
```

```bash
python scripts/convert_benchmark_data.py \
  --source '/path/to/Code2Play bench' \
  --project .
```

After conversion, run `python main.py validate` and `python -m pytest -q`.

## Human export

Human evidence is built from a completed task, then split into a public blind
bundle and a private mapping. Public assets are content-addressed and checked
for hash, path, ordering, scale, rateability, candidate/model leaks, automatic
scores, judge outputs, and answer keys. See
[questionnaire-export.md](docs/questionnaire-export.md).

The public questionnaire is available at
[Code2Play Questionnaire](https://aurora1094.github.io/Code2Play.github.io/).

## Compatibility

This repository is the new 15-game benchmark contract. Old runs, checkpoints,
reports, and embedded D4 contracts are intentionally incompatible and are not
migrated. Use a new external run ID and round ID.
