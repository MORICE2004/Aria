---
name: aria-bridge
description: "Forward inbound WhatsApp messages to ARIA for observation and learning"
metadata:
  { "openclaw": { "emoji": "🛰️", "events": ["message:received"] } }
---

# ARIA Bridge

Forwards every inbound message to ARIA's `/whatsapp/ingest` endpoint so ARIA
can observe, classify, and learn from it.

**This hook cannot reply.** OpenClaw ignores `event.messages` for `message:*`
events, so there is no path for this hook to put text back into a chat. ARIA's
own autonomy gate is the second, independent guarantee.

## Configuration

`config.json` in this directory:

```json
{
  "url": "http://127.0.0.1:8000/whatsapp/ingest",
  "secret": "<same value as OPENCLAW_INGEST_SECRET in ARIA's .env>",
  "channels": ["whatsapp"]
}
```

Environment variables `ARIA_INGEST_URL` and `ARIA_INGEST_SECRET` override the
file when set.

## Failure behaviour

If ARIA is not running, the POST fails and the hook logs a warning. It never
throws — a down dashboard must not break the messaging gateway, and it must
never silently look like success.
