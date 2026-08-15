"""Autonomy resolution — what ARIA is allowed to do, for whom, right now.

Three inputs decide every question of permission:

  1. The GLOBAL MODE      — how much autonomy MORICE has granted overall.
  2. The CONTACT TRUST    — a per-person ceiling, independent of the global mode.
  3. The EMERGENCY STOP   — overrides everything to OBSERVE.

The effective permission is always the **most restrictive** of these. Raising
the global mode can never widen what ARIA may do for an untrusted contact,
and no setting survives the kill switch.

This module is the single source of truth for that question. Nothing else in
the codebase may decide "am I allowed to send" on its own.
"""

from __future__ import annotations

from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import AutonomyState, Contact


class Mode(str, Enum):
    """Autonomy modes, ordered least to most permissive."""

    OBSERVE = "observe"          # watch and learn; never respond
    SUGGEST = "suggest"          # prepare drafts for review
    SUPERVISED = "supervised"    # may send after explicit confirmation
    TRUSTED = "trusted"          # may auto-handle defined low-risk messages
    AUTONOMOUS = "autonomous"    # broad autonomy (requires readiness evidence)


class TrustLevel(str, Enum):
    NEVER_AUTONOMOUS = "never_autonomous"
    UNKNOWN = "unknown"
    LOW = "low"
    TRUSTED = "trusted"
    HIGH = "high"


# Permissiveness ranking. Index = how much freedom the mode grants.
_MODE_RANK: list[Mode] = [
    Mode.OBSERVE,
    Mode.SUGGEST,
    Mode.SUPERVISED,
    Mode.TRUSTED,
    Mode.AUTONOMOUS,
]

# The highest mode each trust level permits, whatever the global mode says.
_TRUST_CEILING: dict[TrustLevel, Mode] = {
    # An unknown contact is only ever observed — ARIA does not draft for
    # strangers, because a stranger is also the likeliest injection vector.
    TrustLevel.UNKNOWN: Mode.OBSERVE,
    TrustLevel.LOW: Mode.SUGGEST,
    TrustLevel.TRUSTED: Mode.SUPERVISED,
    TrustLevel.HIGH: Mode.TRUSTED,
    # Explicit opt-out: drafts are fine, autonomy never is.
    TrustLevel.NEVER_AUTONOMOUS: Mode.SUGGEST,
}


def _rank(mode: Mode) -> int:
    return _MODE_RANK.index(mode)


def effective_mode(global_mode: Mode, trust: TrustLevel, *, emergency_stop: bool) -> Mode:
    """The mode that actually applies for one contact.

    Pure function — no I/O — so the policy is trivially testable, which
    matters more here than anywhere else in ARIA.
    """
    if emergency_stop:
        return Mode.OBSERVE
    ceiling = _TRUST_CEILING[trust]
    return global_mode if _rank(global_mode) <= _rank(ceiling) else ceiling


def may_draft(mode: Mode) -> bool:
    """Can ARIA prepare a draft for MORICE to read?"""
    return _rank(mode) >= _rank(Mode.SUGGEST)


def may_send_with_approval(mode: Mode) -> bool:
    """Can an approved draft be sent (still via the Action Gateway)?"""
    return _rank(mode) >= _rank(Mode.SUPERVISED)


def may_send_automatically(mode: Mode) -> bool:
    """Can ARIA send a low-risk reply without a per-message click?

    Even when true, the message still passes the Action Gateway and is
    audited — 'automatic' means pre-authorised, never unlogged.
    """
    return _rank(mode) >= _rank(Mode.TRUSTED)


async def get_state(session: AsyncSession) -> AutonomyState:
    """Load the singleton autonomy row, creating it in OBSERVE if absent.

    Defaulting to OBSERVE means a fresh install, or a wiped database, can
    never come up in a sending mode.
    """
    state = await session.get(AutonomyState, "singleton")
    if state is None:
        state = AutonomyState(id="singleton", mode=Mode.OBSERVE.value)
        session.add(state)
        await session.commit()
    return state


async def resolve_for_contact(
    session: AsyncSession, contact: Contact
) -> tuple[Mode, str]:
    """Effective mode for a contact, plus a human-readable reason.

    The reason is shown in the dashboard so MORICE can always see *why*
    ARIA did or didn't act — an action explanation, not chain-of-thought.
    """
    state = await get_state(session)
    global_mode = Mode(state.mode)
    trust = TrustLevel(contact.trust_level)
    mode = effective_mode(global_mode, trust, emergency_stop=state.emergency_stop)

    if state.emergency_stop:
        reason = "emergency stop is active — observe only"
    elif mode is not global_mode:
        reason = (
            f"limited to {mode.value} by contact trust '{trust.value}' "
            f"(global mode is {global_mode.value})"
        )
    else:
        reason = f"global mode {global_mode.value}, contact trust '{trust.value}'"
    return mode, reason


async def find_contact(
    session: AsyncSession, handle: str, channel: str = "whatsapp"
) -> Contact | None:
    result = await session.execute(
        select(Contact).where(Contact.handle == handle, Contact.channel == channel)
    )
    return result.scalar_one_or_none()
