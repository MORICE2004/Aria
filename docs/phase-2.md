# Phase 2 — Memory & RAG

Built 2026-07-07.

## What exists now

- **Embedding provider** (`src/memory/embeddings.py`): same adapter pattern as
  the LLM. Default: `fastembed` running locally on the CPU — free, private
  (memory content never leaves the machine to be indexed), no extra API key.
  The model (~100 MB) downloads once on first use.
- **Chunking** (`src/memory/chunking.py`): documents are split on paragraph
  boundaries (~1200 chars, one-paragraph overlap) so retrieval returns the
  relevant paragraph, not a whole file.
- **Memory service** (`src/memory/service.py`): ingest (chunk → embed → store)
  and semantic search. On Postgres, pgvector computes cosine similarity in the
  database; tests use a Python fallback over SQLite.
- **Memory API** (`/memory`): add, list, search (`?q=`), delete.
- **RAG in chat**: before every reply, chat searches memory with the user's
  message; hits scoring ≥ 0.55 are added to the system prompt with an explicit
  "do not invent memories" instruction.
- **Memory viewer UI** (`/memory`): add notes/documents/facts/writing samples,
  search by meaning, see match scores, delete (with confirmation) — you can
  always inspect exactly what ARIA knows.
- **Tests** (13 total): chunking edge cases, ingest/list/delete, kind
  validation, relevance-ordered search — all with a deterministic fake embedder.

## Concepts introduced (plain-English)

- **Embedding**: text → vector of numbers where similar meanings land near
  each other. Verified live: "what do I want to do professionally?" matched
  "become a backend developer" (0.67) far above a groceries note (0.45),
  despite sharing no keywords.
- **Chunking**: split before embedding, so one vector = one idea.
- **RAG**: retrieve relevant memories, hand them to the model with the
  question. The model doesn't "learn" your data; it reads it at answer time.
- **Cosine similarity/distance**: the angle-based closeness measure between
  two vectors; `<=>` is pgvector's operator for it.

## Gotcha worth remembering

Wrapping pgvector's column type in a cross-database `TypeDecorator` hides its
comparator, so `.cosine_distance` disappeared at runtime (found during live
verification, not by tests — SQLite tests take the Python path). Fixed by
re-exposing the operator via `comparator_factory` in `src/models.py`.

## How to verify

1. Start everything (README), open http://localhost:3000/memory.
2. Add a fact about yourself and an unrelated note; search by a paraphrase —
   the related one ranks first with a higher score.
3. In chat, ask something your memory can answer — ARIA uses it.
4. Delete a memory, ask again — ARIA no longer knows it.
5. `pytest` in `apps/api` → 13 passed.
