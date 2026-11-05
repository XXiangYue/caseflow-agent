import json
import httpx
import pytest

from caseflow_agent.common import Budget, db
from caseflow_agent.model import Model


def test_pending_reserve_is_not_free(tmp_path):
    b = Budget(tmp_path / "budget.sqlite", 1)
    b.reserve(0.75, label="trial")
    assert b.summary()["cost_upper_bound_usd"] == 0.75
    assert b.summary()["pending_reserved_usd"] == 0.75
    assert b.trial_usage("trial")["cost_upper_bound_usd"] == 0.75


@pytest.mark.parametrize("mode", ["retry", "missing_usage", "empty_choices"])
def test_provider_failure_accounting(monkeypatch, tmp_path, mode):
    monkeypatch.setenv("OUTCOMES_API_KEY", "unit-test-placeholder")
    monkeypatch.setattr("caseflow_agent.model.time.sleep", lambda _: None)
    calls = []

    def fake_post(self, url, **kwargs):
        calls.append(1)
        status = 500 if mode == "retry" and len(calls) == 1 else 200
        body = {
            "model": "fixture",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
        }
        if mode != "missing_usage":
            body["usage"] = {"prompt_tokens": 10, "completion_tokens": 2}
        if mode == "empty_choices":
            body["choices"] = []
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    m = Model(ledger=tmp_path / "budget.sqlite", log=tmp_path / "calls.jsonl")
    if mode == "empty_choices":
        with pytest.raises(RuntimeError):
            m.chat([{"role": "user", "content": "x"}], label="trial")
        assert m.budget.summary()["charge_unknown_upper_bound_usd"] > 0
    else:
        r = m.chat([{"role": "user", "content": "x"}], label="trial")
        assert (
            r["cost_upper_bound_usd"]
            == m.budget.trial_usage("trial")["cost_upper_bound_usd"]
        )
        if mode == "missing_usage":
            assert not r["usage_complete"] and r["cost_usd_peak_equivalent"] is None
    assert "unit-test-placeholder" not in (tmp_path / "calls.jsonl").read_text()
