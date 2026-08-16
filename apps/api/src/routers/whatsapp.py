"""WhatsApp endpoints — autonomy control, contacts, observation, queue, simulator.

Ingest persists before it processes: see `src/whatsapp/queue.py` for why that
ordering is the difference between a durable channel and a lossy one.
"""

import hashlib
import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.db import SessionMaker, get_session
from src.llm import get_router
from src.communication import learning as comm_learning
from src.models import (
    AuditEvent,
    AutonomousResponse,
    Contact,
    LearningEvent,
    MessageDraft,
    OutboundMessage,
    WhatsAppMessage,
)
from src.whatsapp import (
    autonomy,
    decision,
    observer,
    queue,
    readiness,
    risk,
    sending,
)
from src.whatsapp.decision import Decision, Mode, TrustLevel
from src.whatsapp.worker import drain_due

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

# Ingest lives on its own router, registered WITHOUT the dashboard JWT
# dependency: the caller is the local OpenClaw gateway, not a browser, and it
# authenticates with a shared secret instead. Without this split, turning on
# ARIA_PASSWORD would silently break message ingest.
ingest_router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


# ---------- shapes ----------

class ModeOut(BaseModel):
    value: str
    description: str


class AutonomyOut(BaseModel):
    mode: str
    # Three separate stops, because they mean different things: pause ARIA
    # entirely, stop only automatic sending, or hit the emergency stop.
    emergency_stop: bool
    paused: bool
    autonomy_stopped: bool
    # Every mode and what it permits — so the dashboard never has to guess.
    available_modes: list[ModeOut]


class AutonomyIn(BaseModel):
    mode: str | None = None
    emergency_stop: bool | None = None
    paused: bool | None = None
    autonomy_stopped: bool | None = None


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    handle: str = Field(min_length=1, max_length=120)
    relationship: str = "unknown"


class ContactUpdate(BaseModel):
    trust_level: str | None = None
    relationship: str | None = None
    notes: str | None = Field(default=None, max_length=5000)
    # --- per-contact autonomy policy ---
    autonomy_enabled: bool | None = None
    allowed_actions: list[str] | None = None
    forbidden_actions: list[str] | None = None
    paused: bool | None = None
    taken_over: bool | None = None


class ContactOut(BaseModel):
    id: str
    name: str
    handle: str
    trust_level: str
    relationship: str
    notes: str
    autonomy_enabled: bool
    allowed_actions: list[str]
    forbidden_actions: list[str]
    paused: bool
    taken_over: bool
    # Effective permission for this contact right now, and why.
    effective_mode: str
    mode_reason: str


class MessageOut(BaseModel):
    id: str
    direction: str
    body: str
    sent_at: datetime
    simulated: bool

    model_config = {"from_attributes": True}


class SimulateIn(BaseModel):
    """Feed ARIA a message as if it arrived on WhatsApp."""

    handle: str = Field(min_length=1, max_length=120)
    name: str = Field(default="", max_length=200)
    body: str = Field(min_length=1, max_length=10_000)
    direction: str = Field(default="in", pattern="^(in|out)$")


class ObservationOut(BaseModel):
    contact: ContactOut
    stored_message_id: str
    effective_mode: str
    mode_reason: str
    intent: str | None
    needs_reply: bool | None
    sensitive: list[str]
    urgency: str | None
    language: str | None
    draft: str | None
    # Explicit, so the UI can state plainly that nothing was or will be sent.
    sent: bool = False


# ---------- autonomy control ----------

def _autonomy_out(state) -> AutonomyOut:
    return AutonomyOut(
        mode=state.mode,
        emergency_stop=state.emergency_stop,
        paused=state.paused,
        autonomy_stopped=state.autonomy_stopped,
        available_modes=[
            ModeOut(value=m.value, description=autonomy.MODE_DESCRIPTIONS[m])
            for m in Mode
        ],
    )


@router.get("/autonomy", response_model=AutonomyOut)
async def get_autonomy(session: AsyncSession = Depends(get_session)):
    return _autonomy_out(await autonomy.get_state(session))


@router.patch("/autonomy", response_model=AutonomyOut)
async def set_autonomy(
    body: AutonomyIn, session: AsyncSession = Depends(get_session)
):
    """Change the global autonomy mode or the kill switch.

    Every change is written to the append-only audit log: autonomy must never
    change silently, including when MORICE himself changes it.
    """
    state = await autonomy.get_state(session)
    changes: list[str] = []

    if body.mode is not None:
        try:
            new_mode = Mode(body.mode)
        except ValueError:
            raise HTTPException(
                422, f"mode must be one of {[m.value for m in Mode]}"
            ) from None
        if state.emergency_stop and new_mode is not Mode.OBSERVE:
            raise HTTPException(
                409,
                "Emergency stop is active. Clear it before raising the autonomy mode.",
            )
        changes.append(f"mode {state.mode} -> {new_mode.value}")
        state.mode = new_mode.value

    if body.paused is not None:
        changes.append(f"paused {state.paused} -> {body.paused}")
        state.paused = body.paused

    if body.autonomy_stopped is not None:
        changes.append(
            f"autonomy_stopped {state.autonomy_stopped} -> {body.autonomy_stopped}"
        )
        state.autonomy_stopped = body.autonomy_stopped

    if body.emergency_stop is not None:
        changes.append(f"emergency_stop {state.emergency_stop} -> {body.emergency_stop}")
        state.emergency_stop = body.emergency_stop
        if body.emergency_stop:
            # Drop to observe immediately rather than merely masking the mode.
            state.mode = Mode.OBSERVE.value

    if changes:
        state.updated_at = datetime.now(timezone.utc)
        session.add(
            AuditEvent(
                action_request_id="autonomy",
                event="autonomy_changed",
                detail="; ".join(changes),
            )
        )
        await session.commit()

    # Any stop must also stop what is ALREADY in flight. A kill switch that
    # only prevents future decisions, while a message approved two seconds ago
    # sails out of the queue, is not a kill switch.
    if state.emergency_stop or state.paused:
        await sending.claim_outbound(session)

    return _autonomy_out(state)


@router.post("/emergency-stop", response_model=AutonomyOut)
async def emergency_stop(session: AsyncSession = Depends(get_session)):
    """Kill switch. Immediately forces observe mode and blocks external action.

    Also cancels anything already queued for delivery — see set_autonomy.
    """
    return await set_autonomy(AutonomyIn(emergency_stop=True), session)


@router.post("/pause", response_model=AutonomyOut)
async def pause_aria(
    resume: bool = False, session: AsyncSession = Depends(get_session)
):
    """PAUSE ARIA — stop acting, keep observing and learning.

    Softer than the emergency stop: the mode is preserved, so resuming puts
    everything back exactly as it was instead of making MORICE reconstruct it.
    """
    return await set_autonomy(AutonomyIn(paused=not resume), session)


@router.post("/stop-autonomy", response_model=AutonomyOut)
async def stop_autonomy(
    resume: bool = False, session: AsyncSession = Depends(get_session)
):
    """STOP AUTONOMY — no automatic sending; drafting and asking continue.

    For "keep helping me, but check with me first" — which is a different
    intention from "stop", and deserves its own control rather than a mode
    change MORICE then has to remember to undo.
    """
    return await set_autonomy(AutonomyIn(autonomy_stopped=not resume), session)


# ---------- contacts ----------

async def _to_contact_out(session: AsyncSession, contact: Contact) -> ContactOut:
    mode, reason = await autonomy.resolve_for_contact(session, contact)
    return ContactOut(
        id=contact.id,
        name=contact.name,
        handle=contact.handle,
        trust_level=contact.trust_level,
        relationship=contact.relationship,
        notes=contact.notes,
        autonomy_enabled=contact.autonomy_enabled,
        allowed_actions=list(contact.allowed_actions or risk.DEFAULT_ALLOWED_ACTIONS),
        forbidden_actions=list(contact.forbidden_actions or []),
        paused=contact.paused,
        taken_over=contact.taken_over,
        effective_mode=mode.value,
        mode_reason=reason,
    )


@router.post("/contacts", response_model=ContactOut, status_code=201)
async def add_contact(body: ContactIn, session: AsyncSession = Depends(get_session)):
    if await autonomy.find_contact(session, body.handle):
        raise HTTPException(409, "A contact with that handle already exists")
    contact = Contact(
        name=body.name, handle=body.handle, relationship=body.relationship
    )
    session.add(contact)
    await session.commit()
    return await _to_contact_out(session, contact)


@router.get("/contacts", response_model=list[ContactOut])
async def list_contacts(session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Contact).order_by(Contact.created_at))
    return [await _to_contact_out(session, c) for c in result.scalars()]


@router.patch("/contacts/{contact_id}", response_model=ContactOut)
async def update_contact(
    contact_id: str, body: ContactUpdate, session: AsyncSession = Depends(get_session)
):
    contact = await session.get(Contact, contact_id)
    if contact is None:
        raise HTTPException(404, "Contact not found")

    if body.trust_level is not None:
        try:
            trust = TrustLevel(body.trust_level)
        except ValueError:
            raise HTTPException(
                422, f"trust_level must be one of {[t.value for t in TrustLevel]}"
            ) from None
        # Trust changes are consequential — audit them like autonomy changes.
        session.add(
            AuditEvent(
                action_request_id="contact_trust",
                event="trust_changed",
                detail=f"{contact.handle}: {contact.trust_level} -> {trust.value}",
            )
        )
        contact.trust_level = trust.value

    if body.relationship is not None:
        contact.relationship = body.relationship
    if body.notes is not None:
        contact.notes = body.notes

    # --- autonomy policy ---
    # Every field here is consequential, so every change is audited, including
    # when MORICE makes it himself.

    if body.allowed_actions is not None:
        unknown = set(body.allowed_actions) - set(risk.ACTION_TYPES)
        if unknown:
            raise HTTPException(
                422,
                f"unknown action type(s): {sorted(unknown)}. "
                f"Valid: {list(risk.ACTION_TYPES)}",
            )
        # Categories that are never autonomous cannot be allowed into the list.
        # Rejecting them here means the UI cannot present a checkbox that would
        # silently do nothing — the engine would refuse them anyway.
        forbidden_always = set(body.allowed_actions) & set(
            risk.NEVER_AUTONOMOUS_ACTIONS
        )
        if forbidden_always:
            raise HTTPException(
                422,
                f"{sorted(forbidden_always)} can never be handled autonomously. "
                "ARIA will always ask you about these.",
            )
        session.add(
            AuditEvent(
                action_request_id="contact_policy",
                event="allowed_actions_changed",
                detail=f"{contact.handle}: {contact.allowed_actions} -> "
                f"{body.allowed_actions}",
            )
        )
        contact.allowed_actions = list(body.allowed_actions)

    if body.forbidden_actions is not None:
        unknown = set(body.forbidden_actions) - set(risk.ACTION_TYPES)
        if unknown:
            raise HTTPException(422, f"unknown action type(s): {sorted(unknown)}")
        contact.forbidden_actions = list(body.forbidden_actions)

    if body.autonomy_enabled is not None:
        if body.autonomy_enabled:
            # Two gates, deliberately. Trust describes the relationship;
            # enabling autonomy is the separate, explicit grant. Requiring both
            # means raising trust can never by itself start sending messages.
            trust_now = decision._trust_or_unknown(contact.trust_level)
            ceiling = decision._TRUST_CEILING[trust_now]
            if decision.rank(ceiling) < decision.rank(Mode.LIMITED_AUTONOMY):
                raise HTTPException(
                    409,
                    f"Trust level '{contact.trust_level}' does not permit autonomy "
                    f"(it caps this contact at '{ceiling.value}'). Raise the trust "
                    "level first, deliberately.",
                )
        session.add(
            AuditEvent(
                action_request_id="contact_policy",
                event="autonomy_enabled" if body.autonomy_enabled else "autonomy_disabled",
                detail=f"{contact.handle}: autonomy -> {body.autonomy_enabled}",
            )
        )
        contact.autonomy_enabled = body.autonomy_enabled

    if body.paused is not None:
        contact.paused = body.paused
        session.add(
            AuditEvent(
                action_request_id="contact_policy",
                event="contact_paused" if body.paused else "contact_resumed",
                detail=contact.handle,
            )
        )

    if body.taken_over is not None:
        contact.taken_over = body.taken_over
        contact.taken_over_at = (
            datetime.now(timezone.utc) if body.taken_over else None
        )
        session.add(
            AuditEvent(
                action_request_id="contact_policy",
                event="taken_over" if body.taken_over else "handed_back",
                detail=contact.handle,
            )
        )

    await session.commit()

    # Pausing or taking over must also stop what is already queued. Otherwise
    # "ARIA, stop talking to this person" is followed a second later by ARIA
    # talking to that person.
    if body.paused or body.taken_over:
        await sending.cancel_pending_for_contact(
            session,
            contact.id,
            "MORICE took over the conversation"
            if body.taken_over
            else "ARIA paused for this contact",
        )

    return await _to_contact_out(session, contact)


@router.post("/contacts/{contact_id}/take-over", response_model=ContactOut)
async def take_over(
    contact_id: str,
    release: bool = False,
    session: AsyncSession = Depends(get_session),
):
    """TAKE OVER — MORICE handles this conversation himself from now on.

    ARIA stops responding to this contact entirely, and anything already
    queued for them is cancelled. She does not resume when the conversation
    goes quiet, or after a timeout, or because she judges the topic to have
    changed: only an explicit release brings her back. A takeover that expires
    on its own is a takeover MORICE cannot rely on.
    """
    return await update_contact(
        contact_id, ContactUpdate(taken_over=not release), session
    )


@router.post("/contacts/{contact_id}/pause", response_model=ContactOut)
async def pause_contact(
    contact_id: str,
    resume: bool = False,
    session: AsyncSession = Depends(get_session),
):
    """Disable ARIA for one contact, without touching anyone else."""
    return await update_contact(
        contact_id, ContactUpdate(paused=not resume), session
    )


@router.get("/contacts/{contact_id}/messages", response_model=list[MessageOut])
async def contact_messages(
    contact_id: str, session: AsyncSession = Depends(get_session)
):
    if await session.get(Contact, contact_id) is None:
        raise HTTPException(404, "Contact not found")
    return await observer.recent_messages(session, contact_id)


# ---------- observation / simulator ----------

@router.post("/simulate", response_model=ObservationOut, status_code=201)
async def simulate_message(
    body: SimulateIn,
    session: AsyncSession = Depends(get_session),
    model_router=Depends(get_router),
):
    """Feed ARIA a message as if it arrived on WhatsApp.

    This is how observe mode is exercised and tested before a real account is
    ever connected. Simulated messages are flagged in the database so they can
    be told apart from real history.
    """
    obs = await observer.observe(
        session,
        model_router,
        handle=body.handle,
        name=body.name,
        body=body.body,
        direction=body.direction,
        simulated=True,
    )
    c = obs.classification
    return ObservationOut(
        contact=await _to_contact_out(session, obs.contact),
        stored_message_id=obs.message.id,
        effective_mode=obs.mode.value,
        mode_reason=obs.mode_reason,
        intent=c.intent if c else None,
        needs_reply=c.needs_reply if c else None,
        sensitive=c.sensitive if c else [],
        urgency=c.urgency if c else None,
        language=c.language if c else None,
        draft=obs.draft,
    )


class IngestIn(BaseModel):
    """Inbound message pushed by the WhatsApp bridge.

    Only what ARIA needs is accepted; anything else in the payload is ignored
    rather than trusted.
    """

    handle: str = Field(min_length=1, max_length=120)
    name: str = Field(default="", max_length=200)
    body: str = Field(min_length=1, max_length=20_000)
    direction: str = Field(default="in", pattern="^(in|out)$")
    # Transport-assigned message id. The bridge always sends one; it is the
    # dedupe key. Optional only so the endpoint stays usable by hand, in which
    # case a content hash stands in.
    message_id: str = Field(default="", max_length=180)
    # Sender's clock, epoch seconds. Lets a delayed message be recognised as
    # delayed rather than treated as fresh.
    timestamp: int | None = None


class IngestOut(BaseModel):
    """Acknowledgement that the message is DURABLE.

    `queued: true` is a promise that the message is committed to the database
    and will be processed. The bridge deletes its spooled copy on this
    response and on no other, so the field's meaning is load-bearing.

    Note what this response does NOT contain: what ARIA thought of the message.
    That is deliberate — see the endpoint docstring.
    """

    queued: bool
    duplicate: bool
    queue_id: str
    status: str


def _require_ingest_secret(request: Request) -> None:
    """Shared-secret auth for local services. Fails closed."""
    expected = get_settings().openclaw_ingest_secret
    if not expected:
        raise HTTPException(
            503,
            "Ingest is disabled. Set OPENCLAW_INGEST_SECRET in .env and the "
            "same value in the bridge's config.json.",
        )
    presented = request.headers.get("X-ARIA-Ingest-Secret", "")
    if not secrets.compare_digest(presented, expected):
        raise HTTPException(401, "Bad ingest secret")


@ingest_router.post("/ingest", response_model=IngestOut, status_code=202)
async def ingest_message(
    body: IngestIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Receive a real WhatsApp message. Store it, acknowledge, and stop.

    This endpoint does one thing: INSERT and COMMIT. It does not classify,
    draft, decide, or send. Understanding the message is the worker's job.

    That separation is the fix for the original data-loss bug, and it is not
    only about crashes. The first version of this rewrite still classified
    inline, and the very first live test failed: a cold local model took 33
    seconds, the bridge's HTTP client gave up at 20, and the bridge could not
    tell "ARIA never got it" from "ARIA got it and is thinking". It had to
    assume the worst and hold the message — correct, but it means receipt
    latency was hostage to model latency. A receiver whose speed depends on an
    LLM is a receiver that will time out, and a receiver that times out under
    load is how messages get lost in the first place.

    So: acknowledge in milliseconds, process out of band, expose the result
    through the queue endpoints. The bridge only ever needed to know the
    message was safe.

    Authenticated by a shared secret rather than the dashboard JWT, because the
    caller is a local service, not a browser.
    """
    _require_ingest_secret(request)

    dedupe_key = body.message_id.strip() or _fallback_dedupe_key(body)
    sent_at = (
        datetime.fromtimestamp(body.timestamp, tz=timezone.utc)
        if body.timestamp
        else None
    )

    row, created = await queue.enqueue(
        session,
        dedupe_key=dedupe_key,
        handle=body.handle,
        name=body.name,
        body=body.body,
        direction=body.direction,
        sent_at=sent_at,
    )

    # A redelivery is acknowledged, never reprocessed. This is what stops a
    # duplicate message from producing a duplicate response.
    return IngestOut(
        queued=True,
        duplicate=not created,
        queue_id=row.id,
        status=row.status,
    )


def _fallback_dedupe_key(body: IngestIn) -> str:
    """Dedupe key for callers that supply no transport message id.

    Content-based, so a hand-repeated identical message within the same second
    still deduplicates. Real bridge traffic never takes this path.
    """
    material = f"{body.handle}|{body.direction}|{body.timestamp or ''}|{body.body}"
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


# ---------- queue observability ----------

class QueueItemOut(BaseModel):
    id: str
    dedupe_key: str
    handle: str
    name: str
    body: str
    direction: str
    status: str
    attempts: int
    last_error: str
    outcome: str
    # Sender's clock vs ARIA's. Both are exposed so a message delayed in
    # transit is visibly delayed rather than looking freshly sent.
    sent_at: datetime | None
    received_at: datetime
    next_attempt_at: datetime
    processed_at: datetime | None

    model_config = {"from_attributes": True}


@router.get("/queue")
async def queue_stats(session: AsyncSession = Depends(get_session)):
    """Queue health. Processing state must be visible, not inferred."""
    return await queue.stats(session)


@router.get("/queue/items", response_model=list[QueueItemOut])
async def queue_items(
    status: str | None = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    """Recent queued messages, newest first. `?status=dead` is the error list."""
    return await queue.list_messages(session, status=status, limit=min(limit, 200))


@router.post("/queue/{message_id}/retry", response_model=QueueItemOut)
async def queue_retry(
    message_id: str, session: AsyncSession = Depends(get_session)
):
    """Replay a dead message after fixing whatever killed it."""
    row = await queue.revive(session, message_id)
    if row is None:
        raise HTTPException(404, "Queued message not found")
    return row


@router.post("/queue/drain")
async def queue_drain(
    session: AsyncSession = Depends(get_session),
    model_router=Depends(get_router),
):
    """Process everything currently due, synchronously.

    The worker does this on a timer; this endpoint exists so recovery can be
    triggered and observed deliberately rather than waited for.
    """
    handled = await drain_due(SessionMaker, model_router)
    return {"processed": handled, "queue": await queue.stats(session)}


class DraftOut(BaseModel):
    id: str
    contact_id: str
    contact_name: str
    incoming: str
    draft: str
    status: str
    final: str
    rationale: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DecideDraftIn(BaseModel):
    # approved = "good, I'll send it myself"; edited = he rewrote it;
    # rejected = wrong. ARIA cannot send in any case.
    decision: str = Field(pattern="^(approved|edited|rejected)$")
    final: str = Field(default="", max_length=20_000)
    note: str = Field(default="", max_length=1_000)


class DecideDraftOut(BaseModel):
    status: str
    lessons: list[str]
    sent: bool = False  # always false: the transport is read-only


@router.get("/drafts", response_model=list[DraftOut])
async def list_drafts(
    status: str = "pending", session: AsyncSession = Depends(get_session)
):
    """Drafts awaiting review."""
    rows = await session.execute(
        select(MessageDraft, Contact)
        .join(Contact, Contact.id == MessageDraft.contact_id)
        .where(MessageDraft.status == status)
        .order_by(MessageDraft.created_at.desc())
    )
    return [
        DraftOut(
            id=d.id, contact_id=d.contact_id, contact_name=c.name,
            incoming=d.incoming, draft=d.draft, status=d.status, final=d.final,
            rationale=d.rationale, created_at=d.created_at,
        )
        for d, c in rows.all()
    ]


@router.post("/drafts/{draft_id}/decide", response_model=DecideDraftOut)
async def decide_draft(
    draft_id: str,
    body: DecideDraftIn,
    session: AsyncSession = Depends(get_session),
):
    """Approve, correct, or reject a draft — and learn from the outcome.

    Nothing is sent. ARIA's WhatsApp transport is read-only; approving means
    MORICE will send it himself. The value here is the learning signal.
    """
    draft = await session.get(MessageDraft, draft_id)
    if draft is None:
        raise HTTPException(404, "Draft not found")
    if draft.status != "pending":
        raise HTTPException(409, f"Draft already {draft.status}")

    final_text = body.final.strip()
    if body.decision == "edited" and not final_text:
        raise HTTPException(422, "An edited draft needs the corrected text")

    draft.status = body.decision
    draft.final = final_text if body.decision == "edited" else (
        draft.draft if body.decision == "approved" else ""
    )
    draft.decided_at = datetime.now(timezone.utc)

    _, lessons = await comm_learning.record_feedback(
        session,
        kind=body.decision,
        draft=draft.draft,
        final=draft.final,
        contact_id=draft.contact_id,
        note=body.note,
    )
    return DecideDraftOut(status=draft.status, lessons=lessons)


# ---------- autonomy engine: preview, responses, readiness ----------

class EvaluateIn(BaseModel):
    """Ask the engine what it WOULD do, without doing it."""

    handle: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=10_000)
    proposed_reply: str = Field(default="", max_length=10_000)


class DecisionOut(BaseModel):
    decision: str
    reasons: list[str]
    action_type: str
    risk_level: str
    risk_categories: list[str]
    risk_reasons: list[str]
    injection_suspected: bool
    effective_mode: str
    communication_confidence: float
    correction_rate: float


def _decision_out(outcome) -> DecisionOut:
    s = outcome.signals
    return DecisionOut(
        decision=outcome.decision.value,
        reasons=outcome.reasons,
        action_type=s.action if s else "",
        risk_level=s.risk.level.value if s else "",
        risk_categories=list(s.risk.categories) if s else [],
        risk_reasons=list(s.risk.reasons) if s else [],
        injection_suspected=s.risk.injection_suspected if s else False,
        effective_mode=s.effective_mode.value if s else "",
        communication_confidence=s.communication_confidence if s else 0.0,
        correction_rate=s.correction_rate if s else 0.0,
    )


@router.post("/evaluate", response_model=DecisionOut)
async def evaluate_message(
    body: EvaluateIn, session: AsyncSession = Depends(get_session)
):
    """What would ARIA do with this message, and why?

    A dry run over the real policy and the real contact record. Nothing is
    stored and nothing is sent — this is how MORICE can check a policy change
    before trusting it with a real conversation.
    """
    contact = await autonomy.find_contact(session, body.handle)
    if contact is None:
        raise HTTPException(404, "Contact not found")
    outcome = await decision.evaluate(
        session,
        contact,
        incoming=body.body,
        proposed_reply=body.proposed_reply or None,
    )
    return _decision_out(outcome)


class AutonomousResponseOut(BaseModel):
    id: str
    contact_id: str
    contact_name: str
    incoming: str
    response: str
    decision: str
    decision_reasons: list[str]
    autonomy_mode: str
    action_type: str
    risk_level: str
    risk_categories: list[str]
    communication_confidence: float
    model: str
    estimated_cost_usd: float
    send_status: str
    send_error: str
    user_reaction: str
    correction: str
    created_at: datetime


@router.get("/autonomous", response_model=list[AutonomousResponseOut])
async def list_autonomous_responses(
    limit: int = 50, session: AsyncSession = Depends(get_session)
):
    """Everything ARIA sent on her own, newest first, with the full rationale."""
    rows = await session.execute(
        select(AutonomousResponse, Contact)
        .join(Contact, Contact.id == AutonomousResponse.contact_id)
        .order_by(AutonomousResponse.created_at.desc())
        .limit(min(limit, 200))
    )
    return [
        AutonomousResponseOut(
            id=r.id,
            contact_id=r.contact_id,
            contact_name=c.name,
            incoming=r.incoming,
            response=r.response,
            decision=r.decision,
            decision_reasons=list(r.decision_reasons or []),
            autonomy_mode=r.autonomy_mode,
            action_type=r.action_type,
            risk_level=r.risk_level,
            risk_categories=list(r.risk_categories or []),
            communication_confidence=r.communication_confidence,
            model=r.model,
            estimated_cost_usd=r.estimated_cost_usd,
            send_status=r.send_status,
            send_error=r.send_error,
            user_reaction=r.user_reaction,
            correction=r.correction,
            created_at=r.created_at,
        )
        for r, c in rows.all()
    ]


class ReactIn(BaseModel):
    # approved = "that was right"; corrected = "here is what you should have
    # said"; rejected = "you should not have sent that".
    reaction: str = Field(pattern="^(approved|corrected|rejected)$")
    correction: str = Field(default="", max_length=20_000)
    note: str = Field(default="", max_length=1_000)


class ReactOut(BaseModel):
    reaction: str
    lessons: list[str]


@router.post("/autonomous/{response_id}/react", response_model=ReactOut)
async def react_to_autonomous_response(
    response_id: str, body: ReactIn, session: AsyncSession = Depends(get_session)
):
    """Tell ARIA what she got right or wrong about a message she sent alone.

    This is the strong evidence. ARIA does not infer approval from silence —
    a response MORICE never reacts to stays `none` forever and is excluded
    from her correction rate entirely, rather than counted as a success.
    Otherwise she would grow more confident the less attention he paid, which
    is exactly backwards.
    """
    response = await session.get(AutonomousResponse, response_id)
    if response is None:
        raise HTTPException(404, "Response not found")

    correction = body.correction.strip()
    if body.reaction == "corrected" and not correction:
        raise HTTPException(422, "A correction needs the text you would have sent")

    response.user_reaction = body.reaction
    response.correction = correction
    response.reacted_at = datetime.now(timezone.utc)

    # Feed the existing Phase 5 learning loop. An edit teaches the most, so a
    # correction is recorded as an edit against the message ARIA actually sent.
    kind = {"approved": "approved", "corrected": "edited", "rejected": "rejected"}[
        body.reaction
    ]
    event, lessons = await comm_learning.record_feedback(
        session,
        kind=kind,
        draft=response.response,
        final=correction,
        contact_id=response.contact_id,
        note=body.note,
    )
    response.learning_event_ids = [*(response.learning_event_ids or []), event.id]
    await session.commit()
    return ReactOut(reaction=body.reaction, lessons=lessons)


@router.get("/readiness")
async def autonomy_readiness(session: AsyncSession = Depends(get_session)):
    """How ready each contact is for more autonomy — as INFORMATION.

    Nothing reads this score to change a permission. A high score is an
    invitation for MORICE to consider enabling autonomy; it never enables
    anything, because a system that can promote itself on evidence it
    generates is not supervised.
    """
    scores = await readiness.score_all(session)
    return {
        "advisory": (
            "These scores never enable autonomy. Only you can, per contact."
        ),
        "contacts": [
            {
                "contact_id": r.contact_id,
                "contact_name": r.contact_name,
                "score": r.score,
                "factors": r.factors,
                "notes": r.notes,
                "blocking": r.blocking,
            }
            for r in scores
        ],
    }


# ---------- outbound queue (read by the sender process) ----------

class OutboundClaimOut(BaseModel):
    messages: list[dict]


@ingest_router.post("/outbound/claim", response_model=OutboundClaimOut)
async def claim_outbound_messages(
    request: Request, session: AsyncSession = Depends(get_session)
):
    """The sender collects approved messages.

    Secret-authenticated like ingest: the caller is a local process, not a
    browser. The stop controls are re-checked inside `claim_outbound`, so a
    message approved moments before MORICE pressed stop is cancelled here
    rather than delivered.
    """
    _require_ingest_secret(request)
    return OutboundClaimOut(messages=await sending.claim_outbound(session))


class ConfirmSendIn(BaseModel):
    id: str
    ok: bool
    error: str = Field(default="", max_length=2000)


@ingest_router.post("/outbound/confirm")
async def confirm_outbound(
    body: ConfirmSendIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """The sender reports the outcome. Recorded and audited either way."""
    _require_ingest_secret(request)
    message = await sending.confirm_sent(
        session, body.id, ok=body.ok, error=body.error
    )
    if message is None:
        raise HTTPException(404, "Outbound message not found")
    return {"id": message.id, "status": message.status}


@router.get("/outbound")
async def list_outbound(
    status: str | None = None,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
):
    """Outbound queue, so MORICE can see what is about to be said in his name."""
    query = select(OutboundMessage).order_by(OutboundMessage.created_at.desc())
    if status:
        query = query.where(OutboundMessage.status == status)
    rows = (await session.execute(query.limit(min(limit, 200)))).scalars()
    return [
        {
            "id": m.id,
            "handle": m.handle,
            "body": m.body,
            "origin": m.origin,
            "status": m.status,
            "attempts": m.attempts,
            "last_error": m.last_error,
            "created_at": m.created_at,
            "sent_at": m.sent_at,
        }
        for m in rows
    ]


@router.get("/activity")
async def activity(session: AsyncSession = Depends(get_session)):
    """Everything the Autonomous Activity page needs, in one call.

    Deliberately one endpoint rather than eight: the page's job is to answer
    "what is ARIA doing right now", and a dashboard assembled from eight
    independently-loading panels shows a different moment in each one.
    """
    state = await autonomy.get_state(session)
    queue_stats = await queue.stats(session)

    async def _count(model, *where):
        return (
            await session.execute(select(func.count(model.id)).where(*where))
        ).scalar_one() or 0

    auto_sent = await _count(
        AutonomousResponse, AutonomousResponse.send_status == "sent"
    )
    auto_queued = await _count(
        AutonomousResponse, AutonomousResponse.send_status == "queued"
    )
    auto_blocked = await _count(
        AutonomousResponse, AutonomousResponse.send_status == "blocked"
    )
    awaiting_approval = await _count(
        MessageDraft, MessageDraft.status == "pending"
    )
    corrections = await _count(
        AutonomousResponse,
        AutonomousResponse.user_reaction.in_(("corrected", "rejected")),
    )
    approvals = await _count(
        AutonomousResponse, AutonomousResponse.user_reaction == "approved"
    )

    # Cost of autonomy specifically, kept apart from ARIA's total spend so
    # "what is this costing me" has an answer scoped to what she does alone.
    autonomous_cost = (
        await session.execute(
            select(func.sum(AutonomousResponse.estimated_cost_usd))
        )
    ).scalar_one() or 0.0

    risk_rows = (
        await session.execute(
            select(AutonomousResponse.risk_level, func.count(AutonomousResponse.id))
            .group_by(AutonomousResponse.risk_level)
        )
    ).all()

    model_rows = (
        await session.execute(
            select(AutonomousResponse.model, func.count(AutonomousResponse.id))
            .group_by(AutonomousResponse.model)
        )
    ).all()

    contacts = (
        await session.execute(select(Contact).order_by(Contact.created_at))
    ).scalars()
    autonomous_contacts = []
    for contact in contacts:
        if not contact.autonomy_enabled:
            continue
        confidence = await decision.communication_confidence(session, contact)
        reviewed, correction_rate = await decision.correction_history(
            session, contact.id
        )
        autonomous_contacts.append(
            {
                "id": contact.id,
                "name": contact.name,
                "handle": contact.handle,
                "trust_level": contact.trust_level,
                "allowed_actions": list(
                    contact.allowed_actions or risk.DEFAULT_ALLOWED_ACTIONS
                ),
                "forbidden_actions": list(contact.forbidden_actions or []),
                "paused": contact.paused,
                "taken_over": contact.taken_over,
                "communication_confidence": confidence,
                "reviewed_responses": reviewed,
                "correction_rate": correction_rate,
            }
        )

    recent_learning = (
        await session.execute(
            select(LearningEvent)
            .order_by(LearningEvent.created_at.desc())
            .limit(10)
        )
    ).scalars()

    failed = await queue.list_messages(session, status="dead", limit=10)

    return {
        "mode": state.mode,
        "mode_description": autonomy.MODE_DESCRIPTIONS[
            decision._mode_or_observe(state.mode)
        ],
        "emergency_stop": state.emergency_stop,
        "paused": state.paused,
        "autonomy_stopped": state.autonomy_stopped,
        "messages": {
            "received": queue_stats["received"],
            "processed": queue_stats["done"],
            "pending": queue_stats["pending"] + queue_stats["processing"],
            "failed": queue_stats["dead"],
            "backlog_seconds": queue_stats["backlog_seconds"],
        },
        "autonomous": {
            "sent": auto_sent,
            "queued": auto_queued,
            "blocked": auto_blocked,
            "awaiting_approval": awaiting_approval,
            "approved_by_user": approvals,
            "corrected_by_user": corrections,
            # Stated explicitly so the dashboard never implies that unreviewed
            # means fine.
            "unreviewed": max(
                auto_sent - approvals - corrections, 0
            ),
        },
        "risk_breakdown": {level or "unknown": count for level, count in risk_rows},
        "models_used": {model or "unknown": count for model, count in model_rows},
        "estimated_autonomous_cost_usd": round(autonomous_cost, 6),
        "autonomous_contacts": autonomous_contacts,
        "recent_learning": [
            {
                "kind": e.kind,
                "note": e.note,
                "draft": e.draft[:200],
                "final": e.final[:200],
                "created_at": e.created_at,
            }
            for e in recent_learning
        ],
        "errors": [
            {
                "id": m.id,
                "handle": m.handle,
                "body": m.body[:200],
                "attempts": m.attempts,
                "last_error": m.last_error,
                "received_at": m.received_at,
            }
            for m in failed
        ],
    }


@router.get("/overview")
async def overview(session: AsyncSession = Depends(get_session)):
    """Dashboard summary: autonomy state plus per-contact message counts."""
    state = await autonomy.get_state(session)
    rows = await session.execute(
        select(Contact, func.count(WhatsAppMessage.id))
        .outerjoin(WhatsAppMessage, WhatsAppMessage.contact_id == Contact.id)
        .group_by(Contact.id)
        .order_by(Contact.created_at)
    )
    contacts = []
    for contact, count in rows.all():
        mode, reason = await autonomy.resolve_for_contact(session, contact)
        contacts.append(
            {
                "id": contact.id,
                "name": contact.name,
                "handle": contact.handle,
                "trust_level": contact.trust_level,
                "message_count": count,
                "effective_mode": mode.value,
                "mode_reason": reason,
            }
        )
    # Whether a real transport is actually delivering, rather than a constant.
    # This was hardcoded False long after the Baileys bridge went live, so the
    # dashboard claimed "not linked" while real messages were arriving.
    # Derived from evidence instead: a non-simulated message means the channel
    # is genuinely connected.
    real_message = (
        await session.execute(
            select(func.count(WhatsAppMessage.id)).where(
                WhatsAppMessage.simulated.is_(False)
            )
        )
    ).scalar_one() or 0

    return {
        "mode": state.mode,
        "emergency_stop": state.emergency_stop,
        "paused": state.paused,
        "autonomy_stopped": state.autonomy_stopped,
        "contacts": contacts,
        "channel_linked": real_message > 0,
    }
