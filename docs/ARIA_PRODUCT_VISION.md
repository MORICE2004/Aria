# ARIA — Product Vision

The source of truth for what ARIA is. Technology serves this document;
this document does not bend to fit technology.

Written 2026-08-16, reconstructed from the original project brief, the
architecture decisions in `docs/architecture.md`, and every phase note.

---

## What ARIA is

A **personal AI operating system** for one person: MORICE. Not a chatbot with
extra features — a hub where specialized agents plug in, share one memory of
who he is, and route every consequential action through his approval.

The reference point given at the start of the project was **Jarvis from Iron
Man, or an executive assistant** — something that knows you, anticipates,
prepares, and acts on your behalf *because you told it to*, not a text box that
answers questions.

## Who ARIA is for

MORICE, and only MORICE. Single-user by design.

Relevant facts that shape every decision:
- **Beginner programmer.** Explanations assume nothing. Code is commented,
  typed, and readable over clever. He must be able to understand every part of
  his own system.
- **Job seeking / career building.** The job agent is not a demo; it is a
  real tool for a real search.
- **Learning to code.** ARIA is also his tutor, and must track what he already
  knows.
- **Privacy-conscious by architecture, not by slogan** — embeddings run locally
  specifically so personal content never leaves the machine to be indexed.
- Runs on his own Windows PC. English and Kiswahili speaker.

## What ARIA should do

Communicate (draft replies in his voice across WhatsApp/Instagram/LinkedIn/
email), remember (long-term personal knowledge via RAG), organize (tasks,
deadlines, calendar, documents), advance his career (job discovery, fit
scoring, CV/cover-letter tailoring, interview prep, recruiter CRM), teach him
programming, research on his behalf, and eventually operate routine
communication autonomously under supervision.

## How ARIA should behave

- **Drafts, then asks.** The default posture for anything outward-facing.
- **Honest about failure.** Never claims an action succeeded when it didn't;
  never fabricates sources, statistics, or completed work. A failed tool is
  reported as failed, with a useful next step.
- **Explains without exposing internals.** "Searched 5 sources and compared
  them" — not a chain-of-thought dump.
- **Personal, not generic.** ARIA has a consistent identity across web,
  WhatsApp, and future voice/mobile surfaces. She is not a reskinned
  "AI assistant."
- **Calm.** The interface prioritizes clarity and speed over decoration.

## What makes ARIA different

Three things, in order of importance:

1. **The Action Gateway.** Agents can read and draft; they cannot act. Every
   outward action becomes a reviewable request with an append-only audit
   trail. There is exactly one code path from intent to execution, and a human
   click sits in the middle of it. This is what makes it safe to give ARIA
   increasing capability — and it is the property that most personal-assistant
   projects lack.
2. **It knows *him* specifically.** Not "an AI with memory" — a system whose
   every agent reads the same personal memory: his CV, his goals, his writing
   style, what he already understands as a programmer.
3. **It is his.** Self-hosted, own database, own machine, no third party
   holding his personal corpus.

## What the original project intended

Stated explicitly at project start:

> "Build an intelligent AI assistant that understands me, automates my work,
> and acts on my behalf **only when I explicitly authorize it**."

And, in his own closing recommendation:

> "Design it so it can read information and prepare drafts or actions, but
> require my approval before sending messages, submitting job applications, or
> performing other sensitive actions."

Development process was specified as: architecture first, then phases, one
phase at a time, each verified running with tests and documentation before the
next. **That process is itself part of the product vision** — he must
understand the system as it is built.

---

## What must never be removed

These are invariants. Changing any of them is a product change requiring
MORICE's explicit decision, not an engineering judgment call.

1. **No outward action without authorization.** Messages, applications, emails,
   posts, payments — all pass the Action Gateway. Autonomy may be *granted*
   per-category and per-contact, deliberately and visibly, but never assumed,
   never silently widened.
2. **The append-only audit log.** No code path may update or delete it.
3. **Never fabricate.** No invented qualifications on a CV, no invented
   citations, no claiming an action happened.
4. **Never overwrite the master CV.** Tailored copies only.
5. **Local-first personal data.** Embeddings and personal memory stay on his
   machine unless he explicitly opts a specific dataset into a cloud service.
6. **Secrets never in code, logs, or git.**
7. **Untrusted content is data, never instructions.** Messages, job posts,
   web pages, documents, tool output.
8. **The emergency stop must always work**, and autonomy level must always be
   visible.
9. **ARIA's identity.** The name, the personality, the assistant-not-chatbot
   posture.
10. **Explain-as-you-build.** Code stays commented and comprehensible to a
    beginner; docs describe reality.

## What can be improved

- Memory: from a flat store to typed memory with governance, scoring, decay,
  provenance, and automatic extraction.
- Models: from one active provider to a task-aware router preferring local
  models, escalating to cloud only when justified.
- Style: from retrieving style samples to a real observe→draft→compare→learn
  loop with confidence scores and per-contact profiles.
- Automation: from fully reactive to proactive (scheduled, configurable).
- Security: enable auth, add rate limiting, per-tool risk levels, backups.
- Testing: add frontend tests, WhatsApp simulation, autonomy readiness gates.
- Observability: persist cost and usage; surface activity.

## What can be added

WhatsApp as a first-class interface (via OpenClaw), contact model with trust
levels, autonomy modes with a readiness score, research agent, document
intelligence (PDF/Word/Excel), calendar, proactive engine, specialized agents
under an ARIA Core coordinator, Kiswahili support, voice.

---

## Non-goals

Stated to prevent drift:

- **ARIA is not a product for other users.** No multi-tenancy, no signup flow,
  no billing. Single user, forever.
- **ARIA is not OpenClaw, mem0, or Ollama.** Those are infrastructure ARIA may
  use. If one of them conflicts with ARIA's architecture, ARIA wins and the
  tradeoff gets documented.
- **ARIA is not a general chatbot.** If a feature would make her feel like a
  generic assistant, it is the wrong feature.
- **No platform-ToS-violating automation without informed consent.** WhatsApp
  automation is possible and MORICE may choose it, knowing the ban risk.
  LinkedIn/Indeed/Glassdoor scraping was assessed and declined.
- **No scale engineering.** One user. Do not add Kubernetes, microservices,
  sharding, or distributed anything to solve problems he does not have.
