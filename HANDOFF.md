# ARIA — Handoff

Updated 2026-08-16. Keep this current after every significant phase.

## Current phase

**ARIA 2.0 directive — Phase 0 (audit) and Phase 3 (model router) complete.**
Phase 1 (stabilize) complete as a side effect. Phases 2, 4–22 not started.

## Current status

ARIA 1.0 was audited and found healthy: 51 tests passing, no TODOs, no stubs,
no broken features. The 2.0 work so far is **additive** — nothing was removed
or rebuilt.

**57 tests passing.** Frontend lint + build clean.

## Working features (verified this session)

| Feature | Evidence |
|---|---|
| Postgres + Redis | Both containers healthy after Docker start |
| Full test suite | 57 passed |
| Local inference (NEW) | `llama3.2:3b` returned "ARIA local inference works." |
| Model router (NEW) | routine/converse → local; reason → cloud (verified live) |
| Routed summarisation (NEW) | Live `/communication/summarize` logged `Ollama call (llama3.2:3b): 119 in, 86 out`; API reported `ran locally on llama3.2:3b` |
| Gemini cloud path | Verified in prior session; still the configured cloud provider |

## Broken features

None known.

## Known gaps / not yet done

- **Cost tracking not persisted.** All adapters log token counts; nothing is
  stored or aggregated. ARIA cannot answer "what have I spent?"
- **Auth still disabled** (`ARIA_PASSWORD` empty). Safe on localhost, unsafe
  the moment ARIA listens on the LAN.
- No WhatsApp, no typed memory, no communication learning, no autonomy modes,
  no emergency stop, no contacts model, no research/document agents, no
  proactive engine, no Qdrant, no mem0 integration.

## Files created this session

```
docs/ARIA_CURRENT_STATE.md     full 17-point audit
docs/ARIA_PRODUCT_VISION.md    vision + invariants ("must never be removed")
docs/ARIA_MODELS.md            routing design, verified behaviour, gaps
HANDOFF.md                     this file
apps/api/src/llm/ollama.py     local provider (httpx, no new dependency)
apps/api/src/llm/router.py     TaskClass/Tier routing with fallback
apps/api/tests/test_router.py  6 routing + fallback tests
```

## Files changed

```
apps/api/src/llm/__init__.py           build_cloud_provider() + get_router()
apps/api/src/core/config.py            Ollama + PREFER_LOCAL settings
apps/api/src/routers/communication.py  /summarize routed as ROUTINE, returns ran_on
apps/api/tests/conftest.py             FakeRouter so tests never hit real models
.env.example                           Ollama settings documented
```

## Environment requirements

- Docker Desktop **must be running** (Postgres + Redis). It was stopped at the
  start of this session — that alone makes ARIA appear broken.
- Ollama running with `llama3.2:3b` pulled (2.0 GB, installed).
- `.env` has `LLM_PROVIDER=gemini` + a working `GEMINI_API_KEY`.

## Commands

```bash
# start everything
./start-aria.ps1

# backend tests
cd apps/api && .venv/Scripts/python -m pytest -q

# frontend checks
cd apps/web && npm run lint && npm run build

# check routing decisions
cd apps/api && .venv/Scripts/python -c "from src.llm.router import ModelRouter, TaskClass; r=ModelRouter(); [print(t.value, '->', r.resolve(t).description) for t in TaskClass]"
```

## Tests performed

- Full backend suite: 57 passed.
- Live local inference through the Ollama adapter.
- Live router resolution against the real `.env`.
- Live `/communication/summarize` end-to-end, confirmed local via server log.
- Frontend lint + production build.

## Failed approaches / gotchas

- **`ollama pull` appeared to hang at 100%.** The blob downloaded but the
  manifest write didn't finish under a background timeout. Re-running the
  pull completed instantly (blob was cached). Not an error.
- **Stale `uvicorn` processes serve old settings.** Repeatedly caused false
  "wrong provider" readings. Always `taskkill //F //IM python.exe` before
  verifying a config change.
- **`du -sh` on large repos is very slow on Windows** — avoid it.

## Agent migration — COMPLETE (2026-08-16)

All 9 LLM endpoints now declare a TaskClass. Chat, drafting and summarising
run locally (free, private); job scoring, cover letters, interview prep and
all three learning-coach tools escalate to cloud. `get_llm_provider()` was
removed as dead code. Verified live — see `docs/ARIA_MODELS.md` for the table
and the server-log evidence.

New setting: `CONVERSE_LOCAL` (default true). Set false to send chat and
drafting to the cloud model instead — the one routing choice with a real
quality-vs-privacy tradeoff.

## Next steps (in priority order)

1. **Cost/usage persistence** — `model_usage` table, surfaced on a Costs page.
   Requires reporting usage out of the streaming interface.
3. **Phase 4 — typed memory + governance** (working/episodic/preference/
   relationship/project), scoring, provenance, "why do you remember that?".
4. **Phase 5 — communication learning loop** (observe → draft → compare edit →
   learn, with confidence scores and per-contact profiles). This is the
   directive's stated most-important feature and depends on Phase 4.
5. **Phases 6–13 — OpenClaw/WhatsApp**, which needs MORICE's decision (see below).

## Blocked on MORICE

**WhatsApp (phases 6–13) requires a decision only he can make.**

1. *What is needed:* his consent to link his personal WhatsApp number, and a
   QR-code scan he must perform physically.
2. *Why:* OpenClaw links as a WhatsApp Web device; the scan cannot be automated.
3. *Where to obtain:* WhatsApp → Settings → Linked Devices.
4. *Where it goes:* `openclaw channels login --channel whatsapp`.
5. *What happens after:* build the ARIA↔OpenClaw bridge in **observe mode
   first** (Phase 8) — read and learn only, no sending — then suggestion mode.

**Known risk, stated once:** automating WhatsApp violates its Terms of
Service; numbers do get banned, more likely with automated sending. A
dedicated secondary number is the safer option.
