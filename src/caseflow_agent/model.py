from __future__ import annotations

import json
import os
from pathlib import Path
import time
import httpx
import tiktoken

from .common import Budget, ROOT, append_jsonl, digest, utc


def estimate_tokens(text: str) -> int:
    """Declared o200k estimator; API-reported usage remains authoritative."""
    return len(tiktoken.get_encoding("o200k_base").encode(text, disallowed_special=()))


class Model:
    def __init__(self, *, model=None, ledger=None, log=None, limit_usd=75):
        self.key = os.environ.get("OUTCOMES_API_KEY", "")
        if not self.key:
            raise RuntimeError("OUTCOMES_API_KEY is required for real inference")
        self.name = model or os.environ.get("OUTCOMES_MODEL", "deepseek-flash")
        self.prices = {
            "deepseek-flash": (0.006, 0.3, 1.2),
            "deepseek-v4-pro": (0.044, 1.32, 3.96),
        }[self.name]
        self.base = os.environ.get(
            "OUTCOMES_API_BASE", "https://api.deepseek.com/v1"
        ).rstrip("/")
        self.budget = Budget(ledger or ROOT / "runtime/api_budget.sqlite", limit_usd)
        self.log = log or ROOT / "evidence/api_calls.jsonl"

    def chat(
        self,
        messages,
        *,
        tools=None,
        max_tokens=2048,
        json_mode=False,
        temperature=0,
        label="",
        timeout=120,
        deadline=None,
    ):
        payload = {
            "model": self.name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "thinking": {"type": "disabled"},
        }
        if tools:
            payload["tools"] = tools
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        estimated = estimate_tokens(json.dumps(payload, ensure_ascii=False))
        # Reserve against peak rates and conservative extra prompt tokens.
        hit_price, input_price, output_price = self.prices
        reserved = (
            (len(json.dumps(payload, ensure_ascii=False).encode()) + 1024) * input_price
            + max_tokens * output_price
        ) / 1_000_000
        started = time.monotonic()
        total_cost_bound = 0
        for attempt in range(3):
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Model caller deadline reached")
            reservation = self.budget.reserve(
                reserved, label=label, request_sha256=digest(payload)
            )
            try:
                remaining = (
                    min(timeout, max(0.1, deadline - time.monotonic()))
                    if deadline is not None
                    else timeout
                )
                with httpx.Client(timeout=remaining, trust_env=False) as client:
                    response = client.post(
                        self.base + "/chat/completions",
                        headers={"Authorization": "Bearer " + self.key},
                        json=payload,
                    )
                if response.status_code in (429, 500, 502, 503) and attempt < 2:
                    self.budget.settle(
                        reservation,
                        {},
                        0 if response.status_code == 429 else reserved,
                        unknown_billing=response.status_code != 429,
                    )
                    total_cost_bound += 0 if response.status_code == 429 else reserved
                    append_jsonl(
                        self.log,
                        {
                            "at": utc(),
                            "label": label,
                            "status": "http_retry",
                            "http_status": response.status_code,
                            "attempt": attempt + 1,
                            "request_sha256": digest(payload),
                        },
                    )
                    time.sleep(2**attempt)
                    continue
                response.raise_for_status()
                body = response.json()
                if (
                    not isinstance(body.get("choices"), list)
                    or not body["choices"]
                    or not isinstance(body["choices"][0].get("message"), dict)
                ):
                    raise ValueError("Malformed model response")
                usage = body.get("usage") or {}
                usage_complete = isinstance(usage, dict) and all(
                    isinstance(usage.get(k), int) and usage[k] >= 0
                    for k in ("prompt_tokens", "completion_tokens")
                )
                if not isinstance(usage, dict):
                    usage = {}
                prompt = usage.get("prompt_tokens", 0)
                hits = usage.get(
                    "prompt_cache_hit_tokens",
                    usage.get("prompt_tokens_details", {}).get("cached_tokens", 0),
                )
                output = usage.get("completion_tokens", 0)
                # Peak-price equivalent, intentionally conservative; not actual billing.
                cost = (
                    hits * hit_price
                    + (prompt - hits) * input_price
                    + output * output_price
                ) / 1_000_000
                if not usage_complete:
                    cost = reserved
                self.budget.settle(
                    reservation, usage, cost, unknown_billing=not usage_complete
                )
                total_cost_bound += cost
                result = {
                    "message": body["choices"][0]["message"],
                    "finish_reason": body["choices"][0].get("finish_reason"),
                    "model": body.get("model"),
                    "fingerprint": body.get("system_fingerprint"),
                    "usage": usage,
                    "usage_complete": usage_complete,
                    "cost_usd_peak_equivalent": cost if usage_complete else None,
                    "cost_upper_bound_usd": total_cost_bound,
                    "reservation_id": reservation,
                    "ms": round((time.monotonic() - started) * 1000, 2),
                    "request_id": body.get("id"),
                    "attempts": attempt + 1,
                }
                append_jsonl(
                    self.log,
                    {
                        "at": utc(),
                        "label": label,
                        "status": "ok",
                        "request_sha256": digest(payload),
                        **result,
                    },
                )
                return result
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                if attempt < 2 and not isinstance(exc, httpx.HTTPStatusError):
                    self.budget.settle(reservation, {}, reserved, unknown_billing=True)
                    total_cost_bound += reserved
                    append_jsonl(
                        self.log,
                        {
                            "at": utc(),
                            "label": label,
                            "status": "transport_retry",
                            "error_type": type(exc).__name__,
                            "attempt": attempt + 1,
                        },
                    )
                    time.sleep(2**attempt)
                    continue
                # Transport failure might have been billed: retain the reservation as
                # conservative cost instead of silently treating it as free.
                self.budget.settle(reservation, {}, reserved, unknown_billing=True)
                append_jsonl(
                    self.log,
                    {
                        "at": utc(),
                        "label": label,
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "http_status": getattr(
                            getattr(exc, "response", None), "status_code", None
                        ),
                        "unknown_billing_reserve": reserved,
                    },
                )
                raise RuntimeError(
                    "Model call failed; see sanitized API ledger"
                ) from None

    def json(self, system, user, **kwargs):
        result = self.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            json_mode=True,
            **kwargs,
        )
        content = result["message"].get("content") or ""
        try:
            value = json.loads(content)
        except json.JSONDecodeError:
            raise ValueError("Model did not return parseable JSON") from None
        return value, result
