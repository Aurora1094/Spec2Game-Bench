# Evaluation protocol

The benchmark preserves the locked scoring semantics while expanding the game
catalog to 15 games. The official score is:

```text
g(D1) = clip((D1 - 40) / 20, 0, 1)
Final = 0.20*D1 + g(D1)*(0.50*D2 + 0.15*D3 + 0.15*D4)
```

D1 controls score contributions only through a continuous factor. D2, D3, and
D4 are measured for diagnosis whenever the candidate can produce valid evidence.
A missing valid dimension keeps the official total incomplete rather than
silently treating it as zero. All four weights are fixed and are not
renormalized.

## Generation

Candidate source is produced by four sequential Qwen calls:

1. `state.py`, maximum 3,000 output tokens
2. `game.py`, maximum 7,000 output tokens
3. `rendering.py`, maximum 4,000 output tokens
4. `main.py`, maximum 2,000 output tokens

The generation protocol uses temperature 0.2, two technical attempts, one
two-second retry delay, no stop-on-truncation policy, zero semantic retries,
and a 16,000-token total budget. Later prompts receive locked source files and
API summaries from earlier stages. Generated source is diagnosed and hashed at
each boundary; retries are transport retries, not score-based code repairs.

## Candidate isolation

The candidate package is validated as exactly five files and copied into an
isolated subprocess working directory. Its RPC adapter exposes only
`init`, `action`, `snapshot`, `render`, and `close`. State snapshots are
redacted and required to be JSON serializable. Evaluator-only checkpoint IDs,
rubrics, contracts, scoring prompts, and judge outputs are written only after
candidate processes exit.

## Judges and sampling

All candidate generation, action compilation, functionality scoring,
specification-deviation scoring, code-quality scoring, artistic scoring,
dynamic visual scoring, contract generation, and visual-question generation
route to the single locked model:

```text
provider: alibaba_dashscope
model: qwen3.7-plus
api_style: chat_completions
```

Judge temperature is 0.0, stateless, with one valid scoring response. The
action compiler and visual evaluator receive only the evidence and public
context needed for their role. API keys are environment-only and logs redact
authorization data.

## D4

D4.1 evaluates the screenshot set selected by the locked contract. D4.2 uses
the real compiled dynamic checkpoint traces and chronological frames. D4.3
selects two deterministic materially distinct frames from contract-selected
D2.2 sources, then asks Qwen to write exactly two questions. Local validation
fixes the question text, option order, answer binding, image binding, hashes,
and source slots. A judge or transport failure is a D4 judge gap, never a
candidate failure.

## CLI lifecycle

`contract build` locks the round before `benchmark` creates candidates. Resume
checks the round ID, contract manifest hash, normalized policy hash, generation
contract hashes, candidate hash, and evaluation policy. Any drift requires a
new run or task directory; old artifacts are not upgraded in place.
