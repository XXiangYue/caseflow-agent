# Running CaseFlow

## Environment

Use Python 3.12 and the checked-in `uv.lock`. `uv sync --locked` installs an
editable checkout in its own virtual environment. Run from the repository root;
the source intentionally locates project assets relative to that checkout.
Linux/macOS are supported; Windows users can use WSL2. CPU runs do not require CUDA.

## Three different verification levels

1. `uv run pytest -q`: offline contracts and regression witnesses; provider fixtures
   are explicitly simulated and are not model-effectiveness evidence.
2. `uv run python scripts/verify_results.py`: recomputation from published rows
   of historical measurements; no inference or new performance claim.
3. The project commands below: fresh execution under your own environment. Use
   a new output directory. Changed models, prompts, dependencies or assets define
   a new run and need their own result label.

```bash
docker compose up -d --wait
# API inference (billable):
uv run caseflow demo --family retry --arm W1 --out runtime/demo-1
# Real services, deterministic fault witnesses, no model calls:
uv run caseflow faults --out runtime/faults-1
```


Inference requires `OUTCOMES_API_KEY` in the process environment. Supply it using
your normal secret manager; no key is required for tests or saved-result verification.
`OUTCOMES_API_BASE` and `OUTCOMES_MODEL` are optional. The evaluated model identifiers
are `deepseek-flash` and `deepseek-v4-pro`. Historical peak-equivalent prices in
`model.py` describe the original accounting policy, not a current price quote.
The per-repository ledger has the retained 75 USD peak-equivalent conservative ceiling; choose a
small run first. Separate repositories have separate ledgers, not a shared cap.


## Results and troubleshooting

`results/` is a read-only historical export. New runs go under `runtime/` or a new
chosen directory. The code refuses a conflicting frozen protocol. Do not reuse
an old terminal output directory for a changed configuration.






PostgreSQL is bound to 127.0.0.1:57543; the local fixture uses trust authentication and is for local development. If the port is occupied, inspect the listener before starting another instance. HTTP services use ephemeral loopback ports and in-memory internal credentials. The command stops its own HTTP/MCP children. Run fault witnesses separately from Agent trials because they control the task index worker. Stop only this compose project with `docker compose stop`; keep its database volume when preserving evidence.

If inference credentials are absent, an explicit configuration error is expected.
No embedded fallback response is substituted for real inference.

First-use tiktoken may fetch public tokenizer data once; contract tests do not call inference providers.

## No-inference execution smoke check

After the preparation steps above, run:

```bash
uv run python scripts/smoke_mcp.py --out runtime/mcp-smoke-1
```

This exercises the actual service or CPU execution layer; it does not create new model-effectiveness results.
