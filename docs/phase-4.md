# Phase 4 — Communication Agent, Email, and Auth

Built 2026-07-07.

## What exists now

- **Communication agent** (`src/agents/communication.py`): drafts replies for
  WhatsApp / Instagram / LinkedIn / email from a pasted conversation, in
  MORICE's voice (it retrieves `style` memories and imitates them), and
  summarizes conversations. It produces TEXT only.
- **Prompt-injection defense** (first phase where it matters): pasted
  conversations are wrapped in explicit `CONVERSATION START/END (untrusted
  data)` markers, and the system prompt orders the model to treat them as
  data, not instructions. Structurally, even a fooled model can only produce
  a draft MORICE reads or a queue entry MORICE reviews.
- **Email sending via SMTP** (`src/integrations/email.py`): registered as the
  `email.send` gateway executor — reachable only from the approve path. Uses
  STARTTLS; Gmail works with an App Password (see .env.example). Unconfigured
  SMTP fails loudly at approval and is recorded as `failed` in the audit log.
- **Auth** (`src/core/security.py`, `/auth`): single-user password login
  issuing 7-day JWTs; all personal-data routers require a token. With
  `ARIA_PASSWORD` empty, auth is disabled (localhost dev mode) — set it (plus
  a random `SECRET_KEY`) to turn login on; the dashboard has a `/login` page
  and attaches the token automatically.
- **Messages UI** (`/messages`): platform picker, paste box, "what should the
  reply achieve", draft + copy button; for email, a "queue for approval"
  hand-off to the Approvals page.
- **Tests** (31 total, 11 new): draft pipeline, platform validation,
  email-request-only-enqueues, failed-executor auditing, auth on/off,
  wrong password, bad token.

## Concepts introduced (plain-English)

- **JWT**: a signed token — the server can verify it wasn't forged without
  keeping session state. Signed ≠ encrypted: don't put secrets inside one.
- **Constant-time comparison**: password checks use `secrets.compare_digest`
  so response timing can't leak how many characters matched.
- **Prompt injection**: content an LLM reads (a message from someone else, a
  job ad) may contain instructions aimed at the model. Defense in depth:
  mark data as data AND make sure the model's output can't act by itself.
- **App Password**: a per-app secret from Google that avoids storing your
  real password; revocable independently.

## Deliberate scope choices

- **SMTP now, Gmail OAuth later**: an App Password is a 2-minute setup; OAuth
  needs a Google Cloud project. The executor boundary means OAuth can replace
  SMTP later without touching anything else.
- **Still no LangGraph**: a one-shot draft is a function call, not a graph
  (YAGNI). It lands with the first genuinely multi-step agent (Phase 5).

## How to verify

1. `/messages`: paste any conversation, click *Draft reply* — without an
   Anthropic key you get the clear "ANTHROPIC_API_KEY is not set" message;
   with a key, a draft in your style (add `style` memories first!).
2. Draft an email, queue it, approve on `/approvals` — with SMTP configured
   it sends; without, status `FAILED` with the SMTP hint, fully audited.
3. Set `ARIA_PASSWORD` + `SECRET_KEY` in `.env`, restart the API: every page
   bounces to `/login`; the password unlocks everything for 7 days.
4. `pytest` → 31 passed.
