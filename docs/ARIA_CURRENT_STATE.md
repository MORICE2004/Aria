# ARIA — Current State Audit

Audited 2026-08-16, against commit `daaf49a`. This document describes **reality**,
not intent. Anything listed as working was verified by running it.

Audit method: full source tree inspection, debt-marker grep
(TODO/FIXME/NotImplemented/stub/placeholder/hardcoded/deprecated), test suite
execution, live environment probes, git history review.

---

## 1. Existing architecture

Monorepo, modular monolith. No microservices.

```
apps/api   FastAPI (Python 3.14) — 38 source files
apps/web   Next.js 15 + TypeScript + Tailwind — 13 source files, 10 pages
docker-compose.yml   PostgreSQL 16 (pgvector image) + Redis 7
```

Backend module layout:

| Module | Responsibility |
|---|---|
| `core/` | config (single env reader), logging, security (JWT) |
| `llm/` | provider abstraction — `base.py` contract + claude/openai/gemini adapters |
| `memory/` | chunking, embeddings, RAG service |
| `agents/` | agent registry + 4 agents |
| `gateway/` | Action Gateway: approval queue + executor registry |
| `integrations/` | email (SMTP send), inbox (IMAP read) |
| `routers/` | 10 HTTP routers |

**Architectural strengths worth preserving:** the LLM provider abstraction
(3 vendors, adding a 4th is one file), and the Action Gateway (single
choke point for all outward action — executors are reachable from exactly
one code path).

## 2. Existing features

Chat (streaming), semantic memory + RAG, Action Gateway approvals with audit
trail, communication drafting (4 platforms), email send/read, job tracker with
AI fit scoring, recruiter contacts, tasks/reminders/deadlines, learning coach
with progress tracking, notifications aggregator.

## 3. Working features (verified)

| Feature | Verification |
|---|---|
| Chat via Gemini | Live call returned a real reply; `gemini-2.5-flash`, HTTP 200, 57/24 tokens |
| Memory + semantic search | "career ambition" → "Career goals" @ 0.65 vs unrelated @ 0.45 |
| Learning coach | Live explanation generated, progress-list aware |
| Action Gateway | submit → pending → approve → executed; double-approve blocked (409) |
| Audit trail | `submitted → approved → executed`, timestamped |
| Job tracker CRUD | Add/status-change/recruiters verified against Postgres |
| Tasks + urgency | Overdue detection verified |
| Notifications | Overdue task surfaced; unconfigured IMAP reported cleanly |
| Auth (when enabled) | Tests prove 401 on all protected routers |
| Test suite | **51 passed** |

## 4. Broken features

**None found.** No failing tests, no runtime errors in any exercised path.

Environment issues (not code defects), as of audit time:
- Docker daemon was **not running** → Postgres/Redis down → ARIA unusable until started.
- Ollama server running, **0 models installed** → local inference impossible.

## 5. Partially implemented features

| Feature | State |
|---|---|
| **Auth** | Fully implemented and tested, but **disabled** (`ARIA_PASSWORD` empty). Zero access control at runtime. |
| **Email send (SMTP)** | Executor implemented + gateway-wired; **unconfigured**, fails loudly on approval. |
| **Email read (IMAP)** | Implemented read-only; **unconfigured**. |
| **Writing-style adaptation** | Drafts retrieve `kind="style"` memories — but this is *retrieval only*. There is **no learning loop**: no observation of edits, no feedback capture, no confidence scoring. |
| **Cost tracking** | Token counts are `logger.info`-ed per call. **Not persisted, not aggregated, not displayed.** |
| **Anthropic/OpenAI providers** | Code complete; no keys configured. Only Gemini is live. |

## 6. Existing integrations

- **SMTP** (send, gateway-gated) — unconfigured
- **IMAP** (read-only, never marks read) — unconfigured
- **Gemini API** — **active and working**
- No WhatsApp, no calendar, no OpenClaw, no Ollama, no Qdrant, no mem0 integration.

## 7. Existing AI models

Provider selected by `LLM_PROVIDER` env var; currently `gemini` → `gemini-2.5-flash`.
Adapters exist for `claude` and `openai`. **One provider active at a time — there
is no router.** No task-complexity-based selection. No local models.

Embeddings: local `fastembed` / BAAI/bge-small-en-v1.5, 384-dim, CPU. Private by design.

## 8. Existing memory

Two tables: `memory_items` (title, kind, content) and `memory_chunks`
(chunk text + 384-dim pgvector embedding). Retrieval = cosine similarity,
threshold ≥ 0.55, top-4 injected into the chat system prompt.

**Limitation vs. the 2.0 target:** memory is a **single flat store**. `kind` is
only `note|document|fact|style`. There is no working/episodic/preference/
relationship/project memory distinction, no memory scoring or governance, no
decay, no provenance ("why do you remember that?"), and no extraction —
everything is manually entered by the user.

## 9. Existing database

PostgreSQL 16 + pgvector. 10 tables: `conversations`, `messages`,
`memory_items`, `memory_chunks`, `job_applications`, `recruiter_contacts`,
`tasks`, `learning_topics`, `action_requests`, `audit_events`.

Schema created via SQLAlchemy `create_all` at startup. **No migration tool
(Alembic).** Acceptable so far; becomes a liability as the schema evolves.

## 10. Existing authentication

Single-user password → 7-day JWT (HS256), constant-time comparison. All
personal-data routers depend on `require_auth`; `/health` and `/auth` public.
**Disabled at runtime** because `ARIA_PASSWORD` is empty.

No rate limiting. No CSRF tokens (no cookie auth — bearer only, so lower risk).
No account lockout.

## 11. Existing UI

Next.js 15, 10 pages: Home (command center), Chat, Memory, Approvals, Messages,
Jobs, Tasks, Learning, Login, plus a global notification bell.
Dark "Jarvis" visual language: glass panels, cyan reactor accent, Lucide icons.
Responsive — sidebar collapses to an icon rail on mobile. PWA manifest present.

Missing vs. the 2.0 target: WhatsApp, Communication Profile, Agents, Calendar,
Documents, Research, Integrations, Activity, Security, Costs, Settings pages,
and any autonomy-level/emergency-stop control.

## 12. Existing automation

**Effectively none.** ARIA is entirely reactive — every action requires a user
click. There is no scheduler, no background worker, no proactive engine, no
polling beyond the frontend's 60-second notification fetch. Redis is running
but **unused** (reserved for queues that were never built).

## 13. Existing security

Implemented and genuinely good:
- **Action Gateway** — the single exit for outward action; executors registered
  in one dict, callable only from the approve path. Structurally prevents an
  agent (even a prompt-injected one) from acting alone.
- **Append-only audit log** — no update/delete path exists in the codebase.
- **Prompt-injection defense** — untrusted content (pasted conversations, job
  postings, code, emails) wrapped in explicit `START/END (untrusted data)`
  markers with instructions to treat as data.
- Secrets only in git-ignored `.env`; `.env.example` documents shape.
- CORS restricted to localhost + private-LAN origins (never `*`).
- Pydantic validation at every request boundary; parameterized SQL via ORM.
- Constant-time password comparison.

Gaps: auth off, no rate limiting, no per-tool risk levels, no encryption at
rest for future OAuth tokens, no backups, no secret-scanning of git history.

## 14. Existing tests

**51 tests, all passing**, ~3.4s. Cover: health, chat + history persistence,
memory (chunking/ingest/search/validation), gateway safety guarantees
(no-execute-while-pending, single execution, 409 on re-decide, audit
completeness), communication (draft/summarize/enqueue-only/failed-executor
auditing), auth (on/off, bad password, bad token), jobs (parser edge cases,
CRUD, honest no-score path), tasks, notifications.

Tests use a fake LLM + fake embedder + in-memory SQLite via dependency
overrides — fast, free, no services required.

Not covered: frontend (zero UI tests), model routing, concurrency, load,
security scanning.

## 15. Existing technical debt

| Item | Severity | Note |
|---|---|---|
| No DB migrations (`create_all`) | Medium | Schema changes will get painful |
| Auth disabled by default | Medium | Fine on localhost, unsafe on LAN |
| pgvector `comparator_factory` workaround | Low | Documented in `models.py`; needed because the cross-DB TypeDecorator hides `cosine_distance` |
| Lazy imports in `memory/__init__.py` | Low | Circular-import workaround, documented |
| Redis running but unused | Low | Dead infrastructure until queues exist |
| Cost data logged, not stored | Low | Cannot answer "what have I spent?" |
| No frontend tests | Medium | UI regressions would be silent |
| `main.py` router wiring growing | Low | Fine now, watch it |

**No TODO/FIXME/stub markers exist in the codebase.** The debt above is
structural, not litter.

## 16. Existing unfinished work

- `docs/specs/autonomous-apply.md` — accepted spec for autonomous job
  application (phases 8+), with agreed scope cuts (no LinkedIn/Indeed/Glassdoor
  scraping — ToS/ban risk). Not started.
- Google Calendar OAuth — deferred, documented in `docs/phase-6.md`.
- Gmail OAuth (to replace SMTP/IMAP app-password auth) — deferred, `docs/phase-4.md`.

## 17. Features originally intended but not implemented

From the original architecture (`docs/architecture.md`) and roadmap:

- **Local LLM support** — listed as Phase 8 expansion, never built. *(Now
  actionable: Ollama is installed.)*
- **Voice interface** — never started.
- **Home automation, image generation, finance/trading/business agents** —
  listed as future expansion, never started.
- **LangGraph** — originally planned, then **deliberately removed** in Phase 5
  (documented, YAGNI: all agents are straight call sequences). Reinstating it
  is justified only for genuinely stateful multi-step workflows.

---

## Summary judgment

ARIA 1.0 is **small, clean, honest, and working**. 51 green tests, no dead code,
no stubs, a genuinely well-designed safety spine, and three of its four
"pillars" (chat, memory, approvals) verified live.

It is also **narrow**: single active model, flat memory, zero automation, zero
learning, one channel (web), and no autonomy machinery whatsoever.

The 2.0 directive is therefore mostly **additive**, not corrective. The right
strategy is to extend the existing abstractions — the provider interface, the
agent registry, the executor registry, the memory service — rather than rebuild.
Nothing in the current codebase needs to be thrown away.
