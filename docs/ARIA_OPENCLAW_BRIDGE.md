# ARIA ↔ OpenClaw bridge

Status: **wired and live** 2026-08-16. Awaiting a real inbound message for
final end-to-end proof.

## How messages reach ARIA

```
WhatsApp
  ↓
OpenClaw gateway  (127.0.0.1:18789, token auth, loopback only)
  ↓  fires `message:received`
aria-bridge hook  (~/.openclaw/hooks/aria-bridge/)
  ↓  POST + X-ARIA-Ingest-Secret
ARIA  POST /whatsapp/ingest
  ↓
observer.observe()  →  classify (local model) → store → autonomy gate
  ↓
nothing is sent
```

## Why a hook, not polling

`openclaw message read` returns **"not supported for channel whatsapp"** —
OpenClaw is a push gateway, not a pollable store. The documented inbound
surface is the internal hook event `message:received` ("Inbound message from
any channel").

## Why this bridge cannot reply

Two independent guarantees:

1. **OpenClaw ignores `event.messages` for `message:*` events** (documented in
   `docs/automation/hooks.md`: pushed strings are delivered only for
   `command:new`, `command:reset`, and compaction events). The hook has no
   channel back into the chat.
2. **ARIA's autonomy gate** — observe mode returns no draft, and no send path
   exists in ARIA's WhatsApp module.

Neither depends on a prompt.

## Files

| Path | Purpose |
|---|---|
| `~/.openclaw/hooks/aria-bridge/HOOK.md` | Hook metadata; subscribes to `message:received` |
| `~/.openclaw/hooks/aria-bridge/handler.js` | Forwards to ARIA; never throws |
| `~/.openclaw/hooks/aria-bridge/config.json` | URL + shared secret (**contains a secret; not in git**) |
| `apps/api/src/routers/whatsapp.py` | `POST /whatsapp/ingest` |

## Security

- Gateway binds **loopback only** with token auth.
- Ingest uses a shared secret compared in constant time, on a router
  **without** the dashboard JWT (the caller is a local service). Verified:
  401 without the secret.
- **Fails closed** — no `OPENCLAW_INGEST_SECRET` means ingest is refused (503).
- The hook never throws: ARIA being down logs a warning and drops the forward
  rather than breaking the messaging gateway.

## Operations

```bash
# gateway (installed as Windows scheduled task "OpenClaw Gateway")
openclaw gateway install      # (re)install
openclaw gateway uninstall    # remove entirely
openclaw channels status      # is WhatsApp connected?
openclaw hooks check          # are hooks ready?
openclaw hooks disable aria-bridge   # stop forwarding to ARIA
```

Verified state: gateway listening on `127.0.0.1:18789`; WhatsApp
`linked, running, connected, health:healthy`; 6/6 hooks ready.

## Gotchas hit while building this

- `openclaw gateway start` does not exist — it is `gateway run` (foreground)
  or `gateway install` (service).
- `gateway run` produces no output and never binds in a non-interactive
  shell; use the scheduled task.
- The scheduled task disappeared once after a stop/start cycle and had to be
  reinstalled. If the gateway is unreachable, check
  `schtasks /query | findstr OpenClaw` first.

## Remaining

End-to-end proof needs one real inbound WhatsApp message to the linked demo
number. Everything before that point is verified.
