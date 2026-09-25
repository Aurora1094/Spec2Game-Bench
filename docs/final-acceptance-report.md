# Spec2Game-Bench Final Acceptance Report

Date: 2026-08-29

## Scope

This report covers the local final acceptance of the standalone
Spec2Game-Bench project. It does not include a real Qwen request, a benchmark
run, an upload, or a Git commit.

## Delivered Layout

```text
Spec2Game-Bench/
  benchmark/
    catalog.yaml
    conversion_audit.json
    games/<15 games>/{game.yaml,spec.md,checkpoints.jsonl}
  configs/
  docs/
  scripts/convert_benchmark_data.py
  src/code2play/
    config/ d4/ evaluation/ execution/ generation/
    human_review/ planning/ providers/ reporting/
  tests/unit/ tests/integration/ tests/compatibility/
  main.py
```

All benchmark execution artifacts are scoped to an external workspace. The
repository has no `runs/`, `rounds/`, root `contracts/`, `ckpt/`,
`rendered_prompts/`, `candidates/`, or `questionnaires/` directory.

## Pilot Boundary and Module Mapping

| Pilot artifact | Current Spec2Game-Bench owner | Result |
|---|---|---|
| `project_config.py` | `config/project.py` | Current catalog and locked runtime policy |
| `benchmark_runner.py` | `execution/benchmark.py` | Current schema-v3 resumable batch/task state |
| `candidate_project.py` | `execution/candidate_project.py` | Five-file candidate validation and content hash |
| `evaluation_pipeline.py`, `scoring.py` | `evaluation/pipeline.py`, `evaluation/scoring.py` | Current D1-D4 assembly and official-total semantics |
| `protocol_policy.py`, `protocol_sampling.py`, `safe_artifacts.py` | corresponding `execution/` modules | Protocol-v4 execution, sampling, and artifact safety |
| `prompt_builder.py`, `staged_generation.py`, `request_planning.py` | `generation/prompt_builder.py`, `generation/staged.py`, `planning/requests.py` | Current prompt, staged generation, and no-send planning |
| `generation_clients.py`, `llm_clients/client_*` | `providers/dashscope.py` | Provider and role routing for the configured candidate and AWS Mantle judges; the OpenAI-compatible SDK is transport only |
| `reporting.py` | `reporting/reports.py` | Current report schema; legacy report inputs are rejected |
| `human_review/web_server.py` | `human_review/artifacts.py` plus `human export`/`human validate` | Static public/private questionnaire packages; no service command |
| `evaluator/contracts/d4/v5`, `v6`, `v7` | `d4/contracts.py` and round-scoped `round_v1` contracts | Old versions rejected; no old contract directory retained |
| `aws_credentials.py` | environment-only provider-key handling | No repository credential module |

The read-only Pilot checkout remains clean at `009464c`; no Pilot file was
changed.

## Data Conversion Audit

The external source directory contains 15 DOCX files and 15 CSV files. A fresh
external conversion matched the checked-in `benchmark/conversion_audit.json`:

| Measure | Verified value |
|---|---:|
| Games | 15 |
| Checkpoints | 537 |
| D2.1 / D2.2 / D2.3 / D2.4 / D2.5 | 97 / 94 / 150 / 66 / 130 |
| Per-game specification-body hashes | All matched |

Source DOCX/CSV files remain external and are not copied into the repository.

## D4 Round Flow

1. `contract build --mock --round-id round-001` writes one D4 contract for
   every game under an external workspace's `rounds/round-001/contracts/`.
2. The canonical `contracts/manifest.json` and root `manifest.json` must be
   identical and self-hash correctly.
3. A repeat build reuses the locked round byte-for-byte.
4. Contract content, root pointer, input hash, or round identifier drift fails
   validation before execution.
5. Task and batch run states require the current schema-v3 round, contract,
   and policy descriptors. Old states fail before API access.
6. D4 evidence, public questionnaire assets, and private answer keys are
   exported through the blind-bundle boundary; public validation detects
   response-template tampering.

## CLI Surface

Kept: `validate`, `preflight`, `contract build`, `benchmark`, `evaluate`,
`plan`, `smoke`, `human export`, and `human validate`.

Removed: `human-serve`, `human-response-validate`, legacy D4 contract
directories, and uncalled compiler/scoring judge constructors. The current
runtime uses the locked role-specific candidate and AWS Mantle judge routes.
`SemanticJudge`, `JudgeRouter`, test injection, and the OpenAI-compatible
provider transport remain intentionally supported.

## Verification Results

| Check | Result |
|---|---|
| `python -m compileall -q src main.py scripts` | Passed |
| `python -m ruff check src scripts main.py tests` | Passed |
| `python -m pytest -q` | 28 passed |
| `python main.py validate` | Passed: 15 games, 537 checkpoints, D2 counts above |
| `python main.py smoke` | Passed, `live: false` |
| `python main.py preflight` | Passed, `live_api_check: false` |
| External-workspace `contract build --mock --round-id round-001` | Passed; 15 contracts locked |
| Mock benchmark orchestration round binding | Passed; all 15 task calls shared one round ID and manifest hash |
| Installed `code2play validate` vs `python main.py validate` | Structurally identical JSON |
| Human export/validate integration | Public/private boundary, assets, order, blank template, leak checks, and tamper rejection passed |
| Compatibility integration | Old D4 versions, old run state, and old report inputs rejected |

## Live-Service Risk

No real provider call was made. Local preflight confirmed only that a
credential is configured and deliberately reported `live_api_check: false`.
The remaining operational evidence must be gathered later in an explicitly
authorized external workspace: one paid preflight request, real candidate
generation, and a full benchmark run to observe provider behavior, latency,
rate limits, cost, and real semantic-judge output.

## Delivery Integrity

No upload, `git commit`, `git push`, or Pilot modification was performed in
this acceptance round. Temporary mock rounds, conversion outputs, and tooling
caches were kept outside the repository; pre-existing project-local caches
were moved to the external temporary cache archive
`Spec2Game-Bench-ignored-caches-20260829`.
