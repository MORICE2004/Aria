# ARIA — Models & Routing

Status: **implemented and verified** 2026-08-16.

## The problem this solves

Sending "classify this message" to a premium cloud model wastes money and
leaks private content unnecessarily. Sending "analyse this contract" to a 3B
local model gives a bad answer. ARIA should pick per task.

## How it works

Callers never name a vendor. They declare **what kind of thinking** the work
needs, and `ModelRouter` resolves it to a provider.

| TaskClass | Used for | Preferred tier |
|---|---|---|
| `ROUTINE` | classification, extraction, summarisation, tagging | local |
| `CONVERSE` | chat, drafting | local |
| `REASON` | analysis, scoring, code review, planning | cloud |

Tiers, cheapest/most-private first: `LOCAL_FAST` → `LOCAL_REASONING` → `CLOUD`.

**Fallback is automatic and never silent-fails:** if the preferred tier is
unavailable (Ollama down, no cloud key), the router tries the next and logs
the fallback. If nothing is available it raises an actionable error naming
the exact fix.

`PREFER_LOCAL=true` pushes local ahead of cloud even for `REASON` — the
privacy/cost escape hatch, at some quality cost.

## Verified behaviour (live, against the real .env)

```
routine   -> local_fast   llama3.2:3b        (ran locally on llama3.2:3b)
converse  -> local_fast   llama3.2:3b        (ran locally on llama3.2:3b)
reason    -> cloud        gemini-2.5-flash   (ran in the cloud on gemini-2.5-flash)
```

Local inference verified end-to-end through the adapter: a real
`llama3.2:3b` call returned `"ARIA local inference works."`

## Providers

| Provider | File | Notes |
|---|---|---|
| Ollama | `src/llm/ollama.py` | Local. Native `/api/chat` over httpx — no new dependency. Free, private, offline. |
| Gemini | `src/llm/gemini.py` | **Currently active cloud provider.** Free tier. |
| OpenAI | `src/llm/openai.py` | Code complete, no key configured. |
| Claude | `src/llm/claude.py` | Code complete, no key configured. |

Every adapter implements the same `LLMProvider` contract. Adding a vendor is
one file plus a branch in `build_cloud_provider()`.

## Configuration

```
LLM_PROVIDER=gemini            # which cloud vendor to use
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_FAST_MODEL=llama3.2:3b  # empty disables the local fast tier
OLLAMA_REASONING_MODEL=        # optional larger local model
PREFER_LOCAL=false
```

## Offline behaviour

With `OLLAMA_FAST_MODEL` set, ARIA keeps working with **no internet and no API
key**: chat, drafting, classification and summarisation all run locally.
`get_llm_provider()` also falls back to Ollama when no cloud key is present,
so a lapsed API key degrades ARIA rather than breaking it.

## Where every endpoint routes (all migrated 2026-08-16)

| Endpoint | TaskClass | Runs on | Why |
|---|---|---|---|
| `POST /conversations/{id}/messages` | CONVERSE | local | Everyday chat — free, and conversation stays on the machine |
| `/communication/draft` | CONVERSE | local | Low-risk drafting; the conversation being replied to never leaves |
| `/communication/summarize` | ROUTINE | local | Summarisation is cheap, high-volume work |
| `/jobs/{id}/analyze` | REASON | cloud | Must emit valid JSON and sound judgement |
| `/jobs/{id}/cover-letter` | REASON | cloud | High-stakes writing |
| `/jobs/{id}/interview-prep` | REASON | cloud | Analysis |
| `/learning/explain` | REASON | cloud | A wrong explanation to a beginner is worse than none |
| `/learning/review` | REASON | cloud | Code review |
| `/learning/path` | REASON | cloud | Planning |

**`get_llm_provider()` has been removed.** It became dead code once every
endpoint moved to the router, and its fallback logic is now the router's tier
ordering. All model access goes through `get_router()` — a single choke point,
which is also why faking one dependency isolates the whole test suite.

Verified live (server logs, 2026-08-16):

```
chat              -> Ollama call (llama3.2:3b): 113 in, 9 out
learning/explain  -> Gemini call: 108 in, 787 out
jobs/analyze      -> Gemini call: 244 in, 219 out   (returned score 20 + notes)
```

## Not yet done

- **Cost/usage persistence.** Token counts are logged per call by every
  adapter but not stored or aggregated — ARIA cannot yet answer "what have I
  spent?". Requires a `model_usage` table and surfacing usage out of the
  streaming interface.
- **`ran_on` is only surfaced by `/communication/summarize`.** Other endpoints
  route correctly but don't yet tell the UI where they ran.
