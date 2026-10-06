# Generation protocol

This document defines the locked candidate-generation procedure used by
Spec2Game-Bench. The README keeps only the public summary; this page contains
the full stage limits, retry policy, candidate contract, and isolation rules.

## Four locked stages

Candidate source is generated sequentially. Later stages receive the source and
API summaries required by the public generation contract from earlier stages.

| Stage | Output file | Normal limit | Hard limit |
| --- | --- | ---: | ---: |
| 1 | `state.py` | 4,000 tokens | 5,000 tokens |
| 2 | `game.py` | 7,000 tokens | 14,000 tokens |
| 3 | `rendering.py` | 5,000 tokens | 10,000 tokens |
| 4 | `main.py` | 2,000 tokens | 2,000 tokens |
| **Total** |  | **18,000** | **31,000** |

The candidate package must contain exactly:

```text
candidate/
  __init__.py
  state.py
  game.py
  rendering.py
  main.py
```

The adapter must expose `init`, `action`, `snapshot`, `render`, and `close`.
Candidate processes run in isolated working directories. Evaluator-only
checkpoint IDs, contracts, prompts, and judge outputs are written after the
candidate process exits and are never provided to the candidate.

## Example generation configuration

The default candidate in `configs/examples/qwen37_main.yaml` is Qwen3.7 Plus
through Alibaba DashScope. Generation uses temperature `0.2`, at most two
technical attempts per stage, a two-second retry delay, truncation detection,
and zero semantic repair attempts.

Technical retries do not receive execution feedback or score-based code repairs.
The candidate source is therefore determined by the staged prompts and the
model configuration, rather than by evaluator feedback.

## Workspace and reproducibility

Mutable candidates, traces, and reports are stored outside the Git checkout
under the workspace selected by `SPEC2GAME_WORKSPACE` or `--workspace`. The
legacy `CODE2PLAY_WORKSPACE` name remains accepted for existing runs. The
run manifest records the selected model configuration, track, round, prompt
and contract hashes, retry policy, and output paths. Re-running an official
track must use a fresh run ID and must not reuse candidates or scores from a
different track.

The official run procedure, including contract creation and resume behavior,
is described in the [evaluation protocol](evaluation-protocol.md).
