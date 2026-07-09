# ARIA Architecture

Decided 2026-07-06. Update this file whenever a decision changes — stale docs are worse than none.

## The core safety rule

Agents can **read** and **draft**. Any outward action (send a message, submit an
application, publish anything) must pass through the **Action Gateway**: it becomes
an Action Request in an approval queue, executes only after explicit human approval,
and every request + decision is written to an append-only audit log. There is no
other code path from agent to outside world.

## System overview

- **apps/web** — Next.js 15 + TypeScript + Tailwind dashboard. Talks to the API over HTTPS with JWT auth.
- **apps/api** — FastAPI (Python). Contains:
  - `core/` — config (all env-driven, single source of truth), logging, security helpers
  - `llm/` — provider abstraction; agents never call a vendor SDK directly (Phase 1)
  - `memory/` — structured memory (SQL) + semantic memory (RAG over pgvector) (Phase 2)
  - `agents/` — LangGraph agents, one folder each, registered in a central registry (Phase 3)
  - `gateway/` — the Action Gateway described above (Phase 3)
  - `integrations/` — OAuth clients for email, calendar, etc. (Phase 4+)
  - `routers/` — HTTP endpoints
- **PostgreSQL + pgvector** — one database for relational data AND vector embeddings.
- **Redis** — cache, background job queues, rate limiting.

## Key decisions and why

| Decision | Why |
|---|---|
| Python/FastAPI over NestJS | The AI ecosystem (LangGraph, embeddings, doc parsing, local models) is Python-first; FastAPI validates inputs at the boundary and auto-generates docs. |
| pgvector over a dedicated vector DB | One less service to run, secure, and pay for; ample at personal scale. |
| LLM provider abstraction | Swap Claude/OpenAI/local models by writing one adapter, not touching agents. |
| Plain async pipelines for agents (LangGraph dropped) | All agents are straight call sequences; our human-in-the-loop lives in the Action Gateway, not a framework. Revisit if an agent ever needs branching/stateful workflows (see docs/phase-5.md). |
| Docker Compose | Identical infra on any machine with one command. |
| WhatsApp/Instagram = paste-in drafting only | No official personal APIs; unofficial ones risk account bans. |

## Security baseline

- Secrets only in `.env` (git-ignored); `.env.example` documents the shape.
- OAuth tokens encrypted at rest.
- CORS restricted to the dashboard origin — never `*`.
- Per-agent permission scopes; append-only audit log.
- Prompt-injection defense: external content can influence *drafts* only — the
  Action Gateway means a manipulated agent still cannot act.

## Roadmap

0. Scaffold + infra (this repo skeleton) ✅
1. Core chat: LLM abstraction, streaming chat, persisted conversations ✅ (auth moved to Phase 3, see docs/phase-1.md)
2. Memory & RAG: pgvector, local embeddings, memory viewer, RAG-augmented chat ✅
3. Agent registry + **Action Gateway** + audit log + approvals UI ✅ (LangGraph + auth move to Phase 4, next to their first real use)
4. Communication agent: paste-in drafting, SMTP email via gateway, JWT auth ✅ (OAuth later; swap inside the email.send executor)
5. Job search agent: fit scoring, cover letters, interview prep, tracker + recruiters; OpenAI as second provider ✅
6. Productivity: tasks, reminders, deadlines, interviews ✅ (Google Calendar OAuth later)
7. Learning coach
8. Expansion: voice, local LLMs, finance/research agents

Gate between phases: it runs, tests pass, and `docs/phase-N.md` exists.
