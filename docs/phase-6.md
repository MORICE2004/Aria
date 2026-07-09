# Phase 6 — Productivity: Tasks, Reminders, Deadlines

Built 2026-07-09.

## What exists now

- **Task model + API** (`/tasks`): tasks, reminders, deadlines, and interview
  dates; optional due time; optional link to a tracked job (`job_id`);
  open/done lifecycle. `GET /tasks` returns urgency order (dated first,
  soonest first, then undated newest-first).
- **Tasks UI** (`/tasks`): add with kind + due picker (local time converted to
  UTC for the API), grouping into Overdue / Today / Upcoming / No date,
  checkbox complete, collapsible Done section.
- **Tests** (44 total, 4 new): lifecycle, urgency ordering, status filter,
  kind/status validation.

## Deliberate scope

- **No Google Calendar OAuth yet**: needs a Google Cloud project; the local
  calendar covers the core need. When OAuth lands, sync becomes an
  integration module, and calendar *writes* (creating events others see) can
  go through the Action Gateway if ever needed.
- **No notification push yet**: reminders are visible by urgency grouping;
  actual notifications (email/desktop) can arrive with the stats dashboard
  slice of the autonomous-apply spec (docs/specs/autonomous-apply.md).
- **Timezone note**: due times are stored UTC, entered and displayed local —
  the standard pattern; the conversion happens once at each edge.

## Also this session

The full autonomous job application spec was accepted into
`docs/specs/autonomous-apply.md` (future phases 8+), with two scope
adjustments: no LinkedIn/Indeed/Glassdoor scraping or Easy Apply automation
(ToS violation, account-ban risk) — discovery via Greenhouse/Lever/Ashby
public boards and company pages instead; and incremental delivery, one
verified slice per phase.

## How to verify

1. `/tasks`: add an interview with a due time, a deadline for tomorrow, and
   an undated task — they land in the right groups; overdue items turn up in
   red as time passes. Check one off; it moves to Done.
2. `pytest` → 44 passed.
