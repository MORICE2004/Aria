# Spec: Autonomous Job Application Agent (future phases 8+)

Status: ACCEPTED as future roadmap, 2026-07-09. Not yet scheduled.
Origin: MORICE's full spec (job discovery → tailoring → browser automation →
human approval gateway → submission). Preserved here so nothing is lost;
build it incrementally, one slice per phase, each verified before the next.

## Scope adjustments agreed

- **No LinkedIn / Indeed / Glassdoor scraping or Easy Apply automation.**
  Violates their ToS; high account-ban risk (same reasoning as WhatsApp
  paste-in-only). Job discovery uses: Greenhouse/Lever/Ashby/SmartRecruiters
  public job boards + company career pages + jobs MORICE pastes in manually.
- Everything else stands, including: dedupe, threshold scoring, master-CV
  tailoring (never fabricate, never overwrite the original), ATS-optimized
  wording, per-ATS Playwright form filling, CAPTCHA = always pause and
  notify (never bypass), screenshot previews, Edit/Reject/Accept&Submit
  approval flow, confirmation capture, full audit logging.

## How it maps onto the existing architecture (no redesign needed)

| Spec element | Existing ARIA component |
|---|---|
| "Pause before final Submit" | Action Gateway (`application.submit` becomes a new action type) |
| Approval dashboard w/ preview | Approvals page, extended with screenshot + document panels |
| Edit loop | New pending-action state: reject-with-changes resubmits a fresh request |
| Per-ATS form filling | One Playwright executor per ATS, registered via `@register_executor` |
| Never fabricate / never overwrite CV | jobsearch agent prompts (already enforced) + master CV stored read-only in memory |
| Dedupe / threshold / prioritize | jobsearch service functions over JobApplication table |
| Metrics dashboard | New `/jobs/stats` endpoint + dashboard cards |
| Notifications | Phase 6 tasks/reminders system |

## Suggested build order (one phase each)

1. Job ingestion: Greenhouse/Lever/Ashby public APIs + dedupe + auto-scoring
   against threshold; "new jobs today" feed.
2. Document pipeline: master CV in memory (read-only original), tailored CV +
   cover letter generation and versioned storage per application.
3. Browser automation MVP: Playwright, ONE ATS (Greenhouse), fill + screenshot
   + pause at submit via gateway; Edit/Reject/Approve flow on Approvals page.
4. More ATSs (Lever, Ashby, SmartRecruiters), error recovery (LLM re-identifies
   changed fields), CAPTCHA pause-and-notify.
5. Stats dashboard + notifications + response-rate tracking.

## Hard safety invariants (restate in every implementing phase)

- Submission happens ONLY through the gateway's approve path. No exceptions.
- Never fabricate degrees, skills, certifications, employment history, dates.
- The master CV file/memory is never modified — tailored copies only.
- No duplicate applications (dedupe by company+role+posting URL).
- CAPTCHAs and logins: pause and hand to the human. Never bypass.
- Every step audited (existing append-only AuditEvent table).
