# aria-bridge hook (source of truth)

The live copy runs from `~/.openclaw/hooks/aria-bridge/`. This directory is
the version-controlled source so the bridge is not lost if that directory is
wiped.

Install:

```bash
mkdir -p ~/.openclaw/hooks/aria-bridge
cp HOOK.md handler.js ~/.openclaw/hooks/aria-bridge/
cp config.example.json ~/.openclaw/hooks/aria-bridge/config.json
# edit config.json: set "secret" to OPENCLAW_INGEST_SECRET from ARIA's .env
openclaw hooks enable aria-bridge
openclaw gateway install   # then start the "OpenClaw Gateway" scheduled task
```

`config.json` holds a secret and is deliberately NOT committed.
