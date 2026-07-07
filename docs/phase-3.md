# Phase 3 — Action Gateway & Agent Registry

Built 2026-07-07.

## What exists now

- **Action Gateway** (`src/gateway/service.py`) — the single door to the
  outside world. Agents `submit()` sensitive actions; they queue as `pending`.
  Approval runs the action's registered executor exactly once; rejection
  buries it. Decided requests can never be re-decided (double-send is
  structurally impossible — verified live with a 409).
- **Append-only audit log** (`AuditEvent`) — every submit/approve/reject/
  execute/fail is recorded; there is deliberately no update/delete code path
  for this table anywhere.
- **Executor registry** — `@register_executor("email.send")` is how future
  integrations plug in. Executors are reachable ONLY from the gateway's
  approve path; there is no other route from agent code to an executor.
- **Agent registry** (`src/agents/`) — each agent declares its name,
  description, and `allowed_actions` (its permission scope). The `demo` agent
  exercises the pipeline with a harmless `demo.echo` action — no LLM or API
  key needed.
- **Approvals UI** (`/approvals`) — pending cards show the agent, the action,
  and the exact payload; Approve/Reject buttons; history with expandable
  audit trails; a demo-request generator for trying the flow today.
- **Tests** (20 total, 7 new) pinning the safety guarantees, not
  implementation details.

## Why this design is the security heart

A future agent — even one manipulated by prompt injection in an email or job
posting it read — can only ever *enqueue a request you will see*. The
dangerous capability (the executor) is registered in one dictionary, called
from one place, after one human click. Security reviews of every later phase
reduce to: "does anything bypass the gateway?" — grep for `_executors`.

## Notes

- **Auth**: still deferred — lands in Phase 4 together with the first real
  external integration (Gmail OAuth), i.e. before ARIA can touch anything
  outside localhost.
- **LangGraph**: deliberately not added yet. Phase 3 needed the safety spine,
  not a workflow engine; LangGraph arrives in Phase 4 with the first
  LLM-powered agent, so the dependency lands next to its first real use.
- **Circular import gotcha**: `src/models.py` imports `EMBEDDING_DIM` from the
  memory package, so `src/memory/__init__.py` must import its own submodules
  lazily (inside functions). Python circular imports usually surface as
  `partially initialized module` errors.

## How to verify

1. Open http://localhost:3000/approvals.
2. Create a demo request → it appears under "Awaiting your decision" with its payload.
3. Approve it → status `EXECUTED`, with the result; audit trail shows
   submitted → approved → executed with timestamps.
4. Create another and reject it → `REJECTED`, result empty (nothing ran).
5. `pytest` in `apps/api` → 20 passed.
