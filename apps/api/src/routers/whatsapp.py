"""WhatsApp endpoints — autonomy control, contacts, observation, simulator.

Phase 8: observe mode. Nothing here can send a message; there is no send
path in this module at all.
"""

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.db import get_session
from src.llm import get_router
from src.communication import learning as comm_learning
from src.models import AuditEvent, Contact, MessageDraft, WhatsAppMessage
from src.whatsapp import autonomy, observer
from src.whatsapp.autonomy import Mode, TrustLevel

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

# Ingest lives on its own router, registered WITHOUT the dashboard JWT
# dependency: the caller is the local OpenClaw gateway, not a browser, and it
# authenticates with a shared secret instead. Without this split, turning on
# ARIA_PASSWORD would silently break message ingest.
ingest_router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


# ---------- shapes ----------

class AutonomyOut(BaseModel):
    mode: str
    emergency_stop: bool
    # Every mode and what it permits — so the dashboard never has to guess.
    available_modes: list[str]


class AutonomyIn(BaseModel):
    mode: str | None = None
    emergency_stop: bool | None = None


class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    handle: str = Field(min_length=1, max_length=120)
    relationship: str = "unknown"


class ContactUpdate(BaseModel):
    trust_level: str | None = None
    relationship: str | None = None
    notes: str | None = Field(default=None, max_length=5000)


class ContactOut(BaseModel):
    id: str
    name: str
    handle: str
    trust_level: str
    relationship: str
    notes: str
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

@router.get("/autonomy", response_model=AutonomyOut)
async def get_autonomy(session: AsyncSession = Depends(get_session)):
    state = await autonomy.get_state(session)
    return AutonomyOut(
        mode=state.mode,
        emergency_stop=state.emergency_stop,
        available_modes=[m.value for m in Mode],
    )


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

    return AutonomyOut(
        mode=state.mode,
        emergency_stop=state.emergency_stop,
        available_modes=[m.value for m in Mode],
    )


@router.post("/emergency-stop", response_model=AutonomyOut)
async def emergency_stop(session: AsyncSession = Depends(get_session)):
    """Kill switch. Immediately forces observe mode and blocks external action."""
    return await set_autonomy(AutonomyIn(emergency_stop=True), session)


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

    await session.commit()
    return await _to_contact_out(session, contact)


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
    """Inbound message pushed by OpenClaw.

    Field names mirror OpenClaw's webhook payload loosely; only what ARIA
    needs is accepted, and anything else is ignored rather than trusted.
    """

    handle: str = Field(min_length=1, max_length=120)
    name: str = Field(default="", max_length=200)
    body: str = Field(min_length=1, max_length=20_000)
    direction: str = Field(default="in", pattern="^(in|out)$")


@ingest_router.post("/ingest", response_model=ObservationOut, status_code=201)
async def ingest_message(
    body: IngestIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
    model_router=Depends(get_router),
):
    """Receive a real WhatsApp message from the OpenClaw gateway.

    Authenticated by a shared secret rather than the dashboard JWT, because
    the caller is a local service, not a browser. Fails closed: if no secret
    is configured, ingest is refused outright.

    This endpoint OBSERVES. It cannot reply — the observer enforces the
    autonomy gate, and no send path exists in this module.
    """
    expected = get_settings().openclaw_ingest_secret
    if not expected:
        raise HTTPException(
            503,
            "Ingest is disabled. Set OPENCLAW_INGEST_SECRET in .env and "
            "configure the same value in OpenClaw's webhook.",
        )
    presented = request.headers.get("X-ARIA-Ingest-Secret", "")
    if not secrets.compare_digest(presented, expected):
        raise HTTPException(401, "Bad ingest secret")

    obs = await observer.observe(
        session,
        model_router,
        handle=body.handle,
        name=body.name,
        body=body.body,
        direction=body.direction,
        simulated=False,  # real traffic
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
    return {
        "mode": state.mode,
        "emergency_stop": state.emergency_stop,
        "contacts": contacts,
        "channel_linked": False,  # Phase 7 (real WhatsApp link) not done yet
    }
