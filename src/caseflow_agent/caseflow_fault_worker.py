"""Subprocess witness: exit after a real knowledge commit, before ticket write."""

import json
import os
from pathlib import Path
from .caseflow import Gateway
from .common import ROOT

c = json.loads(os.environ["CASEFLOW_WITNESS"])
g = Gateway(
    Path(c["ledger"]),
    scope=c["scope"],
    subject="synthetic-operator",
    knowledge_url=os.environ["CASEFLOW_KNOWLEDGE_URL"],
    tickets_url=os.environ["CASEFLOW_TICKETS_URL"],
    internal_token=os.environ["CASEFLOW_INTERNAL_TOKEN"],
    user_policy=c["policy"],
    skills_path=ROOT / "skills",
)
r = g.call(
    "knowledge.apply_operation",
    {"operation_id": c["operation_id"], "approval_id": c["approval_id"]},
)
print(
    json.dumps(
        {
            "knowledge_step_ok": r["ok"],
            "exit_point": "after_committed_knowledge_before_ticket",
        }
    ),
    flush=True,
)
os._exit(73)
