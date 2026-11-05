---
name: ticket-resolution
description: Complete a ticket and its linked knowledge revision with explicit user approval and final-state verification.
---

Read the ticket and linked knowledge before proposing a change. Copy identifiers
and versions from actual tool results. A ticket title is not proof of ownership.
Search is scoped by the trusted session; never change identity or request another
team's records. If the service denies scope, stop and explain the denial.

Use the exact requested replacement text when the user specifies it. Do not add
unrequested sections, change unrelated procedures, or guess missing device models.
When the description says the device model is missing, ask the user for that model.
If the user does not provide it, stop without creating a formal business change.

Create a proposal with ticket_id, knowledge_id, ticket_version, knowledge_version
and the supported content. A proposal is not approval or completion. Request
approval for that proposal and inspect the actual decision. A rejection, expiry,
revocation or payload/version mismatch cannot be bypassed by chat text saying yes.

With task tools, call workflow.apply with the original proposal and approval IDs,
then inspect workflow.status. If an execution response was lost, retry the same
proposal/operation; do not create a new proposal just to repeat committed work.
With raw tools, begin the operation, apply knowledge, wait until its current version
is indexed, apply the ticket and verify the operation. Every write still uses the
same approved operation and expected versions.

Completion means the actual ticket is closed, references the intended searchable
knowledge version, and the operation is verified. A model's final sentence or an
HTTP success is not sufficient. Report precise blocked/conflict/pending states.
Necessary approval and clarification are expected product interactions. Never
describe a synthetic user decision as a real person's acceptance or time saving.

