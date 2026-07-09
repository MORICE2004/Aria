# Phase 7 — Learning Coach

Built 2026-07-09.

## What exists now

- **Topic tracker** (`/learning/topics` API + UI): the things MORICE is
  learning, each with self-assessed status (learning → comfortable →
  mastered) and optional notes.
- **Learning coach agent** (`src/agents/learning.py`) — text-only, no gateway
  actions. Its defining feature: **every prompt includes the progress list**,
  so it builds on known topics and assumes nothing else. Three tools:
  - **Explain**: analogy first, then a runnable example, then one exercise
    and a pointer to the next topic.
  - **Review code**: mentor-style — what's wrong, why it matters, corrected
    lines, and what was done well; instructed not to invent problems. Pasted
    code is wrapped in untrusted-data markers (same defense as elsewhere).
  - **Learning path**: 5–10 ordered steps toward a goal, each with a practice
    project and a "ready to move on when…" check; skips mastered topics.
- **Learning UI** (`/learning`): tracker with one-click status chips on the
  left; Explain / Review code / Learning path tabs on the right.
- **Tests** (48 total, 4 new): topic lifecycle + validation, progress list
  included in prompts, code marked as data, goal validation.

## Design note

Progress lives in its own table rather than memory/RAG because it's
*structured, enumerable* data the coach needs in full every time — a SQL
`SELECT` is exact; semantic search is for unstructured knowledge. Rule of
thumb worth remembering: precise lists → tables; prose knowledge → RAG.

## How to verify

1. `/learning`: add topics you actually know ("Variables", mark comfortable)
   and one you don't. With an LLM key, ask it to explain something advanced —
   the answer builds only on your marked topics. Without a key: clear 503.
2. Paste real code into Review — it should also tell you what you did well.
3. `pytest` → 48 passed.
