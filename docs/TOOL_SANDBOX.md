# Retrieving the next tool after a state change

CaseFlow's MCP ticket workflow and this cross-domain experiment address a common question. After an agent learns that a prerequisite failed or an object was created, will it find the next tool within a five-schema budget? The public benchmark uses simulated phone tasks such as changing settings or updating reminders. The existing approval and knowledge-index cases have separate results in [RESULTS.md](RESULTS.md).

## Held-out results

The same actor ran once per task and strategy. Each cell lists dense retrieval first, then retrieval with the state adjustment.

| Measure | Original Tool-Embed-4B (BF16) | Auxiliary BGE-M3 |
|---|---:|---:|
| Terminal-state pass / 24 | 16 → 16 | 13 → 14 |
| Perfect official trajectory / 34 | 1 → 2 | 2 → 3 |
| Mean official trajectory similarity / 34 | 0.633 → 0.674 | 0.682 → 0.689 |
| Tool-schema tokens / 34 attempted tasks (sum) | 145,454 → 105,926 | 120,387 → 139,176 |
| Tool-schema tokens per attempted task | 4,278 → 3,115 | 3,541 → 4,093 |
| Actor turns / 34 attempted tasks (sum) | 224 → 170 | 239 → 256 |
| Total provider input tokens | 249,250 → 165,826 | 206,155 → 226,589 |
| Total provider output tokens | 5,810 → 4,131 | 5,268 → 5,485 |
| Runs with off-target terminal table changes | 0 → 0 | 0 → 0 |
| Duplicate successful adds/sends | 47 → 1 | 0 → 0 |
| Tasks with a duplicate successful add/send | 3 → 1 | 0 → 0 |
| Official minefield triggers | 0 → 0 | 0 → 0 |
| Actor errors | 0 → 1 | 0 → 1 |
| Turn-limit exits | 2 → 1 | 3 → 3 |

**tool-embed-bf16.** 0 gained and 0 lost among the 24 cases across 11 state-bearing task families. All observed pairs agree, so the family bootstrap has zero width and supplies no useful population equivalence bound. The estimated peak-rate actor charges on all 34 attempts were USD 0.0664 and USD 0.0424. [Task-level receipts](../results/tool_sandbox_20261105/tool-embed-bf16/trials.jsonl) · [offline summary](../results/tool_sandbox_20261105/tool-embed-bf16/summary.json)

**bge-m3.** 2 gained and 1 lost among the 24 cases across 11 state-bearing task families. The 95% paired family-bootstrap interval for the change is [-9.1, +18.2] percentage points. The estimated peak-rate actor charges on all 34 attempts were USD 0.0615 and USD 0.0597. [Task-level receipts](../results/tool_sandbox_20261105/bge-m3/trials.jsonl) · [offline summary](../results/tool_sandbox_20261105/bge-m3/summary.json)

On the original checkpoint both arms passed exactly the same 16 state-changing tasks. The predeclared target of completing additional tasks was missed. The three requests with repeat writes in the baseline all asked for reminders with relative dates. All three still failed the terminal predicate after reranking. Across those three requests the baseline added 53 rows and the state arm added five; among the 34 attempts, the strict duplicate counter fell from 47 to one. A post-hoc check excluding these three tasks leaves 105,806 → 93,198 schema tokens on the other 31 attempts. The supplemental BGE-M3 experiment had zero identical repeat writes in either arm and its schema usage rose.


## What each comparison measures

The [original Tool-Embed-4B checkpoint](https://huggingface.co/Lux1997/Tool-Embed-4B/tree/0ff726361463e980dbd3aca1904daf304b0ea994) supplies dense scores. CaseFlow uses its normalized last-token representation in BF16 with float32 normalization. Both arms serialize the same full function schemas and use the same English query instruction. This measures transfer to ToolSandbox. The [Tool-REX experiments](https://github.com/EIT-NLP/Tool-REX) have their own document corpus and retrieval metrics.

Every step gives the actor at most five schemas. It can execute any of the five, request another search, or give a final answer. Both arms see the original request, prior actions, and visible execution responses. Both can change the search query. The state arm adjusts candidate scores when the last execution produced an ID, a field matching a required parameter, or an error naming a missing setting. It also discounts an immediately repeated creation or send. Neither ranker sees reference tools, milestones, user-simulator instructions, private database fields or validation results.

The separate BGE-M3 comparison uses the same paired execution and scoring path. Its frozen test results are under [bge-m3](../results/tool_sandbox_20261105/bge-m3/summary.json).

## Tasks and scoring

The [pinned upstream ToolSandbox](https://github.com/apple/ToolSandbox/tree/c8571d7854316d2e1c5f288e59fe1e34e53f6dd1) contains 54 single-user-turn, multi-tool scenarios. Fourteen require RapidAPI to satisfy the user request. The retained 40 can be completed locally. All 40 use the tool membership of the upstream all-tools distractor variant, sorted by name before scoring. Distractor calls that require RapidAPI can return the original unavailable-service error. The actor gets the public initial user request only, with no simulated follow-up conversation. The local calendar is fixed at 2024-03-20 12:00 UTC for matching fixtures and tool responses. UTC also makes absolute timestamps reproducible.

The manifest lists all 54 task IDs. Variants ending in alt or implicit are grouped with their base family, and wifi-off or ambiguous variants stay with the related task. SHA256 of the family name modulo five determines the split, with remainder zero assigned to development. This yields six development and 34 held-out tasks. Before inspecting held-out outcomes, the shared actor instructions and state rules were finalized on the six development scenarios using a separate BGE-M3 pilot.

* **Primary terminal-state measure.** The 34 test cases contain 24 whose upstream milestones name a physical business table. CaseFlow applies the upstream snapshot, addition, removal or update predicate to the *last* physical table, with the initial table as the reference for changes. All target predicates must score one, the upstream minefield score must be zero, and the other tables must finish unchanged. A duplicate successful add/send with identical arguments prevents a pass. This accepts a valid final state reached by a different route. Read-only tasks have no physical-state denominator. The raw predicates are in each trial.
* **Full upstream score.** We also run the original milestone/minefield scorer over every trajectory. It evaluates tool traces and, where applicable, response similarity. Reports include the graded mean and the number of trials with a perfect score to 1e-7. Perfect upstream score is a stricter, separate outcome.
* **Side effects.** Receipts report terminal changes to non-target tables, repeated successful adds/sends and official minefield triggers. These indicators cover specific side effects. Semantic mistakes within a target table can depress the target predicate without a separate unsafe-action classification.
* **Cost.** Each arm uses the same DeepSeek Flash service alias, temperature zero, 20 actor turns and 800 maximum output tokens per call. The schema count uses o200k_base on the compact JSON snippets displayed; the provider supplies separate total input and output token counts. Both include unsuccessful attempts where available. The SQLite ledger applies a USD 10 ceiling per retriever arm. Estimated peak-rate cost and unknown-billing calls are separate from the actual invoice. Embedding work runs on the fixed model; its compute is excluded from actor-token totals.
* **Uncertainty.** Report rescued and lost paths by task ID. The paired 95% percentile interval resamples entire task families, so an alternate wording stays with its parent. The split contains eleven state-bearing families. We ran each actor once per task and arm. Where every observed pair agrees, a sample bootstrap can collapse to zero width; that result cannot establish equivalence on new tasks. The actor service alias may subsequently change.

## Recompute or rerun

Recompute a published arm pair on Python 3.9 or later without an API key.

```bash
python3 benchmarks/toolsandbox/score.py --verify results/tool_sandbox_20261105/tool-embed-bf16
python3 benchmarks/toolsandbox/score.py --verify results/tool_sandbox_20261105/bge-m3
```

For a fresh run, use an isolated benchmark environment. The historical MCP project still uses its own Python 3.12 lock. The transformer encoder and the tool simulator may run in separate environments.

```bash
git clone https://github.com/apple/ToolSandbox /tmp/caseflow-toolsandbox
git -C /tmp/caseflow-toolsandbox checkout c8571d7854316d2e1c5f288e59fe1e34e53f6dd1
uv venv --python 3.11 .bench-env
uv pip install --python .bench-env/bin/python -r benchmarks/toolsandbox/requirements.txt
uv venv --python 3.11 .encoder-env
uv pip install --python .encoder-env/bin/python torch==2.9.1 transformers==4.57.3 huggingface_hub==0.36.0
.encoder-env/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('Lux1997/Tool-Embed-4B',revision='0ff726361463e980dbd3aca1904daf304b0ea994',local_dir='runtime/tool-embed-4b')"
.encoder-env/bin/python benchmarks/toolsandbox/embeddings.py --backend tool-embed-bf16 --weights runtime/tool-embed-4b --cache runtime/embed-cache
```

In a second terminal, export the key using your normal secret manager. The actor requires OUTCOMES_API_KEY; OUTCOMES_API_BASE defaults to the service's OpenAI-compatible v1 endpoint. Keep RAPID_API_KEY unset for this offline experiment.

```bash
export PYTHONPATH="$PWD/src:/tmp/caseflow-toolsandbox"
export POLARS_MAX_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
.bench-env/bin/python benchmarks/toolsandbox/run.py --backend tool-embed-bf16 --out runtime/tool-sandbox --manifest-only
.bench-env/bin/python benchmarks/toolsandbox/run.py --backend tool-embed-bf16 --out runtime/tool-sandbox --split all --workers 3
.bench-env/bin/python benchmarks/toolsandbox/score.py runtime/tool-sandbox
```

A localhost embedding server also supports a distinct BGE-M3/Ollama run with `--backend bge-m3-ollama`. Give each model a separate output folder. Existing complete receipts are skipped. Fresh runs keep provider responses privately in the runtime directory. The public numerical records include candidate names, action statuses, argument hashes, table digests, raw evaluator outputs, and usage. The [replay tool](../benchmarks/toolsandbox/replay.py) can check private actor decisions again, including the mapping of newly generated object IDs.

For a local MCP integration example, pass dense scores for *available* business tools and the last observed MCP receipt to `uv run caseflow rank-tools benchmarks/toolsandbox/example_native.json`. The example starts with the ticket-write tool scoring highest and a pending index receipt. The opt-in adapter returns `knowledge.index_status` first. Gateway checks continue to validate approvals, scope and version when a tool is executed. The example uses illustrative scores. The 72-ticket historical experiment used its original full catalogs.

In the original Tool-Embed-4B run, both approaches failed the final reminder predicate on `add_reminder_content_and_week_delta_and_time_alt`. Dense retrieval created 15 reminder rows, including 13 repeated calls with identical arguments; the state arm created two rows and recorded zero exact repeats. This example explains both the narrower improvement in repeated side effects and the remaining failure to create exactly the requested reminder. [Original BF16 receipts](../results/tool_sandbox_20261105/tool-embed-bf16/trials.jsonl)

In the auxiliary BGE-M3 run, the dense-only agent enabled cellular service but reached the turn limit before sending the requested message. The state-assisted run ended with both the requested message row and enabled service. Conversely, the dense-only agent updated the correct contact on `modify_contact_with_message_recency`; the other agent searched repeatedly and its actor response eventually failed. We count that failed attempt. Both examples can be located by task ID in the [receipts](../results/tool_sandbox_20261105/bge-m3/trials.jsonl).

Newly created ToolSandbox rows receive random UUIDs. Table digests compare the before and after snapshots *within* one run. The private replay maps a later successful reference when it points unambiguously to the single newly created row. Original BF16 trials preserve the measured table digests and the independently replayed table digests. In the older auxiliary files the table digests come from replays that match the originally recorded terminal predicates and changed table names. It verifies the recorded tool error status and the full upstream score before exporting a replay witness. The paired interval reflects sampled task families and one set of actor decisions, so precision is limited for small differences.

After a successful or failed tool call, the dense query in both arms combines the original request, the tool name and the first 350 characters of its result. An explicit new search from the actor replaces that query. The state arm also inspects keys and errors from the actor-visible result (up to 3,000 trailing characters). A difference can therefore reflect both structured field matching and access to a field outside the dense query's short prefix. No ablation separates these two effects.
