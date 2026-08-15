# ARIA — Autonomy Model

Status: **implemented and verified** 2026-08-16 (Phase 8).

The rule ARIA is built around: *she drafts, you decide.* Autonomy is
something MORICE grants deliberately, in visible increments, and can revoke
instantly.

## The five modes

| Mode | ARIA may |
|---|---|
| `observe` | Watch and learn. **Never respond.** |
| `suggest` | Prepare drafts for review. |
| `supervised` | Send, but only after explicit per-message confirmation. |
| `trusted` | Auto-handle defined low-risk messages (still audited). |
| `autonomous` | Broad autonomy. Requires readiness evidence (not yet built). |

Default on a fresh install — or a wiped database — is `observe`. A system that
loses its state can never come back up able to send.

## Three inputs decide every permission

1. **Global mode** — how much autonomy is granted overall.
2. **Contact trust** — a per-person ceiling, independent of the global mode.
3. **Emergency stop** — overrides everything.

The effective permission is always the **most restrictive** of these.

```
effective_mode = emergency_stop ? OBSERVE
                                : min(global_mode, trust_ceiling[contact])
```

### Trust ceilings

| Trust level | Highest mode allowed |
|---|---|
| `unknown` | `observe` |
| `low` | `suggest` |
| `trusted` | `supervised` |
| `high` | `trusted` |
| `never_autonomous` | `suggest` (drafts fine, autonomy never) |

**New contacts always start `unknown`**, so a stranger is observed and nothing
more. Trust is granted by MORICE; it is never inferred from message content —
which is exactly what stops a message from talking its way into permissions.

Verified: with the global mode set to `autonomous`, an unknown contact still
resolves to `observe`.

## The emergency stop

- Forces mode to `observe` immediately.
- Blocks raising the mode while active (HTTP 409).
- **Stored in the database, not memory** — it survives a restart. Verified
  live: the stop set before an API restart was still active afterwards.
- Reachable from the dashboard as a single red button, and at
  `POST /whatsapp/emergency-stop`.

## Everything is audited

Autonomy and trust changes both write to the existing append-only audit log
(`autonomy_changed`, `trust_changed`), including when MORICE makes them
himself. Autonomy must never change silently — that includes not changing
silently *for him*.

## Where the policy lives

`src/whatsapp/autonomy.py`. `effective_mode()` is a **pure function** — no
database, no I/O — so the policy is exhaustively testable. The test suite
asserts that no combination of mode and trust escapes the kill switch.

Nothing else in the codebase may decide "am I allowed to send." Sending, when
it eventually exists, still goes through the Action Gateway on top of this.

## Not yet built

- **Autonomy readiness score** (§48) — evidence-gated escalation. Until it
  exists, `trusted` and `autonomous` are selectable but no code sends anyway.
- **Action-risk classifier** (§19) for low/medium/high/critical routing.
- Sensitive-category enforcement: messages *are* classified for sensitivity
  (financial, legal, commitment, …) but nothing consumes that signal yet,
  because nothing can send.
