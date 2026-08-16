# ARIA — Communication Learning

Status: **implemented and verified with real data** 2026-08-16 (Phase 5).

The directive's stated most-important feature: ARIA learns how MORICE
actually writes, rather than being told "write like the user".

## The loop

```
OBSERVE     his real outgoing messages
   ↓
ANALYZE     measure style statistically (no LLM, no guessing)
   ↓
STORE       patterns with confidence + evidence counts
   ↓
GENERATE    drafts built from the profile
   ↓
USER EDITS  he changes the draft
   ↓
COMPARE     diff the draft against what he actually wrote
   ↓
LEARN       repeated differences become preferences
   ↓
IMPROVE     next draft is closer
```

## Two rules the whole design serves

**1. Never fabricate.** Every statistical dimension is *counted* from real
messages. "5.4 words per message over 10 samples" — both numbers are real and
recomputable. Nothing is estimated by a model.

**2. Never overfit.** Confidence follows `evidence / (evidence + 8)`, capped
at 0.95:

| Samples | Confidence |
|---|---|
| 1 | 0.11 — effectively ignored |
| 8 | 0.50 |
| 30 | 0.79 |
| 100 | 0.93 |
| ∞ | 0.95 — never certain |

Patterns below 0.25 are **omitted from prompts entirely** rather than
presented as fact. One message can nudge ARIA; it can never rewrite her.

## What is measured

`src/communication/style.py` — pure functions, fully testable:

message length · sentence count · emoji rate · question rate · exclamation
rate · lowercase-opening rate · ellipsis use · greetings · sign-offs ·
recurring phrases (2–3 word habits, only if repeated) · Kiswahili use ·
English/Kiswahili code-switching

## Only HIS voice trains his voice

Learning uses `direction == "out"` messages only. Inbound messages are other
people's writing and must never shape how ARIA writes as him. This is tested
explicitly: an inbound message in a wildly different style trains nothing.

## Sources of learning, in order of trust

| Source | Confidence | Why |
|---|---|---|
| **Explicit rule** ("never use Dear Sir/Madam") | 0.95 immediately | He said it. Not a guess. |
| **Repeated edits** | grows with repetition | A preference must recur to count |
| **Measured statistics** | grows with sample size | Real counts over real messages |

## Verified live (real data, 10 messages)

Measured:

```
avg_words       5.4 words per message
capitalisation  almost always starts lowercase (100%)
greeting        'hey' (4x), 'yo' (2x)
common_phrases  'just checking' (4x)
language        mixes English and Kiswahili (40% of messages contain both)
```

An edit produced these lessons:

```
draft: "Hello, I hope this message finds you well. I wanted to inquire
        whether you might be available."
final: "hey you free?"
→ prefers shorter: cut 17 words to 3
→ prefers opening 'hey' over 'hello'
→ prefers lowercase opening
```

And the resulting live draft, for *"Are we still meeting tomorrow at 3pm?"*:

```
hey, yeah, still on
```

Four words, lowercase, "hey", no emoji, no exclamation — matching every
learned pattern. A generic assistant would have written *"Hi! Yes, we're
still on for tomorrow at 3pm. Looking forward to it! 😊"*

## Transparency and control

Everything is inspectable at `/style`:

- every pattern with its confidence, evidence count, and source
- **"Show exactly what ARIA reads before drafting"** — the literal prompt block
- **Preview** what an edit would teach, before committing it
- **Forget** any pattern that is wrong

Learning is never silent: every edit returns the lessons drawn from it.

## Bug found and fixed during the build

Multiple lessons from a single edit all shared the key
`(edit_preference, global)` and overwrote each other, so evidence never
accumulated and a preference could never become confident. Each lesson now
gets its own dimension (`edit:<lesson>`). Caught by a test asserting that six
identical edits reach evidence count 6 — a weaker test would have missed it.

## Not yet done

- **Relationship-scoped profiles.** The scope system supports
  `relationship:friend` and `contact:<id>`, and profile assembly already
  prefers the most specific scope — but only `global` and `contact:` are
  currently written. Per-relationship measurement is the next increment.
- **LLM-judged dimensions** (formality, warmth, humour) — deliberately
  deferred: they cannot be counted, so they would need a different and more
  careful confidence treatment.
- Drafts do not yet flow automatically from WhatsApp into the feedback loop;
  that arrives with Phase 9 (suggestion mode).
