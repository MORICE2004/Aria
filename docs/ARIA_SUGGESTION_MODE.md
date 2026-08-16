# ARIA — Suggestion Mode (Phase 9)

Status: **implemented and verified end-to-end** 2026-08-16.

ARIA drafts replies for trusted contacts in MORICE's learned voice. He
approves, corrects, or rejects — and every correction feeds Phase 5's
learning loop, so the next draft is closer.

## The cycle

```
inbound message
   ↓  (contact trusted AND mode >= suggest AND not sensitive)
ARIA drafts in his learned voice
   ↓
draft appears on /whatsapp for review
   ↓
approve  /  correct  /  reject
   ↓
correction -> learning loop -> better next draft
```

## What it will not do

**Send.** ARIA's WhatsApp transport is the read-only Baileys bridge, which
contains no send code. "Approve" means *"this is good, I'll send it myself"*,
and the UI says exactly that. The API response includes `sent: false`
explicitly so the behaviour is never ambiguous.

**Draft on sensitive messages.** If the classifier flags a message as
financial, legal, contractual, employment-related, emotional, a money
request, or reputation-affecting, ARIA produces **no draft at all**.

The reasoning: a plausible-sounding draft on a sensitive topic is worse than
no draft. It invites a fast approval on exactly the messages that deserve
slow thought. Tested explicitly.

**Draft for untrusted contacts.** Unknown contacts stay observe-only no
matter the global mode — the Phase 8 trust ceiling still governs everything.

## Verified live

Contact marked `trusted`, mode `suggest`, inbound
*"yo are we still on for football saturday?"*:

```
mode : suggest
draft: hey, tutaonana kesho
sent : False
```

The draft used his learned greeting (`hey`) and his Kiswahili
code-switching — both measured in Phase 5, not configured.

Correcting it to *"yeah bro sawa, saa ngapi?"*:

```
status : edited
sent   : False
learned: prefers longer: expanded 3 words to 5
learned: prefers opening 'yeah' over 'hey'
```

Two lessons, immediately visible, feeding the profile. The loop closes.

## Honest limitation

The draft above is stylistically right but semantically weak — the question
was about Saturday football and `tutaonana kesho` means "see you tomorrow".
That is `llama3.2:3b` being a small local model, not a bug in the pipeline.

Options, in order of cost: set `CONVERSE_LOCAL=false` to draft with Gemini
(better meaning, less privacy), pull a larger local model, or accept it and
correct the drafts — corrections are what train ARIA anyway.

## Bug found during the build

`StylePattern.dimension` was `String(40)`, but edit-lesson keys like
`edit:prefers shorter: cut 17 words to 3` exceed that. Postgres rejected the
insert with a 500; **the test suite stayed green because SQLite silently
ignores VARCHAR limits.**

Fixed by widening the column to 120, truncating in code against a shared
`MAX_DIMENSION_LEN`, migrating the live table, and adding a test that asserts
the length directly rather than relying on the database to complain.

Worth remembering: the SQLite-for-tests trade buys speed and isolation, but
it will not catch column-width, type-strictness, or constraint differences.
Live verification against Postgres is not optional.
