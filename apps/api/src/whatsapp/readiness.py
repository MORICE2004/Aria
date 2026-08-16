"""Autonomy readiness — evidence that ARIA *could* handle a contact alone.

Emphatically not a permission. Nothing in this codebase reads the score and
enables anything; it exists so MORICE can look at a contact and see whether
ARIA has actually earned more freedom there, instead of guessing.

The reason it is advisory is not caution for its own sake. A score high enough
to auto-promote would be a score worth gaming, and the thing gaming it would be
ARIA's own learning system — the one that decides what counts as evidence. A
system that can promote itself by generating its own evidence has no meaningful
supervision. So the score informs, and MORICE decides.

Seven factors, each 0–1, combined with weights that sum to 1:

    communication confidence   does she sound like him, for this person
    evidence volume            how many of his real messages she has seen
    correction history         how often he has had to fix her
    context confidence         how much of this conversation she has
    contact trust              what he has said about this person
    error rate                 how often processing has failed for them
    risk profile               how sensitive their conversations tend to be
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import (
    AutonomousResponse,
    Contact,
    InboundMessage,
    WhatsAppMessage,
)
from src.whatsapp import decision as decision_module
from src.whatsapp import risk as risk_module
from src.whatsapp.decision import TrustLevel

# Enough observed messages that a style profile is a measurement rather than
# an impression. Matches the confidence curve in communication/learning.py.
EVIDENCE_TARGET = 30

_WEIGHTS = {
    "communication_confidence": 0.25,
    "evidence_volume": 0.20,
    "correction_history": 0.20,
    "context_confidence": 0.10,
    "contact_trust": 0.10,
    "error_rate": 0.05,
    "risk_profile": 0.10,
}

_TRUST_SCORE = {
    TrustLevel.NEVER_AUTONOMOUS: 0.0,
    TrustLevel.UNKNOWN: 0.0,
    TrustLevel.LOW: 0.25,
    TrustLevel.TRUSTED: 0.6,
    TrustLevel.HIGH: 1.0,
}


@dataclass(frozen=True)
class Readiness:
    contact_id: str
    contact_name: str
    score: float
    factors: dict[str, float] = field(default_factory=dict)
    # Plain-English notes on what is holding the score down, so the number is
    # actionable rather than merely discouraging.
    notes: list[str] = field(default_factory=list)
    # What MORICE would still need to do. Never done automatically.
    blocking: list[str] = field(default_factory=list)


async def score_contact(session: AsyncSession, contact: Contact) -> Readiness:
    factors: dict[str, float] = {}
    notes: list[str] = []
    blocking: list[str] = []

    # 1. Does ARIA sound like MORICE for this person?
    confidence = await decision_module.communication_confidence(session, contact)
    factors["communication_confidence"] = confidence
    if confidence < decision_module.MIN_CONFIDENCE_FOR_AUTONOMY:
        notes.append(
            f"style confidence {confidence:.2f} is below the "
            f"{decision_module.MIN_CONFIDENCE_FOR_AUTONOMY:.2f} needed to send unwatched"
        )

    # 2. How much of his own writing has she actually seen?
    written_by_morice = (
        await session.execute(
            select(func.count(WhatsAppMessage.id)).where(
                WhatsAppMessage.direction == "out"
            )
        )
    ).scalar_one() or 0
    factors["evidence_volume"] = min(written_by_morice / EVIDENCE_TARGET, 1.0)
    if written_by_morice < EVIDENCE_TARGET:
        notes.append(
            f"learned from {written_by_morice} of MORICE's messages "
            f"(target {EVIDENCE_TARGET})"
        )

    # 3. How often has he had to correct her here?
    reactions, correction_rate = await decision_module.correction_history(
        session, contact.id
    )
    if reactions == 0:
        # No feedback is not good news. It is the absence of evidence, and it
        # scores as such rather than as a clean record.
        factors["correction_history"] = 0.3
        notes.append("no feedback yet on autonomous replies to this contact")
    else:
        factors["correction_history"] = max(0.0, 1.0 - correction_rate)
        if correction_rate > 0:
            notes.append(
                f"MORICE corrected {correction_rate:.0%} of "
                f"{reactions} reviewed replies"
            )

    # 4. How much of this conversation does she have?
    history = (
        await session.execute(
            select(func.count(WhatsAppMessage.id)).where(
                WhatsAppMessage.contact_id == contact.id
            )
        )
    ).scalar_one() or 0
    factors["context_confidence"] = min(history / 20, 1.0)
    if history < 10:
        notes.append(f"only {history} messages of history with this contact")

    # 5. What has MORICE said about this person?
    trust = decision_module._trust_or_unknown(contact.trust_level)
    factors["contact_trust"] = _TRUST_SCORE[trust]
    if trust in (TrustLevel.UNKNOWN, TrustLevel.NEVER_AUTONOMOUS):
        blocking.append(
            f"trust level is '{trust.value}' — autonomy is impossible until "
            "MORICE raises it"
        )

    # 6. Has processing been reliable for this contact?
    total_queued = (
        await session.execute(
            select(func.count(InboundMessage.id)).where(
                InboundMessage.handle == contact.handle
            )
        )
    ).scalar_one() or 0
    failed = (
        await session.execute(
            select(func.count(InboundMessage.id)).where(
                InboundMessage.handle == contact.handle,
                InboundMessage.status == "dead",
            )
        )
    ).scalar_one() or 0
    error_rate = (failed / total_queued) if total_queued else 0.0
    factors["error_rate"] = max(0.0, 1.0 - error_rate * 5)  # 20% failure => 0
    if failed:
        notes.append(f"{failed} message(s) from this contact failed processing")

    # 7. How sensitive are their conversations, typically?
    factors["risk_profile"] = await _risk_profile(session, contact)
    if factors["risk_profile"] < 0.5:
        notes.append("conversations with this contact often touch sensitive topics")

    if not contact.autonomy_enabled:
        blocking.append(
            "autonomy is not enabled for this contact — MORICE must turn it on "
            "explicitly; a high score never does it for him"
        )

    score = round(sum(factors[k] * w for k, w in _WEIGHTS.items()), 3)
    return Readiness(
        contact_id=contact.id,
        contact_name=contact.name,
        score=score,
        factors={k: round(v, 3) for k, v in factors.items()},
        notes=notes,
        blocking=blocking,
    )


async def _risk_profile(session: AsyncSession, contact: Contact) -> float:
    """1.0 when this contact's messages are routine; lower when they are not.

    Measured from real history rather than assumed from the relationship type:
    a "friend" who mostly discusses money should not score as low risk because
    of the label on the relationship.
    """
    rows = (
        await session.execute(
            select(WhatsAppMessage.body)
            .where(
                WhatsAppMessage.contact_id == contact.id,
                WhatsAppMessage.direction == "in",
            )
            .order_by(WhatsAppMessage.sent_at.desc())
            .limit(50)
        )
    ).scalars()

    bodies = list(rows)
    if not bodies:
        return 0.5  # unknown, so neither credited nor penalised

    sensitive = sum(
        1
        for body in bodies
        if risk_module.classify_incoming(
            body, relationship=contact.relationship
        ).level
        in (risk_module.RiskLevel.HIGH, risk_module.RiskLevel.CRITICAL)
    )
    return round(1.0 - sensitive / len(bodies), 3)


async def score_all(session: AsyncSession) -> list[Readiness]:
    contacts = (
        await session.execute(select(Contact).order_by(Contact.created_at))
    ).scalars()
    return [await score_contact(session, c) for c in contacts]
