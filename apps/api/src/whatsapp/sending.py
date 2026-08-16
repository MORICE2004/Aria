"""The send path — the only way a WhatsApp message can leave ARIA.

Read the directive's rule for this file: *do not simply remove the approval
check from the send function.* So the approval check is not removed. What
changes is who can satisfy it — a contact-scoped policy MORICE configured in
advance can now stand in for a click, for exactly the low-risk categories he
listed, and nothing else.

Four things still hold, and every one of them is enforced by code here rather
than promised in a comment:

1. **Every send goes through the Action Gateway.** Autonomous or approved by
   hand, a message is an `ActionRequest` with an executor and an audit trail.
   There is no second path.

2. **Permission is re-checked at execution time, not just at decision time.**
   The gap between deciding and sending is where a kill switch gets pressed.
   A reply approved thirty seconds ago must not go out if MORICE has stopped
   ARIA since — so the executor asks the autonomy engine again, and a stale
   approval fails closed.

3. **The API never touches WhatsApp.** Execution writes an `OutboundMessage`
   row; a separate sender process collects it. The process that reasons has no
   socket to WhatsApp, and the process with the socket cannot reason. Neither
   can send a message on its own.

4. **Collection re-checks the kill switch too.** A message can sit in the
   outbound queue for a few seconds. Pressing stop during those seconds must
   still stop it, so the check happens at handover as well.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import SessionMaker
from src.gateway import gateway
from src.gateway.service import register_executor
from src.models import (
    AutonomousResponse,
    AuditEvent,
    Contact,
    OutboundMessage,
)
from src.whatsapp import decision

logger = logging.getLogger(__name__)

ACTION_TYPE = "whatsapp.send"


class SendBlocked(Exception):
    """Permission was withdrawn between deciding and sending."""


@register_executor(ACTION_TYPE)
async def execute_whatsapp_send(payload: dict) -> str:
    """Gateway executor: hand an approved message to the outbound queue.

    Runs its own session because the gateway executes outside the request that
    submitted the action. Re-checks permission first — see rule 2 above.
    """
    async with SessionMaker() as session:
        contact = await session.get(Contact, payload["contact_id"])
        if contact is None:
            raise SendBlocked("contact no longer exists")

        body = payload["body"]

        # THE RE-CHECK. Not a formality: this is the only thing standing
        # between "MORICE pressed stop" and "the message went anyway".
        outcome = await decision.evaluate(
            session, contact, incoming=payload.get("incoming", ""), proposed_reply=body
        )
        if outcome.decision is decision.Decision.BLOCK:
            await _mark_blocked(session, payload, outcome.explain())
            raise SendBlocked(f"send refused at execution time: {outcome.explain()}")

        message = OutboundMessage(
            contact_id=contact.id,
            handle=contact.handle,
            body=body,
            origin=payload.get("origin", "autonomous"),
            autonomous_response_id=payload.get("autonomous_response_id"),
            action_request_id=payload.get("action_request_id", ""),
        )
        session.add(message)
        await session.commit()

        logger.info(
            "Queued outbound message to %s (%s)", contact.handle, message.id
        )
        return f"queued for delivery to {contact.name} ({message.id})"


async def _mark_blocked(session: AsyncSession, payload: dict, reason: str) -> None:
    response_id = payload.get("autonomous_response_id")
    if response_id:
        response = await session.get(AutonomousResponse, response_id)
        if response is not None:
            response.send_status = "blocked"
            response.send_error = reason
    session.add(
        AuditEvent(
            action_request_id=payload.get("action_request_id", "whatsapp"),
            event="send_blocked",
            detail=reason,
        )
    )
    await session.commit()


async def request_send(
    session: AsyncSession,
    *,
    contact: Contact,
    body: str,
    origin: str = "autonomous",
    autonomous_response_id: str | None = None,
    incoming: str = "",
    summary: str = "",
):
    """Submit a message to the Action Gateway.

    For an autonomous reply this is followed immediately by an auto-approval,
    because MORICE's contact policy IS the approval — granted in advance, for
    a named person and a named set of low-risk categories, instead of per
    message. The gateway still runs the executor, the audit trail still
    records every step, and the executor still re-checks permission.

    For anything else, the request sits in the approvals queue as it always
    has, waiting for a human.
    """
    request = await gateway.submit(
        session,
        agent="whatsapp",
        action_type=ACTION_TYPE,
        summary=summary or f"Send WhatsApp message to {contact.name}",
        payload={
            "contact_id": contact.id,
            "handle": contact.handle,
            "body": body,
            "origin": origin,
            "autonomous_response_id": autonomous_response_id,
            "incoming": incoming,
        },
    )
    # The payload needs its own request id so the executor can audit against
    # it; set after submit, when the id exists.
    request.payload = {**request.payload, "action_request_id": request.id}
    await session.commit()

    if origin == "autonomous":
        await gateway.approve(session, request.id)
        session.add(
            AuditEvent(
                action_request_id=request.id,
                event="pre_authorised",
                detail=(
                    "approved by the contact's standing autonomy policy, "
                    "not by a per-message click"
                ),
            )
        )
        await session.commit()

    return request


# --- Outbound queue, read by the sender process ---------------------------

async def claim_outbound(session: AsyncSession, limit: int = 10) -> list[dict]:
    """Hand pending messages to the sender, re-checking the stop controls.

    The kill switch is checked HERE, not only when the message was approved.
    A message approved a moment before MORICE pressed stop must not go out,
    and this is the last moment ARIA controls.
    """
    state = await decision.get_state(session)
    if state.emergency_stop or state.paused:
        blocked_reason = (
            "emergency stop is active"
            if state.emergency_stop
            else "ARIA is paused"
        )
        pending = (
            await session.execute(
                select(OutboundMessage).where(OutboundMessage.status == "pending")
            )
        ).scalars()
        count = 0
        for message in pending:
            message.status = "cancelled"
            message.last_error = blocked_reason
            count += 1
        if count:
            session.add(
                AuditEvent(
                    action_request_id="whatsapp",
                    event="outbound_cancelled",
                    detail=f"{count} queued message(s) cancelled: {blocked_reason}",
                )
            )
            logger.warning("Cancelled %d queued outbound message(s): %s", count, blocked_reason)
        await session.commit()
        return []

    rows = (
        await session.execute(
            select(OutboundMessage)
            .where(OutboundMessage.status == "pending")
            .order_by(OutboundMessage.created_at)
            .limit(limit)
        )
    ).scalars()

    claimed = []
    now = datetime.now(timezone.utc)
    for message in rows:
        message.status = "claimed"
        message.claimed_at = now
        message.attempts += 1
        claimed.append(
            {"id": message.id, "handle": message.handle, "body": message.body}
        )
    await session.commit()
    return claimed


async def confirm_sent(
    session: AsyncSession, message_id: str, *, ok: bool, error: str = ""
) -> OutboundMessage | None:
    """The sender reports what happened. Recorded either way."""
    message = await session.get(OutboundMessage, message_id)
    if message is None:
        return None

    message.status = "sent" if ok else "failed"
    message.last_error = "" if ok else error[:2000]
    message.sent_at = datetime.now(timezone.utc) if ok else None

    if message.autonomous_response_id:
        response = await session.get(
            AutonomousResponse, message.autonomous_response_id
        )
        if response is not None:
            response.send_status = "sent" if ok else "failed"
            response.send_error = "" if ok else error[:2000]

    session.add(
        AuditEvent(
            action_request_id=message.action_request_id or "whatsapp",
            event="sent" if ok else "send_failed",
            detail=f"{message.handle}: {message.body[:200]}" if ok else error[:500],
        )
    )
    await session.commit()
    return message


async def cancel_pending_for_contact(
    session: AsyncSession, contact_id: str, reason: str
) -> int:
    """Stop anything already queued for one contact.

    Called when MORICE takes over a conversation or pauses a contact: the
    intent is "ARIA, stop talking to this person", and a message already in
    the outbound queue would violate that intent a second later.
    """
    rows = (
        await session.execute(
            select(OutboundMessage).where(
                OutboundMessage.contact_id == contact_id,
                OutboundMessage.status.in_(("pending", "claimed")),
            )
        )
    ).scalars()

    count = 0
    for message in rows:
        message.status = "cancelled"
        message.last_error = reason
        count += 1
    if count:
        session.add(
            AuditEvent(
                action_request_id="whatsapp",
                event="outbound_cancelled",
                detail=f"{count} message(s) to contact {contact_id} cancelled: {reason}",
            )
        )
    await session.commit()
    return count
