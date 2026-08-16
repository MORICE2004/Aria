# ARIA — Handoff

Updated 2026-08-16. Keep this current after every significant phase.

## Current phase

**ARIA 2.0 directive — Phases 0, 1, 3, 5, 7, 8 complete.**
Audit, stabilize, model router, communication learning, WhatsApp connection,
and WhatsApp observe mode are all done and verified with real data.
Remaining: 2 (architecture cleanup), 4 (typed memory), 6 (OpenClaw — now
superseded by the read-only Baileys bridge), 9-22.

## Current status

ARIA 1.0 was audited and found healthy: 51 tests passing, no TODOs, no stubs,
no broken features. The 2.0 work so far is **additive** — nothing was removed
or rebuilt.

**100 tests passing.** Frontend lint + build clean.

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
- No typed memory (Phase 4), no research/document agents, no proactive
  engine, no Qdrant, no mem0 integration.
- Relationship-scoped style profiles not yet measured (scope system supports
  them; only global and per-contact are written today).

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

## Phase 8 — WhatsApp observe mode COMPLETE (2026-08-16)

Built: contacts + trust levels, autonomy modes, emergency stop (DB-backed,
survives restart), message store, local classifier, conversation simulator,
and the `/whatsapp` control centre.

**ARIA cannot send.** No send path exists in the WhatsApp module.

Verified live: injection attempt left trust `unknown`/mode `observe`;
emergency stop forced observe and returned 409 on escalation; the stop
survived an API restart; local classifier correctly flagged a Kiswahili money
request as `financial` + `high` urgency. **76 tests passing** (19 new).

Phase 7 (real account link) is still outstanding — see "Blocked on MORICE".

## Phase 5 - Communication learning COMPLETE (2026-08-16)

ARIA learns MORICE's writing voice from his real messages. Statistical
analysis (no LLM guessing), confidence = evidence/(evidence+8) capped at 0.95,
patterns below 0.25 excluded from prompts. Explicit rules trusted at 0.95.
Only direction="out" messages train his voice.

Verified live: 10 messages produced a real profile (5.4 avg words, 100%
lowercase openings, 'hey' 4x, 'just checking' 4x, 40% English/Kiswahili mix).
A live draft for "still meeting tomorrow?" returned "hey, yeah, still on" -
matching every learned pattern.

Full transparency at /style: every pattern with evidence, the literal prompt
block, preview-before-learning, and delete.

Bug found+fixed: multiple lessons from one edit shared a key and overwrote
each other, so evidence never accumulated. 100 tests passing.

## Next steps (in priority order)

1. **Phase 9 — suggestion mode**: real drafts for trusted contacts, surfaced
   in the approvals queue, feeding edits back into the learning loop.
2. **Phase 4 — typed memory + governance** (working/episodic/preference/
   relationship/project), scoring, provenance, "why do you remember that?".
3. **Cost/usage persistence** — `model_usage` table, surfaced on a Costs page.
4. **Relationship-scoped style** — measure per relationship type, not just
   global and per-contact.

## WhatsApp transport — RESOLVED (2026-08-16)

Originally routed through OpenClaw. OpenClaw is an AI gateway that
auto-replies with its own agent; that fired on a real inbound message. It was
replaced with `apps/wa-bridge`, a read-only Baileys client containing no send
code, enforced by `npm run verify-readonly` before every start.

OpenClaw's WhatsApp channel and the aria-bridge hook are disabled. The demo
number is paired to the Baileys bridge and real messages flow into ARIA.

Start with `start-whatsapp-bridge.ps1`. Delete `apps/wa-bridge/auth/` and
re-run to re-pair.

**Known risk:** automating WhatsApp violates its Terms of Service. Read-only
is lower risk than sending, but not zero. Use the demo number.
