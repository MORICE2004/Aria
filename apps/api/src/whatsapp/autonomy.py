"""Autonomy helpers — contact lookup and mode summaries.

The POLICY used to live here. It now lives in `decision.py`, which evaluates
the full signal set rather than the three inputs this module started with.
What remains here is the small stuff that is genuinely about autonomy but is
not policy: finding a contact, and describing the current mode in words.

The names below are re-exported so callers do not need to know that the policy
moved. There is still exactly ONE implementation — this module holds no copy
of it, because two implementations of a permission check is how a system ends
up enforcing the more permissive one by accident.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import AutonomyState, Contact
from src.whatsapp.decision import (  # noqa: F401 — re-exported public surface
    Decision,
    Mode,
    Outcome,
    TrustLevel,
    _TRUST_CEILING,
    effective_mode,
    evaluate,
    get_state,
    rank,
)

# Human-readable descriptions, shown wherever a mode is selectable so the
# choice is never made from the bare enum name.
MODE_DESCRIPTIONS: dict[Mode, str] = {
    Mode.OBSERVE: "ARIA reads and learns. She never responds.",
    Mode.SUGGEST: "ARIA drafts replies for you to send. She never sends.",
    Mode.SUPERVISED: "ARIA prepares each reply and asks you before sending.",
    Mode.LIMITED_AUTONOMY: (
        "ARIA automatically handles low-risk conversations with contacts you "
        "have explicitly enabled. Everything else is escalated to you."
    ),
    Mode.FULL_AUTONOMY: (
        "ARIA handles a broader range of conversations according to each "
        "contact's policy. High-risk messages still come to you."
    ),
}


def may_draft(mode: Mode) -> bool:
    """Can ARIA prepare a draft at all? False only in observe mode."""
    return rank(mode) >= rank(Mode.SUGGEST)


def may_send_with_approval(mode: Mode) -> bool:
    """Can an approved reply be sent (still via the Action Gateway)?"""
    return rank(mode) >= rank(Mode.SUPERVISED)


def may_send_automatically(mode: Mode) -> bool:
    """Could this MODE ever permit an unattended send?

    A ceiling check, not a permission. The actual question — may ARIA send
    THIS reply to THIS person right now — is `decision.evaluate`, which also
    weighs risk, contact policy, confidence and history. Never use this
    function to gate a send.
    """
    return rank(mode) >= rank(Mode.LIMITED_AUTONOMY)


async def resolve_for_contact(
    session: AsyncSession, contact: Contact
) -> tuple[Mode, str]:
    """Effective mode for a contact, plus a human-readable reason.

    The reason is shown in the dashboard so MORICE can always see *why* ARIA
    did or didn't act — an action explanation, not chain-of-thought.
    """
    state: AutonomyState = await get_state(session)
    global_mode = Mode(state.mode) if _known(state.mode) else Mode.OBSERVE
    trust = TrustLevel(contact.trust_level) if _known_trust(contact.trust_level) else TrustLevel.UNKNOWN
    mode = effective_mode(global_mode, trust, emergency_stop=state.emergency_stop)

    if state.emergency_stop:
        reason = "emergency stop is active - observe only"
    elif state.paused:
        reason = f"ARIA is paused (mode would be {mode.value})"
    elif contact.paused:
        reason = f"ARIA is paused for {contact.name}"
    elif contact.taken_over:
        reason = "you have taken over this conversation"
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


def _known(value: str) -> bool:
    return value in {m.value for m in Mode}


def _known_trust(value: str) -> bool:
    return value in {t.value for t in TrustLevel}
