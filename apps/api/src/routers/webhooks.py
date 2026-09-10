"""n8n and external webhook integration.

Inspired by n8n self-hosted AI workflows:
- Dispatches outbound events (e.g. messages received, actions approved) to n8n.
- Receives inbound webhooks from n8n to ingest knowledge, trigger actions, or query memory.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.db import get_session
from src.memory import get_memory_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


async def _post_webhook(url: str, secret: str, payload: dict[str, Any]) -> None:
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-ARIA-Webhook-Secret"] = secret

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json=payload, headers=headers)
    except Exception as exc:
        logger.warning("Failed to dispatch webhook to %s: %s", url, exc)


def dispatch_webhook(event: str, data: dict[str, Any]) -> None:
    """Dispatch an event asynchronously to n8n or external webhooks."""
    settings = get_settings()
    url = settings.n8n_webhook_url.strip()
    if not url:
        return

    payload = {
        "event": event,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_post_webhook(url, settings.webhook_secret, payload))
    except RuntimeError:
        pass


# ── Inbound n8n Webhook Handler ───────────────────────────────────────────


class InboundWebhookIn(BaseModel):
    action: str = Field(..., description="Action to perform: ingest | send_whatsapp | query_memory | status")
    secret: str = Field(default="", description="Webhook secret if configured")
    data: dict[str, Any] = Field(default_factory=dict)


class InboundWebhookOut(BaseModel):
    ok: bool
    action: str
    result: Any = None
    error: str | None = None


@router.post("/n8n", response_model=InboundWebhookOut)
async def handle_n8n_webhook(
    body: InboundWebhookIn,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Inbound webhook receiver for n8n workflows."""
    settings = get_settings()
    expected_secret = settings.webhook_secret.strip()
    if expected_secret:
        header_secret = request.headers.get("X-ARIA-Webhook-Secret", "")
        if body.secret != expected_secret and header_secret != expected_secret:
            raise HTTPException(401, "Invalid webhook secret")

    action = body.action.lower()
    data = body.data

    if action == "status":
        from src.whatsapp import autonomy
        state = await autonomy.get_state(session)
        return InboundWebhookOut(
            ok=True,
            action=action,
            result={
                "mode": state.mode,
                "emergency_stop": state.emergency_stop,
                "paused": state.paused,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    if action == "ingest":
        title = str(data.get("title", "n8n ingested item")).strip()
        content = str(data.get("content", "")).strip()
        if not content:
            raise HTTPException(422, "Content is required for ingest")
        kind = str(data.get("kind", "document")).strip()
        scope = str(data.get("style_scope", "")).strip()

        memory_svc = get_memory_service()
        item = await memory_svc.ingest(
            session,
            title=title,
            content=content,
            kind=kind,
            explicit=True,
            provenance="Ingested via n8n webhook",
            style_scope=scope,
        )
        return InboundWebhookOut(ok=True, action=action, result={"item_id": item.id, "title": item.title})

    if action == "query_memory":
        query = str(data.get("query", "")).strip()
        if not query:
            raise HTTPException(422, "Query is required")
        limit = int(data.get("limit", 4))

        memory_svc = get_memory_service()
        hits = await memory_svc.search(session, query, k=limit)
        return InboundWebhookOut(
            ok=True,
            action=action,
            result=[
                {"title": h.title, "content": h.content, "score": h.score, "kind": h.kind, "style_scope": h.style_scope}
                for h in hits
            ],
        )

    if action == "send_whatsapp":
        from src.whatsapp import autonomy, sending
        handle = str(data.get("handle", "")).strip()
        message = str(data.get("message", "")).strip()
        if not handle or not message:
            raise HTTPException(422, "handle and message are required")

        contact = await autonomy.find_contact(session, handle, channel="whatsapp")
        if not contact:
            raise HTTPException(404, f"Contact with handle '{handle}' not found")

        outbound = await sending.request_send(
            session,
            contact=contact,
            body=message,
            origin="n8n_webhook",
            summary=f"n8n webhook triggered send to {contact.name}: {message[:80]}",
        )
        return InboundWebhookOut(
            ok=True,
            action=action,
            result={"outbound_id": outbound.id, "status": outbound.status, "handle": handle},
        )

    raise HTTPException(400, f"Unknown action: {body.action}")
