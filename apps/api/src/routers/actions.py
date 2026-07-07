"""Action Gateway endpoints: the approval queue the dashboard drives."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents import get_agent, list_agents
from src.db import get_session
from src.gateway import gateway
from src.gateway.service import GatewayError
from src.models import ActionRequest

router = APIRouter(tags=["actions"])


class ActionOut(BaseModel):
    id: str
    agent: str
    action_type: str
    summary: str
    payload: dict
    status: str
    result: str

    model_config = {"from_attributes": True}


class AuditOut(BaseModel):
    event: str
    detail: str
    created_at: str

    model_config = {"from_attributes": True}


class RejectIn(BaseModel):
    reason: str = ""


class DemoActionIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)


class AgentOut(BaseModel):
    name: str
    description: str
    allowed_actions: tuple[str, ...]


@router.get("/agents", response_model=list[AgentOut])
def get_agents():
    return list_agents()


@router.get("/actions", response_model=list[ActionOut])
async def list_actions(
    status: str | None = None, session: AsyncSession = Depends(get_session)
) -> list[ActionRequest]:
    return await gateway.list_requests(session, status)


@router.get("/actions/{request_id}/audit", response_model=list[AuditOut])
async def get_audit_trail(
    request_id: str, session: AsyncSession = Depends(get_session)
):
    events = await gateway.audit_trail(session, request_id)
    if not events:
        raise HTTPException(404, "No audit trail for that id")
    return [
        AuditOut(event=e.event, detail=e.detail, created_at=e.created_at.isoformat())
        for e in events
    ]


@router.post("/actions/{request_id}/approve", response_model=ActionOut)
async def approve_action(
    request_id: str, session: AsyncSession = Depends(get_session)
) -> ActionRequest:
    try:
        return await gateway.approve(session, request_id)
    except GatewayError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/actions/{request_id}/reject", response_model=ActionOut)
async def reject_action(
    request_id: str,
    body: RejectIn,
    session: AsyncSession = Depends(get_session),
) -> ActionRequest:
    try:
        return await gateway.reject(session, request_id, body.reason)
    except GatewayError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/actions/demo", response_model=ActionOut, status_code=201)
async def create_demo_action(
    body: DemoActionIn, session: AsyncSession = Depends(get_session)
) -> ActionRequest:
    """Let the demo agent request a (harmless) action, to exercise the queue."""
    agent = get_agent("demo")
    assert agent is not None  # registered at import time
    return await gateway.submit(
        session,
        agent=agent.name,
        action_type="demo.echo",
        summary=f"Echo the message {body.message!r} (demo of the approval flow)",
        payload={"message": body.message},
    )
