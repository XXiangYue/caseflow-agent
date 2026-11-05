"""Adjust dense retrieval scores from the last observed tool response only."""

from __future__ import annotations

import re


def words(text):
    return set(re.findall(r"[a-z]+", text.lower()))


def state_rank(scores, schemas, recent):
    """Keep cosine scores intact until an observed object or prerequisite changes them."""
    if not recent:
        return sorted(scores, key=lambda name: (-scores[name], name))
    last = recent[-1]
    observed = str(last.get("result", ""))
    error = last.get("error", False)
    keys = set(re.findall(r"""['"]([a-z_]+)['"]\s*:""", observed))
    # Creation returns a scalar UUID in ToolSandbox, while records expose named IDs.
    if not error and re.fullmatch(
        r"""['"]?[0-9a-f-]{36}['"]?""", observed.strip(), re.IGNORECASE
    ):
        created = last["name"].removeprefix("add_")
        keys.add(
            {"contact": "person_id", "reminder": "reminder_id"}.get(
                created, created + "_id"
            )
        )
    blocked = words(observed) if error else set()
    ranked = {}
    for name, score in scores.items():
        params = schemas[name]["parameters"].get("properties", {})
        required = set(schemas[name]["parameters"].get("required", []))
        fields = words(name)
        adjustment = 0.0
        if keys and name != last["name"]:
            adjustment += min(0.09, 0.045 * len(keys & required))
            adjustment += min(0.03, 0.01 * len((keys - required) & set(params)))
        if error and name.startswith(("set_", "get_")):
            names = fields - {"set", "get", "status", "mode", "service"}
            if names and names <= blocked:
                adjustment += 0.20 if name.startswith("set_") else 0.07
        if name == last["name"] and not error and name.startswith(("add_", "send_")):
            adjustment -= 0.18
        if name == last["name"] and error:
            adjustment -= 0.10
        ranked[name] = score + adjustment
    return sorted(ranked, key=lambda name: (-ranked[name], name))


def native_candidates(scores, previous):
    """Score the MCP registry after an *observed* response. Return an exposed top five."""
    import math

    from .caseflow_mcp import TOOLS

    unknown = set(scores) - TOOLS.keys()
    if unknown:
        raise ValueError(f"Unknown CaseFlow tool names: {sorted(unknown)}")
    if not scores or any(
        type(v) not in (int, float) or not math.isfinite(v) for v in scores.values()
    ):
        raise ValueError("Expected finite dense similarity scores for available tools")
    schemas = {name: {"parameters": TOOLS[name][1]} for name in scores}
    active = dict(scores)
    recent = []
    if previous is not None:
        if previous.get("name") not in TOOLS or not isinstance(
            previous.get("result"), dict
        ):
            raise ValueError("Expected a named MCP response with a structured result")
        recent = [previous]
        result = previous["result"]
        followups = set()
        if result.get("approval_required") is True:
            followups.add("approvals.request")
        if result.get("decision") == "approved":
            followups.update(("operations.begin", "workflow.apply"))
        if result.get("decision") == "rejected":
            for name in {
                "workflow.apply",
                "operations.begin",
                "knowledge.apply_operation",
                "tickets.apply_operation",
            } & active.keys():
                active[name] -= 0.3
        receipt = result.get("receipt") or {}
        if result.get("ready") is False or (
            isinstance(receipt, dict) and receipt.get("state") == "index_pending"
        ):
            followups.add("knowledge.index_status")
        if result.get("ready") is True:
            followups.add("tickets.apply_operation")
        for name in followups & active.keys():
            active[name] += 0.20
    return state_rank(active, schemas, recent)[:5]
