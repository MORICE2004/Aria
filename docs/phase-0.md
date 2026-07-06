# Phase 0 — Foundation

Built 2026-07-06.

## What exists now

- **Monorepo** at `aria/` with `apps/api` (FastAPI) and `apps/web` (Next.js).
- **API**: app factory (`src/main.py`), env-driven config (`src/core/config.py` —
  the only place that reads the environment), central logging, `/health` endpoint,
  CORS locked to `http://localhost:3000`.
- **Web**: dark dashboard shell with sidebar (nav entries map to future phases)
  and a home page that live-checks the API's `/health`.
- **Infra**: `docker-compose.yml` with PostgreSQL 16 (pgvector image, ready for
  Phase 2 embeddings) and Redis 7, both with healthchecks and persistent volumes.
- **Tests**: `pytest` suite for the health endpoint (runs without any server/DB).
- **CI**: GitHub Actions workflow — backend tests + frontend lint/build on every push.
- **Secrets hygiene**: `.env.example` template; `.env` git-ignored.

## Concepts introduced (plain-English)

- **Monorepo**: one git repo holding multiple apps that ship together.
- **App factory**: building the FastAPI app inside a function so tests can create
  fresh instances and all wiring lives in one place.
- **CORS**: browsers block cross-site requests unless the API explicitly allows
  the caller's origin. We allow only our own dashboard.
- **Healthcheck**: a cheap endpoint that answers "is this service alive?" —
  used by the UI, Docker, and future monitoring.
- **Named Docker volumes**: your database data survives `docker compose down`.

## How to verify

1. `docker compose up -d` (requires Docker Desktop) — both containers report healthy.
2. `cd apps/api && .venv\Scripts\activate && pytest` → 2 passed.
3. `uvicorn src.main:app --reload --port 8000` → http://localhost:8000/docs shows the API.
4. `cd apps/web && npm run dev` → http://localhost:3000 shows the dashboard with a
   green "API online" indicator.

## Known gaps (intentional, coming in Phase 1)

- No database models/migrations yet (the API doesn't touch Postgres until it needs to).
- No auth yet.
- Sidebar links other than Home are placeholders.
