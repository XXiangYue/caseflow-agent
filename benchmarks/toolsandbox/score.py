"""Score paired raw runs without loading the actor, retriever, or tool simulator."""

import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path


def duplicate_writes(row):
    successful = [
        (e["tool"], e.get("arguments_sha256"))
        for e in row["events"]
        if e.get("action") == "tool"
        and not e["tool_error"]
        and e["tool"].startswith(("add_", "send_"))
    ]
    return len(successful) - len(set(successful))


def passed_state(row):
    adjudicated = [s for scores in row["terminal_constraints"].values() for s in scores]
    return (
        bool(adjudicated)
        and all(s >= 1 - 1e-7 for s in adjudicated)
        and not row["off_target_namespaces"]
        and row["minefield"] == 0
        and duplicate_writes(row) == 0
    )


def summarize(rows):
    return {
        "trials": len(rows),
        "schema_tokens_per_attempted_task_o200k": (
            sum(e["schema_tokens_o200k"] for r in rows for e in r["events"]) / len(rows)
        )
        if rows
        else None,
        "strict_official_pass": sum(r["official_similarity"] >= 1 - 1e-7 for r in rows),
        "official_mean_similarity": math.fsum(r["official_similarity"] for r in rows)
        / len(rows)
        if rows
        else None,
        "terminal_state_tasks": sum(bool(r["terminal_constraints"]) for r in rows),
        "terminal_state_pass": sum(passed_state(r) for r in rows),
        "off_target_final_namespace_change_tasks": sum(
            bool(r["off_target_namespaces"]) for r in rows
        ),
        "duplicate_successful_add_or_send": sum(duplicate_writes(r) for r in rows),
        "tasks_with_duplicate_successful_add_or_send": sum(
            duplicate_writes(r) > 0 for r in rows
        ),
        "official_minefield_triggered": sum(r["minefield"] > 0 for r in rows),
        "actor_errors": sum(r["status"] == "actor_error" for r in rows),
        "turn_limits": sum(r["status"] == "turn_limit" for r in rows),
        "schema_tokens_o200k": sum(
            e["schema_tokens_o200k"] for r in rows for e in r["events"]
        ),
        "actor_turns": sum(len(r["events"]) for r in rows),
        "provider_input_tokens": sum(r["usage"]["input_tokens"] for r in rows),
        "provider_output_tokens": sum(r["usage"]["output_tokens"] for r in rows),
        "unknown_billing_calls": sum(r["usage"]["unknown_usage_calls"] for r in rows),
        "estimated_peak_cost_upper_usd": math.fsum(
            r["usage"]["cost_upper_bound_usd"] for r in rows
        ),
    }


def paired(rows):
    by = {}
    for r in rows:
        n = r["task"]
        if r["arm"] in by.setdefault(n, {}):
            raise ValueError("Duplicate task and arm")
        by[n][r["arm"]] = r
    pairs = [
        (d["dense"], d["state"]) for d in by.values() if set(d) == {"dense", "state"}
    ]
    state = [
        (a, b)
        for a, b in pairs
        if a["terminal_constraints"] and b["terminal_constraints"]
    ]
    groups = defaultdict(list)
    for a, b in state:
        groups[a["family"]].append(int(passed_state(b)) - int(passed_state(a)))
    names = sorted(groups)
    rng = random.Random(20261105)
    samples = []
    if names:
        for _ in range(5000):
            draws = [v for k in rng.choices(names, k=len(names)) for v in groups[k]]
            samples.append(sum(draws) / len(draws))
    samples.sort()
    return {
        "paired_tasks": len(pairs),
        "terminal_state_pairs": len(state),
        "families_with_terminal_state": len(groups),
        "gained_terminal_state_tasks": [
            a["task"] for a, b in state if not passed_state(a) and passed_state(b)
        ],
        "lost_terminal_state_tasks": [
            a["task"] for a, b in state if passed_state(a) and not passed_state(b)
        ],
        "paired_terminal_pass_difference_95pct_family_bootstrap": [
            samples[125],
            samples[4874],
        ]
        if samples
        else None,
        "arms": {
            arm: summarize([p[i] for p in pairs])
            for i, arm in enumerate(("dense", "state"))
        },
    }


def report(folder):
    manifest = json.loads((folder / "manifest.json").read_text())
    archive = folder / "trials.jsonl"
    if archive.exists():
        rows = [json.loads(line) for line in archive.read_text().splitlines() if line]
    else:
        rows = [
            json.loads(p.read_text())
            for p in sorted(folder.glob("*.json"))
            if p.name.endswith((".dense.json", ".state.json"))
        ]
    lookup = {
        r["task"]: (r["split"], r["family"])
        for r in manifest
        if not r["excluded_remote_task"]
    }
    for row in rows:
        if (row["split"], row["family"]) != lookup.get(row["task"]) or row[
            "arm"
        ] not in {"dense", "state"}:
            raise ValueError("Task outside the fixed groups")
        for event in row["events"]:
            shown = event["shown"]
            if not 1 <= len(shown) <= 5 or len(shown) != len(set(shown)):
                raise ValueError("Candidate budget violated")
            if event.get("action") == "tool" and event["tool"] not in shown:
                raise ValueError("Agent executed an unexposed tool")
        for ns, w in row.get("terminal_witnesses", {}).items():
            if (w["before_sha256"] != w["after_sha256"]) != (
                ns in row["changed_namespaces"]
            ):
                raise ValueError("Database change witness mismatch")
    if len({r["backend"] for r in rows}) > 1:
        raise ValueError("Mixed retrievers")
    out = {}
    for split in ["dev", "test"]:
        eligible = [
            r["task"]
            for r in manifest
            if r["split"] == split and not r["excluded_remote_task"]
        ]
        part = [r for r in rows if r["split"] == split]
        out[split] = dict(
            planned=len(eligible),
            **paired(part),
            missing={
                arm: [
                    n
                    for n in eligible
                    if (n, arm) not in [(r["task"], r["arm"]) for r in part]
                ]
                for arm in ("dense", "state")
            },
        )
    return out


if __name__ == "__main__":
    cli = argparse.ArgumentParser()
    cli.add_argument("folder", type=Path)
    cli.add_argument(
        "--verify",
        action="store_true",
        help="Compare a saved summary against the complete public per-task receipts",
    )
    args = cli.parse_args()
    actual = report(args.folder)
    if args.verify:
        expected = json.loads((args.folder / "summary.json").read_text())
        if actual != expected:
            raise SystemExit("Stored summary differs from the trial-level replay")
        print(
            f"Verified {sum(v['paired_tasks'] for v in actual.values())} paired tasks"
        )
    else:
        print(json.dumps(actual, indent=2))
