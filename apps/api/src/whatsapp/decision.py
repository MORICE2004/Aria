"""The autonomy engine — one place that answers "may ARIA do this?".

Every potential external action is evaluated here, against nine signals:

    contact                who it is
    relationship           what they are to MORICE
    context                the conversation and its history
    communication confidence   how well ARIA has learned to write as him
    action type            what kind of thing this is
    risk                   what it could cost if wrong
    user permissions       what MORICE explicitly allowed for this contact
    autonomy mode          how much freedom is granted globally
    historical performance how often ARIA has been corrected here before

and returns one of four outcomes:

    AUTO_SEND   handle it, log it, tell MORICE afterwards
    SUGGEST     draft it, wait for him to use it
    ASK_USER    prepare it and explicitly request approval
    BLOCK       do not act; surface it

Not a trusted/untrusted boolean. The reason a boolean is wrong is that the
same person is safe for some things and not others: MORICE's closest friend
asking "saa ngapi?" and the same friend asking for a loan are not the same
decision, and no amount of trust in the person should collapse them.

**Fail closed, in order.** The engine evaluates blocks first, then permissions,
then capability. Anything unrecognised, missing, or contradictory produces a
more restrictive answer, never a more permissive one. A bug here should cost a
missed auto-reply, never an unwanted sent message.

**Every decision carries its reasons.** A decision MORICE cannot interrogate is
not one he can supervise, and supervision is the entire point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import AutonomousResponse, AutonomyState, Contact
from src.whatsapp import risk as risk_module
from src.whatsapp.risk import RiskAssessment, RiskLevel


class Mode(str, Enum):
    """Autonomy levels, ordered least to most permissive.

    Promotion is never automatic. Nothing in this codebase writes a higher
    mode than the one MORICE set; the readiness score is information for him,
    not an input to a decision about his own permissions.
    """

    OBSERVE = "observe"                      # read and learn; never respond
    SUGGEST = "suggest"                      # draft, but never send
    SUPERVISED = "supervised"                # prepare and ask every time
    LIMITED_AUTONOMY = "limited_autonomy"    # auto-handle explicitly permitted low-risk
    FULL_AUTONOMY = "full_autonomy"          # broader autonomy, per policy


class Decision(str, Enum):
    AUTO_SEND = "auto_send"
    SUGGEST = "suggest"
    ASK_USER = "ask_user"
    BLOCK = "block"


class TrustLevel(str, Enum):
    NEVER_AUTONOMOUS = "never_autonomous"
    UNKNOWN = "unknown"
    LOW = "low"
    TRUSTED = "trusted"
    HIGH = "high"


_MODE_RANK: list[Mode] = [
    Mode.OBSERVE,
    Mode.SUGGEST,
    Mode.SUPERVISED,
    Mode.LIMITED_AUTONOMY,
    Mode.FULL_AUTONOMY,
]

# The highest mode each trust level permits, whatever the global mode says.
_TRUST_CEILING: dict[TrustLevel, Mode] = {
    # A stranger is observed and nothing more. ARIA does not draft for people
    # she does not know, because an unknown number is also the likeliest
    # hostile sender.
    TrustLevel.UNKNOWN: Mode.OBSERVE,
    TrustLevel.LOW: Mode.SUGGEST,
    TrustLevel.TRUSTED: Mode.SUPERVISED,
    TrustLevel.HIGH: Mode.LIMITED_AUTONOMY,
    # Explicit opt-out: drafting is fine, autonomy never is, at any trust or
    # mode. This is the setting for someone MORICE will always answer himself.
    TrustLevel.NEVER_AUTONOMOUS: Mode.SUGGEST,
}

# Below this, ARIA does not sound enough like MORICE to speak as him unwatched.
# Set against the learning curve in communication/learning.py: 0.70 needs
# roughly 19 observed messages, so it cannot be reached by accident.
MIN_CONFIDENCE_FOR_AUTONOMY = 0.70

# If ARIA has been corrected this often for a contact, she has not earned
# autonomy there, whatever the global settings say.
MAX_CORRECTION_RATE = 0.30

# Corrections only mean something once there are enough of them to be a rate
# rather than an accident.
MIN_RESPONSES_FOR_RATE = 4


def rank(mode: Mode) -> int:
    return _MODE_RANK.index(mode)


@dataclass(frozen=True)
class Signals:
    """Everything the engine looks at. Assembled by `evaluate`, and exposed so
    the dashboard can show the same inputs MORICE's assistant reasoned from."""

    contact_name: str
    relationship: str
    trust: TrustLevel
    global_mode: Mode
    effective_mode: Mode
    action: str
    risk: RiskAssessment
    communication_confidence: float
    correction_rate: float
    autonomous_responses: int
    contact_autonomy_enabled: bool
    allowed_actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    emergency_stop: bool
    paused: bool
    autonomy_stopped: bool
    contact_paused: bool
    taken_over: bool


@dataclass(frozen=True)
class Outcome:
    decision: Decision
    # Ordered most-important-first; the first entry is the deciding factor.
    reasons: list[str] = field(default_factory=list)
    signals: Signals | None = None

    @property
    def may_send_automatically(self) -> bool:
        return self.decision is Decision.AUTO_SEND

    @property
    def may_draft(self) -> bool:
        """Drafting is allowed for everything except an outright block."""
        return self.decision is not Decision.BLOCK

    def explain(self) -> str:
        return "; ".join(self.reasons)


def effective_mode(
    global_mode: Mode, trust: TrustLevel, *, emergency_stop: bool
) -> Mode:
    """The mode that actually applies for one contact.

    Pure function — no I/O — so the policy is exhaustively testable, which
    matters more here than anywhere else in ARIA.
    """
    if emergency_stop:
        return Mode.OBSERVE
    ceiling = _TRUST_CEILING[trust]
    return global_mode if rank(global_mode) <= rank(ceiling) else ceiling


def decide(signals: Signals) -> Outcome:
    """The policy, as a pure function of the signals.

    Read top to bottom: the first matching rule wins, and the rules are
    ordered from "stop everything" to "go ahead". That ordering is the safety
    property — every early return is more restrictive than every later one, so
    a rule accidentally added in the wrong place can only tighten behaviour.
    """
    reasons: list[str] = []

    def out(decision: Decision, reason: str) -> Outcome:
        return Outcome(decision, [reason, *reasons], signals)

    # --- 1. Hard stops. Nothing below matters if one of these is set. ---

    if signals.emergency_stop:
        return out(Decision.BLOCK, "emergency stop is active")

    if signals.taken_over:
        return out(
            Decision.BLOCK,
            f"MORICE has taken over the conversation with {signals.contact_name}",
        )

    if signals.contact_paused:
        return out(Decision.BLOCK, f"ARIA is paused for {signals.contact_name}")

    if signals.paused:
        return out(Decision.BLOCK, "ARIA is paused")

    # --- 2. Risk that no mode can override. ---

    if signals.risk.level is RiskLevel.CRITICAL:
        return out(
            Decision.BLOCK,
            f"critical risk: {signals.risk.reasons[0] if signals.risk.reasons else 'unsafe'}",
        )

    if signals.action == "manipulation_attempt" or signals.risk.injection_suspected:
        # Handled above via CRITICAL in practice; kept as an independent rule so
        # a change to the risk table can never silently un-block this case.
        return out(
            Decision.BLOCK,
            "the message tries to instruct ARIA rather than talk to MORICE",
        )

    if signals.action in risk_module.NEVER_AUTONOMOUS_ACTIONS:
        return out(
            Decision.ASK_USER,
            f"'{signals.action}' is never handled autonomously — asking MORICE",
        )

    if signals.action in signals.forbidden_actions:
        return out(
            Decision.ASK_USER,
            f"MORICE forbade autonomous '{signals.action}' for "
            f"{signals.contact_name}",
        )

    # --- 3. Mode gates. ---

    mode = signals.effective_mode

    if mode is Mode.OBSERVE:
        return out(
            Decision.BLOCK,
            f"observe mode for {signals.contact_name} "
            f"(trust '{signals.trust.value}')",
        )

    if signals.risk.level is RiskLevel.HIGH:
        return out(
            Decision.ASK_USER,
            f"high risk: {signals.risk.reasons[0] if signals.risk.reasons else 'sensitive'}",
        )

    if mode is Mode.SUGGEST:
        return out(Decision.SUGGEST, "suggest mode — ARIA drafts, MORICE sends")

    if mode is Mode.SUPERVISED:
        return out(Decision.ASK_USER, "supervised mode — every message is confirmed")

    # --- 4. Autonomy. Everything from here needs the explicit grant. ---

    if signals.autonomy_stopped:
        return out(
            Decision.ASK_USER,
            "autonomous sending is stopped — ARIA will prepare and ask",
        )

    if not signals.contact_autonomy_enabled:
        return out(
            Decision.ASK_USER,
            f"autonomy is not enabled for {signals.contact_name} "
            "(trust alone is not permission)",
        )

    if signals.action not in signals.allowed_actions:
        return out(
            Decision.ASK_USER,
            f"'{signals.action}' is not in the actions MORICE allowed for "
            f"{signals.contact_name}",
        )

    if signals.communication_confidence < MIN_CONFIDENCE_FOR_AUTONOMY:
        return out(
            Decision.SUGGEST,
            f"ARIA does not yet write enough like MORICE to send unwatched "
            f"(confidence {signals.communication_confidence:.2f} < "
            f"{MIN_CONFIDENCE_FOR_AUTONOMY:.2f})",
        )

    if (
        signals.autonomous_responses >= MIN_RESPONSES_FOR_RATE
        and signals.correction_rate > MAX_CORRECTION_RATE
    ):
        return out(
            Decision.SUGGEST,
            f"MORICE has corrected {signals.correction_rate:.0%} of ARIA's "
            f"replies to {signals.contact_name} — not yet reliable enough",
        )

    if signals.risk.level is RiskLevel.MEDIUM:
        if mode is not Mode.FULL_AUTONOMY:
            return out(
                Decision.ASK_USER,
                f"medium risk under limited autonomy: "
                f"{signals.risk.reasons[0] if signals.risk.reasons else 'needs care'}",
            )
        return out(
            Decision.AUTO_SEND,
            f"full autonomy, medium risk permitted for {signals.contact_name}",
        )

    return out(
        Decision.AUTO_SEND,
        f"low risk '{signals.action}' for {signals.contact_name}, "
        f"explicitly permitted, confidence {signals.communication_confidence:.2f}",
    )


# --- Assembling the signals from the database ----------------------------

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


async def correction_history(
    session: AsyncSession, contact_id: str
) -> tuple[int, float]:
    """How often MORICE has corrected ARIA's autonomous replies to this contact.

    Only explicit reactions count. A response he never reacted to is not
    evidence of anything, and is excluded from the denominator rather than
    counted as a success — otherwise ARIA would grow more confident the less
    attention he paid, which is exactly backwards.
    """
    rows = (
        await session.execute(
            select(
                AutonomousResponse.user_reaction, func.count(AutonomousResponse.id)
            )
            .where(
                AutonomousResponse.contact_id == contact_id,
                AutonomousResponse.user_reaction != "none",
            )
            .group_by(AutonomousResponse.user_reaction)
        )
    ).all()

    counts = {reaction: count for reaction, count in rows}
    total = sum(counts.values())
    if total == 0:
        return 0, 0.0
    bad = counts.get("corrected", 0) + counts.get("rejected", 0)
    return total, round(bad / total, 3)


async def communication_confidence(
    session: AsyncSession, contact: Contact
) -> float:
    """How well ARIA has learned to write as MORICE, for this contact.

    Uses the mean confidence of the style patterns that would actually shape
    the reply — the same patterns the drafting prompt is built from. Measuring
    anything else would let ARIA claim confidence she does not use.
    """
    from src.communication import learning as comm_learning
    from src.models import StylePattern

    scopes = ["global"]
    if contact.relationship and contact.relationship != "unknown":
        scopes.append(f"relationship:{contact.relationship}")
    scopes.append(f"contact:{contact.id}")

    rows = (
        await session.execute(
            select(StylePattern).where(StylePattern.scope.in_(scopes))
        )
    ).scalars()

    usable = [
        p.confidence
        for p in rows
        if p.confidence >= comm_learning._USABLE_CONFIDENCE
    ]
    if not usable:
        return 0.0
    return round(sum(usable) / len(usable), 3)


async def evaluate(
    session: AsyncSession,
    contact: Contact,
    *,
    incoming: str,
    proposed_reply: str | None = None,
) -> Outcome:
    """Gather every signal and decide. The single entry point for permission.

    Nothing else in the codebase may decide "am I allowed to send". Callers
    ask this function and obey the answer.
    """
    state = await get_state(session)
    global_mode = _mode_or_observe(state.mode)
    trust = _trust_or_unknown(contact.trust_level)

    assessment = risk_module.classify_exchange(
        incoming, proposed_reply, relationship=contact.relationship
    )
    action = risk_module.action_type(incoming)
    # If the proposed reply is riskier than the message, judge by the reply.
    if proposed_reply:
        reply_action = risk_module.action_type(proposed_reply)
        if reply_action in risk_module.NEVER_AUTONOMOUS_ACTIONS:
            action = reply_action

    responses, correction_rate = await correction_history(session, contact.id)
    confidence = await communication_confidence(session, contact)

    allowed = tuple(contact.allowed_actions or risk_module.DEFAULT_ALLOWED_ACTIONS)
    forbidden = tuple(contact.forbidden_actions or ())

    signals = Signals(
        contact_name=contact.name,
        relationship=contact.relationship,
        trust=trust,
        global_mode=global_mode,
        effective_mode=effective_mode(
            global_mode, trust, emergency_stop=state.emergency_stop
        ),
        action=action,
        risk=assessment,
        communication_confidence=confidence,
        correction_rate=correction_rate,
        autonomous_responses=responses,
        contact_autonomy_enabled=contact.autonomy_enabled,
        allowed_actions=allowed,
        forbidden_actions=forbidden,
        emergency_stop=state.emergency_stop,
        paused=state.paused,
        autonomy_stopped=state.autonomy_stopped,
        contact_paused=contact.paused,
        taken_over=contact.taken_over,
    )
    return decide(signals)


# Modes 8/9 used before the five-level model. Mapped rather than silently
# dropped so an existing database keeps the meaning MORICE chose, while an
# unrecognised value still fails closed below.
_LEGACY_MODES = {
    "trusted": Mode.LIMITED_AUTONOMY,
    "autonomous": Mode.FULL_AUTONOMY,
}


def _mode_or_observe(value: str) -> Mode:
    """Unrecognised mode means OBSERVE, not a crash and not a guess.

    Protects against a database row written by an older schema, or by hand.
    Failing closed here is the difference between a confusing log line and an
    unwanted message.
    """
    try:
        return Mode(value)
    except ValueError:
        return _LEGACY_MODES.get(value, Mode.OBSERVE)


def _trust_or_unknown(value: str) -> TrustLevel:
    try:
        return TrustLevel(value)
    except ValueError:
        return TrustLevel.UNKNOWN
