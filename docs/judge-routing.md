# Judge routing

This document records the example judge configuration used by
Spec2Game-Bench. Routing is part of the locked run configuration and is saved
in the run manifest so that scores can be audited and reproduced.

## Example role routing

| Role | Model | Provider |
| --- | --- | --- |
| Action compilation, D2, and D3 | `qwen.qwen3-235b-a22b-2507` | AWS Bedrock Mantle |
| D4 visual scoring and visual questions | `qwen.qwen3-vl-235b-a22b-instruct` | AWS Bedrock Mantle |
| D4 contract generation | `qwen.qwen3-coder-next` | AWS Bedrock Mantle |

The exact model identifiers and provider settings come from the selected
configuration file. Do not mix judge outputs from different routing policies
within one official run.

## Request policy

Judge temperature is `0.0`, requests are stateless, and explicit reasoning is
disabled. The routing policy, model configuration, prompt hashes, and request
metadata are locked into the run manifest.

The candidate model key and judge key are separate credentials in the example
configuration. Candidate generation uses `DASHSCOPE_API_KEY`; judge requests
use `AWS_MANTLE_API_KEY`. Never commit either credential or place it in a
candidate workspace that is distributed for review.

## Evidence boundary

Judges receive only the evidence allowed by the relevant evaluation dimension.
The D4 round contract is generated before candidate generation and is kept in
the evaluator workspace. Candidates do not receive the contract, evaluator-only
checkpoint IDs, judge prompts, or previous scores. See
[D4 round contracts](d4-round-contracts.md) for the contract lifecycle and
hash-lock rules.
