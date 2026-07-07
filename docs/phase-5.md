# Phase 5 — Job Search Agent + OpenAI Provider

Built 2026-07-07.

## What exists now

- **OpenAI provider** (`src/llm/openai.py`): second LLM adapter. Switch
  vendors with `LLM_PROVIDER=openai` + `OPENAI_API_KEY` in `.env` (model via
  `OPENAI_MODEL`, default gpt-5.1). Proof of the Phase 1 abstraction: one new
  file, one factory branch, zero changes anywhere else.
- **Job tracker** (`/jobs` API + UI): applications with status pipeline
  (saved → applied → interview → offer/rejected), notes, posting URL and
  description; recruiter contacts CRUD.
- **Job search agent** (`src/agents/jobsearch.py`), all draft-only:
  - **Analyze fit**: scores a posting 0–100 against MORICE's profile (pulled
    from Memory — add your CV/skills there!), with strengths and gaps. The
    model must answer in JSON; `parse_analysis()` handles fenced/messy JSON,
    and an unparseable reply is stored as raw text with score = None — we
    never invent a number.
  - **Cover letter**: grounded in profile facts, explicit "never invent
    experience" instruction; saved on the job.
  - **Interview prep**: likely questions + guidance + questions to ask.
- **Safety posture**: this agent has `allowed_actions=()` — no gateway
  actions at all. Job postings are untrusted input (same marker defense);
  applying is always manual, per the project's ground rules.
- **Tests** (40 total, 9 new): parser (plain/fenced/garbage/out-of-range),
  CRUD + status validation, honest no-score path, recruiter validation.

## Concepts introduced (plain-English)

- **Structured output**: asking an LLM for JSON and *defensively parsing* it.
  LLMs are text generators — they usually comply, sometimes don't; code that
  trusts them blindly breaks. Parse, validate ranges, and have an honest
  fallback.
- **Provider switching**: the factory pattern paying off — `_cached_provider()`
  reads one setting and returns whichever adapter matches.

## Final call on LangGraph

Removed from the plan (was "deferred"). Every agent so far — and this one,
our most complex — is a straight sequence of calls, which plain async
functions express more clearly than a graph, especially for a beginner
codebase. A workflow engine earns its place when an agent needs branching,
retries with state, or long-running interrupts (e.g. a future autonomous
research agent). Revisit then; YAGNI until.

## How to verify

1. Add your CV and skills as memories on `/memory` (kind: document/fact).
2. On `/jobs`: track a real posting (paste the description), move its status.
3. With an LLM key: *Analyze fit* → score badge + strengths/gaps;
   *Draft cover letter*; *Interview prep*. Without a key: clear 503 message.
4. `pytest` → 40 passed.
