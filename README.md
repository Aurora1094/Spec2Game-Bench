

<p align="center">
  <img src="assets/spec2game-logo.png" alt="Spec2Game-Bench logo" width="560">
</p>



<p align="center">
  <a href="https://arxiv.org/abs/2610.04253"><img src="https://img.shields.io/badge/Paper-2610.04253-b31b1b.svg" alt="Paper: arXiv 2610.04253"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB.svg" alt="Python 3.10+"></a>
  <a href="docs/"><img src="https://img.shields.io/badge/Docs-Documentation-0A7EA4.svg" alt="Documentation"></a>
  <a href="benchmark/"><img src="https://img.shields.io/badge/Dataset-Benchmark-2E8B57.svg" alt="Dataset"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache--2.0-4E5D6C.svg" alt="Apache-2.0 license"></a>
</p>

**Paper:** *Spec2Game: Can LLMs Generate Complete Playable Games from Detailed Specifications?*

Spec2Game-Bench evaluates whether large language models can turn detailed natural-language game specifications into complete, playable Pygame projects. The benchmark focuses on **specification realization**: a project that runs is not necessarily a project that implements the requested behavior, feedback, rules, and termination conditions.

The benchmark contains 15 game families and 150 task instances. Each family has one canonical task and nine controlled variants that change rules, parameters, maps, object types, or combinations of these factors. Generated projects are evaluated with source-code, runtime, and visual evidence.

## Contents

- [At a glance](#at-a-glance)
- [Benchmark design](#benchmark-design)
- [Evaluation framework](#evaluation-framework)
- [Results from the paper](#results-from-the-paper)
- [Quick start](#quick-start)
- [Official evaluation](#official-evaluation)
- [Data and artifacts](#data-and-artifacts)
- [Citation](#citation)
- [License](#license)

## At a glance

| Property | Value |
| --- | --- |
| Game families | 15 |
| Task instances | 150 (15 canonical tasks + 135 controlled variants) |
| Complexity levels | Easy, Medium, Hard; 5 families per level |
| Core-15 track | 15 canonical tasks |
| Full-150 track | All 150 task instances |
| Formal candidate projects | 3,330 from 14 LLMs |
| Candidate split | 630 Core-15 + 2,700 Full-150 |
| Checkpoints | 537 canonical; 5,475 expanded catalog |
| Evaluation dimensions | D1-D4 |
| Human assessment | 585 generated projects |
| Ablation studies | 2 |
| Candidate output | Five-file Python project |

## Benchmark design

### Task construction

Each task uses a standardized seven-part specification:

1. Game overview
2. Scene and interface
3. Objects and states
4. Player interaction
5. Core rules and mechanics
6. Game flow and progression
7. Goal, feedback, and termination

The 15 families cover real-time reaction, shooting and combat, spatial exploration and platform adventure, logic and puzzle, and strategy and resource management. Each family contains a canonical task and nine standalone controlled variants. Variants preserve the family identity while changing one primary rule or design factor, making them useful for testing robustness to specification changes.

Implementation complexity is assigned with a mechanism-grounded rubric covering operation, object and rule, spatial and scene, adversarial behavior, and interface and information complexity. The resulting Easy, Medium, and Hard labels describe implementation demands rather than player difficulty.

### Evaluation tracks

Core-15 and Full-150 are separate evaluation tracks. Candidates, sampling traces, compiler outputs, and scores are generated independently for each track.

| Track | Instances | Intended use | Aggregation |
| --- | ---: | --- | --- |
| **Core-15** | 15 canonical tasks | Broad model comparison at fixed task coverage | Equal mean over the 15 families |
| **Full-150** | 150 tasks | Robustness to controlled specification changes | Equal mean over 10 instances within each family, then equal mean over 15 families |

## Evaluation framework

Spec2Game evaluates four complementary dimensions:

| Dimension | Components | Evidence |
| --- | --- | --- |
| **D1: Executability** | Syntax validity, dependency readiness, window creation, event handling, runtime stability, controlled termination | Deterministic local checks and a short isolated runtime probe |
| **D2: Specification Realization** | Game element, interaction, rule and mechanism, dynamic evolution, goal and termination modeling | Checkpoint-specific execution evidence and source code when required |
| **D3: Code Quality** | Maintainability, reliability, security, efficiency, conformance | Static analysis, AST checks, import probes, and semantic source judging |
| **D4: User-Facing Quality** | Visual presentation, dynamic feedback fidelity, visual actionability | Execution screenshots, dynamic checkpoint evidence, and visual questions |

D4 does not measure gameplay fun, novelty, or difficulty. It measures whether the running project presents its state and feedback clearly enough for a user to understand and choose an appropriate action.

The official score uses an executability gate:

```text
g(D1) = clip((D1 - 40) / 20, 0, 1)
Overall = 0.20*D1 + g(D1)*(0.50*D2 + 0.15*D3 + 0.15*D4)
```

D1 reduces the contribution of D2-D4 when the project is not reliably executable. The fixed weights are never renormalized when evidence is missing. See the [evaluation protocol](docs/evaluation-protocol.md) for scoring and evidence semantics.

## Results from the paper

The accompanying paper evaluates 14 LLMs on 3,330 generated projects:

- High executability does not guarantee faithful specification realization. Of 630 Core-15 projects, 387 pass all six D1 checks, but 87 of those still score below 60 on D2.
- Models are substantially stronger at Game Element Modeling than at Rule and Mechanism Modeling or Goal and Termination Modeling. The reported Core-15 averages are 80.83, 45.65, and 44.05 for these D2 components, respectively.
- User-facing quality shows a similar gap between appearance and interaction feedback. The reported D4 averages are 70.38 for Visual Presentation, 32.10 for Dynamic Feedback Fidelity, and 40.71 for Visual Actionability.
- Performance decreases as implementation complexity increases. Core-15 Overall averages are 71.19, 65.00, and 58.42 for Easy, Medium, and Hard families; Full-150 averages are 68.24, 59.61, and 51.23.
- Replacing minimal descriptions with detailed specifications raises the mean Core-15 Overall score from 50.59 to 68.62 in the first ablation. Adding a checkpoint-derived behavioral checklist provides only a small, model-dependent change.

See the [Spec2Game paper](https://arxiv.org/abs/2610.04253) for complete model tables, ablations, human-assessment results, and appendix rubrics.

## Quick start

The project requires Python 3.10 or newer. Install the package and development dependencies from the repository root:

```bash
python -m pip install -e '.[dev]'
```

The canonical installed command is `spec2game`. The previous `code2play`
command remains available as a compatibility alias for existing scripts.

Run deterministic local checks without paid provider requests:

```bash
python main.py validate
python main.py smoke
python main.py preflight
python -m pytest -q
python -m ruff check src scripts main.py tests
```

`smoke` and `preflight` use local checks unless `--live` is specified. All mutable outputs should be written outside the Git checkout with `SPEC2GAME_WORKSPACE` or `--workspace`. The previous `CODE2PLAY_WORKSPACE` name remains accepted for existing runs.

## Official evaluation

An official run requires credentials for the selected generation provider and the locked judge providers. Build the D4 contracts before generation:

```bash
python main.py contract build --track full150 --round-id study
```

Then run a track, for example:

```bash
python main.py benchmark \
  --model qwen3_7_plus \
  --track core15 \
  --run-id qwen-core \
  --round-id study
```

The full staged-generation procedure is documented in [Generation protocol](docs/generation-protocol.md). Judge models, request policy, and evidence boundaries are documented in [Judge routing](docs/judge-routing.md). The D4 lock procedure is documented in [D4 round contracts](docs/d4-round-contracts.md).

## Data and artifacts

The checked-in `benchmark/` directory contains the normalized public catalog. Each instance includes a specification, a game configuration, and `checkpoints.jsonl`. `benchmark/conversion_audit.json` records source file hashes and conversion counts. Original DOCX and CSV files remain external and are not copied into the repository.

Generated candidates, contracts, traces, reports, and questionnaire bundles are written under the external workspace. See [Data format](docs/data-format.md) and [Questionnaire export](docs/questionnaire-export.md) for the public data and human-review boundaries.

The evaluator executes generated code in isolated working directories. Run official evaluations in a controlled environment and do not place provider credentials in the repository or in artifacts shared for review.

## Repository layout

```text
Spec2Game-Bench/
|-- benchmark/                  # Catalog, specifications, checkpoints, schemas
|-- configs/examples/           # Reproducible runtime configurations
|-- docs/                       # Protocol, track, data, D4, and review docs
|-- experiments/                # Experiment launch helpers
|-- scripts/                    # Source-data conversion and maintenance tools
|-- src/spec2game/              # Generation, execution, evaluation, and reporting
|-- tests/                      # Unit, integration, and compatibility tests
|-- main.py                     # Source-checkout CLI entry point
|-- pyproject.toml              # Package metadata and dependencies
|-- CITATION.cff                # Machine-readable citation metadata
|-- LICENSE                     # Apache-2.0 license
`-- README.md
```



## Citation

If you use Spec2Game-Bench, please cite:

The repository also provides the same metadata in [CITATION.cff](CITATION.cff)
for GitHub's citation tools and other reference managers.

```bibtex
@article{cai2026spec2game,
  title         = {Spec2Game: Can LLMs Generate Complete Playable Games from Detailed Specifications?},
  author        = {Cai, Yixue and Zhao, Yuzhe and Chao, Hanxiang and Ma, Qingsen and Xiong, Ziheng and Qi, Jinhu and King, Irwin},
  year          = {2026},
  eprint        = {2610.04253},
  archivePrefix = {arXiv},
  primaryClass  = {cs.AI},
  url           = {https://arxiv.org/abs/2610.04253}
}
```

## License

Spec2Game-Bench is released under the [Apache License 2.0](LICENSE).

