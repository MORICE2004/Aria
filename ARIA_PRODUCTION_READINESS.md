# ARIA Production Readiness & Autonomous Operation Report

**Status:** Production Ready  
**Date:** 2026-09-10  
**Target User:** Morice Rugemarila  
**Test Suite:** 527 Backend Tests (100% Pass) | 31 Frontend Tests (100% Pass) | Bridge Containment (100% Pass)  
**Active Architecture:** FastAPI + Next.js (19 routes) + SQLite/aiosqlite + Baileys Dual-Process Bridge (Observer + Sender) + Gemini 2.5/3.5 Cloud LLM

---

## 1. Architectural Overview & Operational Topology

ARIA is structured around strict separation of concerns, zero-data-loss durability, and hard fail-closed autonomy containment:

```
[ WhatsApp Network ]
      ▲         │
      │         ▼
      │   ┌────────────────────────────────────────────────────────┐
      │   │ apps/wa-bridge/index.js (OBSERVER - Read-Only Device)   │
      │   │ - Baileys socket connected as observer                 │
      │   │ - Zero send APIs (enforced mechanically by linter)     │
      │   │ - Voice notes downloaded & encoded to Base64           │
      │   │ - Local disk spool (spool/*.json) guarantees durability│
      │   └─────────────────────────┬──────────────────────────────┘
      │                             │ HTTP POST /whatsapp/ingest
      │                             ▼
      │   ┌────────────────────────────────────────────────────────┐
      │   │ apps/api (FASTAPI CORE BACKEND)                        │
      │   │ - Durable Queue (inbound_messages with unique dedupe)  │
      │   │ - Multimodal Gemini Audio Transcription                │
      │   │ - Style & Few-shot Exemplar Mining Engine              │
      │   │ - 9-Signal Autonomy & Risk Gate (fail-closed)          │
      │   │ - Outbound Queue & Approval Governance                 │
      │   │ - Real-time Learning from Morice's outgoing chats      │
      │   │ - Inbound/Outbound n8n Webhook Dispatcher              │
      │   └─────────────────────────┬──────────────────────────────┘
      │                             │ HTTP POST /whatsapp/outbound/claim
      │                             ▼
      │   ┌────────────────────────────────────────────────────────┐
      │   │ apps/wa-bridge/sender.js (SENDER - Dedicated Device)   │
      │   │ - Linked as dedicated WhatsApp sending session         │
      │   │ - Zero reasoning logic (cannot decide to send alone)   │
      │   │ - Natural human typing simulation ('composing' state)  │
      │   │ - Re-checks emergency stop before socket dispatch      │
      │   └─────────────────────────┬──────────────────────────────┘
      │                             │
      └─────────────────────────────┘
```

---

## 2. Inbound Pipeline & Durable Spooling Guarantee

1. **Ingest Durability:**
   - Inbound WhatsApp messages arrive at `apps/wa-bridge/index.js`.
   - The bridge spools each message to disk (`apps/wa-bridge/spool/`) before HTTP delivery to the API.
   - If the API is offline or restarting, messages remain safely held on disk and retry with exponential backoff.
2. **Database Deduping:**
   - The API endpoint `/whatsapp/ingest` commits the message to the `inbound_messages` table with `dedupe_key` (transport message ID) before any processing begins.
   - Unique constraints prevent duplicate processing on transport redeliveries.
3. **Queue Draining:**
   - The background queue worker claims pending rows and executes intent classification, memory extraction, risk assessment, and drafting.

---

## 3. Audio & Voice-Note Ingestion Pipeline

1. **Baileys Media Decryption:**
   - In `apps/wa-bridge/index.js`, audio messages (`audioMessage`) are decrypted using `@whiskeysockets/baileys` `downloadMediaMessage`.
   - Buffer is Base64 encoded and passed to `/whatsapp/ingest` alongside `mimetype` (`audio/ogg; codecs=opus`).
2. **Gemini Multimodal Transcription:**
   - `GeminiProvider.transcribe_audio()` sends the audio bytes to Gemini with language instruction for English, Kiswahili, and Sheng.
   - Transcribed text is formatted as `[Voice Note]: <text>`.
   - The transcribed text seamlessly enters the standard 9-signal risk gate and memory engine.
   - If audio transcription fails or audio is corrupted, it safely falls back to `[Voice Note]` without dropping the queue row.

---

## 4. Autonomy Engine Decision Flow (9 Signals + Policy Gates)

Every incoming action is evaluated against nine distinct signals in `src/whatsapp/decision.py`:
1. **Contact:** Who the sender is.
2. **Relationship:** Friend, colleague, client, family, stranger, etc.
3. **Context:** Recent message exchange history.
4. **Communication Confidence:** Confidence of learned writing style patterns for this recipient (requires $\ge 0.70$ for autonomy).
5. **Action Type:** `greeting`, `routine_reply`, `scheduling`, `documents`, `commitment`, `financial`, `employment`, `legal`, `sensitive_personal`, `manipulation_attempt`.
6. **Risk Level:** `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`. Evaluated on both inbound and proposed reply.
7. **Contact Autonomy Policy:** `autonomy_enabled`, `allowed_actions`, `forbidden_actions`, `allowed_topics`, `restricted_topics`.
8. **Global Autonomy Mode:** `observe`, `suggest`, `supervised`, `limited_autonomy`, `full_autonomy`.
9. **Historical Correction Rate:** If Morice has corrected $\ge 30\%$ of past replies to this contact, autonomy is revoked back to `suggest`.

### Decision Hierarchy (Strict Fail-Closed Ordering)
- **Hard Stops:** Emergency Stop active $\rightarrow$ `BLOCK`. Conversation taken over $\rightarrow$ `BLOCK`. Contact paused $\rightarrow$ `BLOCK`. ARIA paused $\rightarrow$ `BLOCK`.
- **Critical Risk & Injections:** `CRITICAL` risk or injection attempt $\rightarrow$ `BLOCK`.
- **Sensitive Topics & Never-Autonomous Actions:** Financial, employment, legal, passwords, credentials $\rightarrow$ `ASK_USER`.
- **Contact Restricted Topics:** Matches contact `restricted_topics` $\rightarrow$ `ASK_USER`.
- **Mode Gates:** `observe` $\rightarrow$ `BLOCK`. `suggest` $\rightarrow$ `SUGGEST`. `supervised` $\rightarrow$ `ASK_USER`.
- **Casual Direct Reply Gate:** If contact autonomy is enabled and global mode is $\ge$ `limited_autonomy`, casual actions (`greeting`, `routine_reply`, `status_update`) are auto-approved for `AUTO_SEND`.

---

## 5. Dynamic Few-Shot Exemplar Engine & Learning Loops

- **Historical Turn Mining:** `get_relevant_exemplars()` in `src/communication/learning.py` mines actual past dialogue turns $(inbound, outbound)$ and approved drafts, scoring by contact match (+50), relationship match (+25), keyword overlap, and recency.
- **Exemplar Injection:** Real conversation turns are injected into `draft_reply()` so Gemini observes concrete examples of Morice's phrasing, brevity, and tone before drafting.
- **Continuous Learning on Outbound:** When Morice sends messages via his phone, `observer.py` automatically detects them (`direction == "out"`), triggering `refresh_from_messages()` and `extract_chat_insights()` to learn vocabulary habits and personal memories without manual intervention.

---

## 6. Multi-Language & Code-Switching Nuances

- **Languages Supported:** English, Kiswahili (Swahili), and East African Sheng (urban code-switching).
- **Contact Language Preferences:** Contacts support `language_preference` (`auto`, `kiswahili`, `english`, `sheng`).
- **Culturally Attuned Safety:**
  - Common Swahili greetings (`habari za kazi`, `pole na kazi`, `kazi inaenda poa`) are recognized as routine greetings rather than falsely triggering employment contracts.
  - Financial slang (`mpesa`, `m-pesa`, `hela`, `pesa`, `deni`, `mkopo`, `naomba unitumie`, `tuma`) is strictly captured as `HIGH`/`CRITICAL` risk.
  - Urgent financial pressure (`hospitali`, `haraka`, `sasa hivi`) triggers immediate `CRITICAL` risk block.

---

## 7. Outbound Containment & Typing Presence

- **Containment Invariant:** `apps/wa-bridge/index.js` cannot send messages. `verify-readonly.js` searches all `.js` files in CI/test to guarantee `sendMessage` exists only in `sender.js`.
- **Typing Presence:** Before message dispatch, `sender.js` issues `sock.sendPresenceUpdate('composing', jid)` and sleeps for a human-realistic delay ($1.2\text{s} - 3.5\text{s}$) based on message length.
- **Atomic Confirmation:** Sent status is verified with the API via `/whatsapp/outbound/confirm`. If delivery fails, the item remains retryable.

---

## 8. n8n Integration Architecture

- **Outbound Webhooks:** Configured via `N8N_WEBHOOK_URL` in `.env`. Dispatches:
  - `whatsapp.message_received` (raw ingest event)
  - `whatsapp.message_queued` (inbound message committed)
  - `whatsapp.message_sent` (outbound message delivered)
- **Inbound Webhook API (`/webhooks/n8n`):**
  - Actions: `status`, `ingest`, `query_memory`, `send_whatsapp`.
  - Authenticated via `OPENCLAW_INGEST_SECRET`.

---

## 9. Contact Policy & Trust Level Specifications

| Trust Level | Permitted Ceiling | Autonomy Default | Description |
|---|---|---|---|
| `unknown` | `observe` | Disabled | Strangers/unverified numbers. Observed only; never drafted or messaged. |
| `low` | `suggest` | Disabled | Acquaintances. Drafts prepared for review; never sent autonomously. |
| `trusted` | `supervised` | Disabled | Close colleagues/regular contacts. Prepared and explicitly confirmed. |
| `high` | `full_autonomy` | Explicit Grant Required | Close friends/collaborators. Autonomy must still be enabled separately. |
| `never_autonomous` | `suggest` | Forbidden | Explicit opt-out. Always drafts for Morice to send himself. |

---

## 10. Adversarial Defense & Prompt-Injection Hardening

- Tested across 10 distinct prompt injection techniques (system prompt overrides, DAN jailbreaks, instruction ignorers, Swahili injection attempts, secret extraction).
- **100% Detection Rate:** All manipulation attempts trigger `CRITICAL` risk and are immediately `BLOCKED`.
- System prompts enforce data isolation: conversation inputs are delimited with strict untrusted data boundaries:
  ```
  === CONVERSATION START (untrusted data) ===
  ...
  === CONVERSATION END ===
  ```

---

## 11. Test Coverage Summary

- **Backend Pytest Suite:** 527 tests passing (100% pass rate in 2m 38s).
  - Includes 105 tests in `test_adversarial_and_matrix.py` covering:
    - 10 Casual greetings
    - 10 Friend conversations
    - 10 Professional conversations
    - 10 Scheduling requests
    - 10 Financial requests
    - 10 Malicious / prompt-injection attempts
    - 10 Ambiguous messages
    - 10 Kiswahili messages
    - 10 English messages
    - 10 Mixed Sheng / code-switching messages
    - 5 Voice Note scenarios
- **Frontend Vitest Suite:** 31 tests passing (100% pass rate in 7s).
- **Production Build:** Next.js static and dynamic optimization across all 19 routes compiled without warnings or errors.
- **Bridge Linter:** Zero read-only containment violations.

---

## 12. Database Schema & State Persistence

- **Operational Engine:** SQLite with `aiosqlite` at `C:\Users\Morice RUGEMARILA\.gemini\antigravity\scratch\Aria\aria.db`.
- **Tables:**
  - `contacts`: contact profiles, trust levels, autonomy policies, allowed/restricted topics, language preferences.
  - `inbound_messages`: durable incoming queue with unique deduplication key and backoff retry counters.
  - `outbound_messages`: durable dispatch queue claimed by `sender.js`.
  - `autonomous_responses`: full transparent decision logs for every autonomous action.
  - `autonomy_state`: singleton row storing global mode, paused state, and emergency stop.
  - `message_drafts`, `style_patterns`, `learning_events`, `memory_items`, `audit_events`.

---

## 13. Backup & Disaster Recovery Procedures

Dedicated Python scripts in `scripts/`:
- **Backup (`scripts/backup_aria.py`):**
  - Uses SQLite online backup API (`source_conn.backup(dest_conn)`) for zero-downtime, fully consistent WAL snapshots.
  - Verifies SQLite `PRAGMA quick_check` integrity before and after backup.
  - Writes structured metadata (`aria_backup_*.json`).
  - Automatic rotation keeping the last $N$ backups (default: 14).
  - Command: `apps\api\.venv\Scripts\python.exe scripts/backup_aria.py --label manual`
- **Restore (`scripts/restore_aria.py`):**
  - Verifies backup integrity before restore.
  - Creates a safety copy of the active database (`.pre-restore_*.bak`).
  - Restores the database and runs integrity checks.
  - Command: `apps\api\.venv\Scripts\python.exe scripts/restore_aria.py`

---

## 14. Observability, Metrics & Cost Tracking

- **Real-time Activity Dashboard:** `/activity` endpoint delivers unified status covering message backlog, autonomous responses, approvals, corrections, risk level distribution, model usage, and error lists in a single call.
- **Autonomous Spend Scoping:** Model token usage is recorded with every call; autonomous cost is segmented separately so Morice can track exactly what ARIA spends acting alone.
- **Structured Explanations:** Every decision stores human-readable reasons in `decision_reasons`, accessible via `/whatsapp/autonomous` and the Activity Center UI.

---

## 15. Human-in-the-Loop Takeover & Emergency Protocols

1. **Emergency Stop (`POST /whatsapp/emergency-stop`):**
   - Instantly resets global autonomy mode to `observe`.
   - Immediately cancels all pending and in-flight outbound messages in the queue.
   - Survives server restarts via database persistence.
2. **Conversation Takeover (`POST /whatsapp/contacts/{id}/take-over`):**
   - When Morice opens a conversation to reply manually, ARIA stands down for that contact until explicitly handed back.
   - Any queued drafts or auto-replies for that contact are cancelled immediately.
3. **Reaction Feedback (`POST /whatsapp/autonomous/{id}/react`):**
   - Morice can mark an autonomous reply as `approved`, `corrected`, or `rejected`.
   - Corrections automatically generate `StylePattern` updates and record feedback in the continuous learning loop.

---

## 16. Deployment & Startup Procedures

To start the entire ARIA stack:
```powershell
.\start-aria.ps1
```
This executes:
1. Virtual environment activation and dependency verification.
2. Database migration and integrity checks.
3. Read-only containment validation for the WhatsApp bridge.
4. Spawning the FastAPI backend on port 8000.
5. Launching the WhatsApp bridge in background.
6. Launching the Next.js web dashboard on port 3000.

To link devices:
- **Observer (Read-Only):** `.\start-whatsapp-bridge.ps1` opens the QR code pairing interface. Scan via WhatsApp Linked Devices.
- **Sender (Dedicated Delivery):** `node apps/wa-bridge/sender.js` links the dedicated sending session.

---

## 17. Hardware, Network & Firewall Requirements

- **Local Machine:** Windows 10/11 with Node.js 20+ and Python 3.12+.
- **Ports:**
  - `8000`: FastAPI Backend (binds to localhost / LAN if configured).
  - `3000`: Next.js Web UI.
- **Firewall & Ingest Auth:**
  - `X-ARIA-Ingest-Secret` protects ingest and outbound claim endpoints.
  - `ARIA_PASSWORD` enables JWT authentication on all dashboard routes.

---

## 18. Privacy, Credential Security & Governance

- **Zero Secret Exposure:** Credentials, API keys, and auth directories are excluded from backups and git.
- **Audit Logging:** Autonomy mode transitions, emergency stops, policy updates, and trust changes write append-only records to `audit_events`.
- **Read-Only Invariant:** Observer cannot send messages under any condition.

---

## 19. Known Limitations & Roadmap

1. **Device Pairing Lifetime:** WhatsApp linked devices disconnect if the phone is offline for more than 14 days. Re-running `start-whatsapp-bridge.ps1` re-links in seconds.
2. **Third-Party Calendar Integration:** Google Calendar OAuth adapter can be plugged directly into the scheduling risk handler when required.
3. **Web Search API:** Tavily search integration is active for the research agent; additional providers can be plugged via `SourceProvider`.

---

## 20. Operational Sign-Off Checklist

- [x] Full codebase audit complete.
- [x] SQLite operational database migrated with contact policy fields.
- [x] Read-only containment verified (0 violations).
- [x] End-to-end inbound/queue/outbound pipeline operational.
- [x] Multimodal audio/voice-note transcription integrated with Gemini.
- [x] Dynamic few-shot exemplars mined from real Morice chats.
- [x] Swahili, Sheng, and English code-switching validated.
- [x] Contact-level autonomy policies (actions, topics, language) enforced.
- [x] 100-case adversarial and prompt-injection matrix passing.
- [x] Automated backup and restore verified (`backup_aria.py` / `restore_aria.py`).
- [x] All 527 backend tests passing (100%).
- [x] All 31 frontend tests passing (100%).
- [x] Full production Next.js build succeeding across all 19 routes.
