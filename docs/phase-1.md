# Phase 1 — Core Chat

Built 2026-07-07.

## What exists now

- **LLM provider abstraction** (`src/llm/`): `LLMProvider` is the contract; the
  Claude adapter (`claude.py`) is the ONLY file that imports the Anthropic SDK.
  Swapping/adding OpenAI or a local model = one new adapter file. Token usage
  is logged on every call so spend stays visible.
- **Database layer** (`src/db.py`, `src/models.py`): async SQLAlchemy against
  Postgres; `Conversation` and `Message` tables, created automatically at startup.
- **Chat API** (`src/routers/chat.py`): create/list/delete conversations, list
  messages, and `POST /conversations/{id}/messages` which saves the user turn,
  streams Claude's reply chunk-by-chunk, then saves the full reply — even if the
  browser disconnects mid-stream.
- **Chat UI** (`apps/web/src/app/chat/page.tsx`): conversation sidebar,
  live-typing streamed replies, auto-titled conversations, error banner.
  `src/lib/api.ts` is the single place the frontend talks to the backend.
- **Tests** (8): chat flow, history persistence, validation rejection, 404s,
  delete — using a fake LLM and in-memory SQLite via dependency overrides, so
  tests are free, instant, and need no services running.

## Concepts introduced (plain-English)

- **Dependency injection**: endpoints declare what they need (a DB session, an
  LLM); FastAPI supplies it. Tests supply fakes instead — that's why we can
  test chat without paying for API calls.
- **Streaming**: the reply is sent as it's generated (like water through a
  hose, not a filled bucket), so the UI shows words immediately.
- **ORM**: `Conversation`/`Message` Python classes map to SQL tables; SQLAlchemy
  writes the SQL, always parameterized (no SQL injection).
- **Adapter pattern**: vendor SDKs hide behind our own interface, so vendors
  are swappable.

## Deferred, deliberately

- **Login/auth UI**: everything runs on localhost, single user, CORS-locked.
  Real auth lands with Phase 3's Action Gateway — before any agent can touch
  the outside world, not after.
- **Migrations (Alembic)**: `create_all` suffices until the schema evolves.

## How to verify

1. Put your key in `.env`: `ANTHROPIC_API_KEY=sk-ant-...`
2. `docker compose up -d`, then start API + web (see README).
3. Open http://localhost:3000/chat and talk to ARIA — replies stream in live.
4. Restart everything; the conversation is still there (it lives in Postgres).
5. `pytest` in `apps/api` → 8 passed.
