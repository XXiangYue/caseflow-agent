# CaseFlow

An MCP Agent that revises knowledge and closes tickets through two real services with approvals and durable receipts.

## Measured outcome

Raw tools and task tools each achieved 72/72 on the synthetic main sample (42 actionable, 30 blocked); task tools used 29.7% fewer input tokens. Twelve real-service fault expectations passed.

**Scope and negative findings:** The workflow fixtures and approval/user simulator are synthetic. On-demand Skills achieved 71/72 and a higher cost upper bound; W1 task tools plus full SOP is the default. Per-service idempotency does not promise distributed rollback or exactly-once arbitrary effects.

Measurements were made on **2026-11-01** in the original integrated workspace.
The standalone packaging was prepared on **2026-11-05**. Packaging checks are
reported separately in `VALIDATION.json`; they are not new model benchmark runs.

## Quick start

Use **Python 3.12**, `uv`, and macOS or Linux. Run commands from this checkout.
Docker is also required for actual execution/service checks.

```bash
git clone https://github.com/XXiangYue/caseflow-agent.git
cd caseflow-agent
uv sync --locked
uv run pytest -q
uv run python scripts/verify_results.py
```


Inference requires `OUTCOMES_API_KEY` in the process environment. Supply it using
your normal secret manager; no key is required for tests or saved-result verification.
`OUTCOMES_API_BASE` and `OUTCOMES_MODEL` are optional. The evaluated model identifiers
are `deepseek-flash` and `deepseek-v4-pro`. Historical peak-equivalent prices in
`model.py` describe the original accounting policy, not a current price quote.
The per-repository ledger has the retained 75 USD peak-equivalent conservative ceiling; choose a
small run first. Separate repositories have separate ledgers, not a shared cap.


```bash
docker compose up -d --wait
# API inference (billable):
uv run caseflow demo --family retry --arm W1 --out runtime/demo-1
# Real services, deterministic fault witnesses, no model calls:
uv run caseflow faults --out runtime/faults-1
```

See [running and reproduction](docs/RUNNING.md), [results and limits](docs/RESULTS.md),
[architecture](docs/ARCHITECTURE.md), and [source attribution](THIRD_PARTY.md).
For a Chinese overview, see [中文说明](README.zh-CN.md).

## What is in the repository

- `src/caseflow_agent/`: independently installable project code and project-specific CLI.
- `tests/`: offline domain and retained regression checks.
- `results/`: measured per-trial exports, protocols, summaries and source hashes.
- `scripts/verify_results.py`: recomputes the primary published counts without inference.
- `protocols/P4.json`: original design protocol; original runs lock later amendments.
- `PROVENANCE.json`: source commit, original/published file hashes and packaging changes.

This is personal portfolio engineering. Historical employer results and private
workplace material are not included. Original code has no newly assigned blanket
license in this packaging operation; vendored components retain their licenses.

First-use tiktoken may fetch public tokenizer data once; contract tests do not call inference providers.
