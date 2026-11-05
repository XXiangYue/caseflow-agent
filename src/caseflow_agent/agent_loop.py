"""Model-selected tool execution with durable message checkpoints and budgets."""

from __future__ import annotations
import asyncio
import json
from pathlib import Path
import time

from .common import digest, write_json
from .model import Model


async def run_tools(
    model: Model,
    *,
    messages,
    tools,
    call_tool,
    state_path: Path,
    label,
    max_steps=40,
    input_cap=60000,
    output_cap=8000,
    wall_cap=240,
    persistent=True,
):
    started = time.monotonic()
    if persistent and state_path.exists():
        state = json.loads(state_path.read_text())
        if state.get("terminal"):
            return state
    else:
        state = {
            "messages": messages,
            "steps": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_upper_bound_usd": 0,
            "events": [],
            "terminal": False,
            "started_epoch": time.time(),
        }
    deadline = time.monotonic() + max(
        0, state.get("started_epoch", time.time()) + wall_cap - time.time()
    )
    for key, value in model.budget.trial_usage(label).items():
        state[key] = max(state.get(key, 0), value)

    def checkpoint():
        if persistent:
            write_json(state_path, state)

    aliases = {t["function"]["name"]: t for t in tools}
    checkpoint()
    try:
        while state["steps"] < max_steps:
            if time.monotonic() > deadline:
                state["status"] = "timeout"
                break
            if (
                state["input_tokens"] >= input_cap
                or state["output_tokens"] >= output_cap
            ):
                state["status"] = "budget_exceeded"
                break
            # An interrupted tool call is reconciled with the same original args.
            last_assistant = next(
                (m for m in reversed(state["messages"]) if m["role"] == "assistant"),
                None,
            )
            answered = {
                m.get("tool_call_id") for m in state["messages"] if m["role"] == "tool"
            }
            pending = [
                x
                for x in (last_assistant or {}).get("tool_calls", [])
                if x["id"] not in answered
            ]
            if not pending:
                reply = await asyncio.to_thread(
                    model.chat,
                    state["messages"],
                    tools=tools,
                    max_tokens=min(2048, output_cap - state["output_tokens"]),
                    label=label,
                    deadline=deadline,
                )
                state["input_tokens"] += reply["usage"].get("prompt_tokens", 0)
                state["output_tokens"] += reply["usage"].get("completion_tokens", 0)
                state["cost_upper_bound_usd"] += reply["cost_upper_bound_usd"]
                state["model"] = reply["model"]
                state["fingerprint"] = reply["fingerprint"]
                if not reply["usage_complete"]:
                    raise RuntimeError(
                        "Cannot certify per-trial token budget without usage"
                    )
                if (
                    state["input_tokens"] > input_cap
                    or state["output_tokens"] > output_cap
                ):
                    state.update(status="budget_exceeded", terminal=True)
                    break
                m = reply["message"]
                assistant = {"role": "assistant", "content": m.get("content")}
                if m.get("tool_calls"):
                    assistant["tool_calls"] = m["tool_calls"]
                state["messages"].append(assistant)
                checkpoint()
                pending = m.get("tool_calls", [])
                if not pending:
                    state.update(
                        status="completed", final=m.get("content"), terminal=True
                    )
                    break
            for tool in pending:
                if time.monotonic() > deadline:
                    raise TimeoutError("Tool dispatch deadline reached")
                if state["steps"] >= max_steps:
                    break
                name = tool["function"]["name"]
                try:
                    args = json.loads(tool["function"]["arguments"])
                    if name not in aliases:
                        raise ValueError("tool_not_exposed")
                    result = await call_tool(name, args)
                except (ValueError, KeyError, TypeError) as exc:
                    result = {"ok": False, "error": type(exc).__name__}
                state["steps"] += 1
                state["events"].append(
                    {
                        "tool": name,
                        "arguments": args if "args" in locals() else {},
                        "result": result,
                    }
                )
                state["messages"].append(
                    {
                        "role": "tool",
                        "tool_call_id": tool["id"],
                        "content": json.dumps(result, ensure_ascii=False)[:16000],
                    }
                )
                checkpoint()
        else:
            state["status"] = "tool_budget_exceeded"
    except Exception as exc:
        state.update(status="error", error_type=type(exc).__name__)
    state["active_ms"] = state.get("active_ms", 0) + (time.monotonic() - started) * 1000
    state["terminal"] = True
    checkpoint()
    return state
