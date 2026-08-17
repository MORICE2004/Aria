# ARIA — Personal AI Assistant

A personal "AI operating system": a hub where specialized AI agents (communication,
job search, research, documents, learning coach, productivity...) plug in, share
one memory, one voice and one permission system, and reach the outside world only
through the **Action Gateway**.

> **Core safety rule:** every outward action is an audited Action Gateway
> request, and permission is re-checked at execution time rather than trusted
> from when it was granted.
>
> Approval is normally a click. For WhatsApp it can also be a **standing policy
> you configured in advance** — a named contact, a named set of low-risk message
> categories — which lets ARIA answer routine messages without waking you for
> each one. That is a pre-authorisation of the same gate, not a way around it:
> risk, contact policy, autonomy mode, voice confidence and the kill switch are
> all re-evaluated at send time, and again when the message is handed to the
> sender. Nothing raises your autonomy level except you.

Reading it for the first time: [HANDOFF.md](HANDOFF.md) is the current state,
and it is kept honest about what does *not* work.

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

- [HANDOFF.md](HANDOFF.md) — **current state**: what works, what does not, and
  the exact next action
- [docs/architecture.md](docs/architecture.md) — the full system design and why
- [docs/ARIA_WHATSAPP.md](docs/ARIA_WHATSAPP.md) — the two-process bridge, the
  full path of one message, and how to link the sender
- [docs/ARIA_AUTONOMY.md](docs/ARIA_AUTONOMY.md) — autonomy levels, the risk
  engine, and the controls that stop ARIA
- [docs/ARIA_COMMUNICATION_LEARNING.md](docs/ARIA_COMMUNICATION_LEARNING.md) —
  how ARIA learns to write like you, and why she keeps one voice per audience
- [docs/ARIA_OPERATIONS.md](docs/ARIA_OPERATIONS.md) — migrations, backups,
  readiness checks, runbook
- [docs/phase-0.md](docs/phase-0.md) — what the first phase built
