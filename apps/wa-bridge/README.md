# ARIA WhatsApp bridge (read-only)

Connects to WhatsApp as a linked device and forwards inbound messages to ARIA.
**It cannot send.**

## Why this exists

ARIA previously received WhatsApp through OpenClaw. OpenClaw is an AI gateway
whose *purpose* is to auto-reply with an agent — the opposite of ARIA's
founding rule that nothing goes out without approval. Disabling that was
possible but meant relying on configuration to stay safe: one update, reset,
or missed flag and it sends as you.

This bridge removes the class of risk instead of configuring around it. There
is no send code in it.

## The guarantee, and how it is enforced

```bash
npm run verify-readonly
```

Scans the source for every Baileys sending API (`sendMessage`,
`sendPresenceUpdate`, `readMessages`, `relayMessage`, …) and exits non-zero if
any appears. Safety you can grep for beats safety you have to trust.

Also deliberately disabled:

| Behaviour | Why |
|---|---|
| Read receipts | Senders never see "read" just because ARIA looked |
| Presence / typing | ARIA never makes you appear online |
| Full history sync | Only messages from now on; no archive hoovering |
| Groups | Out of scope for now — DMs only |

## Setup

```bash
cd apps/wa-bridge
npm install
cp config.example.json config.json
#   set "secret" to OPENCLAW_INGEST_SECRET from ARIA's .env
npm start
```

On first run it prints a QR code. Scan it on the phone:
**WhatsApp → Settings → Linked Devices → Link a Device.**

Credentials are saved to `./auth/` (git-ignored) so later runs skip the QR.

## Running it

ARIA's API must be running, or messages are dropped with a warning (never
silently). The bridge reconnects automatically; if the phone logs the device
out, delete `./auth/` and re-pair.

`fromMe` messages — the ones you send — are forwarded too, marked
`direction: "out"`. That is how ARIA learns your writing style. They are never
treated as something to reply to.

## Terms of service

Automating WhatsApp through an unofficial client violates WhatsApp's terms,
and numbers can be banned. Read-only use is lower risk than automated sending,
but the risk is not zero. Use the dedicated demo number.
