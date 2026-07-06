# ARIA — Personal AI Assistant

A personal "AI operating system": a hub where specialized AI agents (communication,
job search, learning coach, productivity...) plug in, share one memory, and route
every sensitive action through **your explicit approval**.

> **Core safety rule:** agents can *read* and *draft*, but nothing is ever sent,
> submitted, or published without human approval via the Action Gateway.

## Structure

```
aria/
├── apps/
│   ├── api/    # FastAPI backend (Python) — agents, memory, action gateway
│   └── web/    # Next.js dashboard (TypeScript) — chat, approvals, trackers
├── docs/       # architecture decisions and per-phase notes
└── docker-compose.yml  # PostgreSQL (+pgvector) and Redis
```

## Requirements

- Python 3.12+
- Node.js 20+
- Docker Desktop (for PostgreSQL and Redis)
- Git

## Quick start

```powershell
# 1. Copy the environment template and fill in your values (never commit .env!)
copy .env.example .env

# 2. Start the databases
docker compose up -d

# 3. Backend (in one terminal)
cd apps/api
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn src.main:app --reload --port 8000

# 4. Frontend (in another terminal)
cd apps/web
npm install
npm run dev
```

- API: http://localhost:8000 — interactive docs at http://localhost:8000/docs
- Dashboard: http://localhost:3000

## Running tests

```powershell
cd apps/api
.venv\Scripts\activate
pytest
```

## Documentation

- [docs/architecture.md](docs/architecture.md) — the full system design and why
- [docs/phase-0.md](docs/phase-0.md) — what this phase built
