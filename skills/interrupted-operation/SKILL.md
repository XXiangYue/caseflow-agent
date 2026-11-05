---
name: interrupted-operation
description: Reconcile an interrupted or response-lost operation without duplicating already committed business changes.
---

An error or lost response does not establish that a write failed. Keep the original
proposal, approval and operation identifiers. Inspect operation/receipt state before
repeating work. Never create a fresh proposal or alter the content simply to avoid
an ambiguous response. Completed service receipts are the authority for completed
effects; a caller's missing response is not permission to duplicate them.

If knowledge was committed but ticket update remains, wait for the current intended
knowledge version to become searchable, then continue the remaining approved steps.
If indexing is pending, report pending and retry the same operation. If a newer
knowledge version supersedes it, stop with conflict. Final verification must read
both services and confirm the ticket link and current searchable version.

Authorization is checked before dispatching each new business action. Expired,
rejected or revoked approval prevents further writes. An already authorized and
committed knowledge revision remains recorded; do not claim distributed rollback
or silently continue to close the ticket. Report partial progress and request a new
authorized plan for remaining work when required. A repeated receipt lookup is
different from dispatching a new side effect.

Version conflicts require re-reading state and a fresh proposal, not a forced
overwrite. Changed payload under an existing operation ID is an error. Multiple
resume callers must still produce at most one service version/receipt for the same
authorized payload. This guarantee covers formal service commits, not exactly-once
execution of arbitrary commands or model calls.

After recovery, verify real state and report completed, blocked, conflict or pending.
Include failure/retry work when reporting total cost and latency. Do not hide failed
attempts or turn a controlled fault exercise into a general reliability guarantee.

