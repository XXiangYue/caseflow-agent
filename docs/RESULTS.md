# Measured results and interpretation

Raw tools and task tools each achieved 72/72 on the synthetic main sample (42 actionable, 30 blocked); task tools used 29.7% fewer input tokens. Twelve real-service fault expectations passed.

The workflow fixtures and approval/user simulator are synthetic. On-demand Skills achieved 71/72 and a higher cost upper bound; W1 task tools plus full SOP is the default. Per-service idempotency does not promise distributed rollback or exactly-once arbitrary effects.

## Evidence and reproduction

The original commit is `f6818662fdf4d845732545c34b63776a3960b694`. The measurement date is 2026-11-01.
`results/SOURCE_MANIFEST.json` lists original file hashes. `results/` contains
per-trial numeric/state exports, not all original databases or model transcripts.
Private workstation paths were normalized. Benchmark source text, downloaded
models, credentials and API request identifiers are excluded. Constructed Quality
Gate corpus data is published because it was authored for this experiment.

Run `uv run python scripts/verify_results.py` to recompute primary numbers.
The script verifies observed numerators, denominators and token totals against
the published summaries. It does not independently validate model judgments.
Fresh-run instructions are in [RUNNING.md](RUNNING.md).

## Additional findings to preserve



All three tool configurations use the same business task set. W0 raw/full-SOP and W1 task/full-SOP each completed 72/72; W2 task/on-demand-Skills completed 71/72. W0 input was 2,264,905 tokens; W1 1,592,024; W2 1,387,457. Despite lower input, W2 used a higher conservative cost bound than W1, so it is not the recommended default. The 12 fault witnesses execute actual services, while their task facts/approvals are synthetic. No real-user time saving is asserted.

