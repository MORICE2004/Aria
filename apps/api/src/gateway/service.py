"""The Action Gateway — ARIA's single door to the outside world.

Agents call `submit()` to REQUEST an action; it sits in the queue as
"pending". Only an explicit human decision (`approve` / `reject`) moves it
forward, and approval immediately runs the action's registered executor.
Every step is written to the append-only audit log.

Design guarantee: executors (the code that actually sends/submits things)
are looked up ONLY here, at approval time. There is no other code path that
can reach them — an agent, even a misbehaving one, can only ever enqueue.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import ActionRequest, AuditEvent

logger = logging.getLogger(__name__)

# An executor performs one action type, e.g. actually send an approved email.
# It receives the request's payload and returns a human-readable result.
Executor = Callable[[dict], Awaitable[str]]

_executors: dict[str, Executor] = {}


def register_executor(action_type: str) -> Callable[[Executor], Executor]:
    """Decorator: register the function that executes one action type.

    Usage:
        @register_executor("email.send")
        async def send_email(payload: dict) -> str: ...
    """

    def decorator(func: Executor) -> Executor:
        if action_type in _executors:
            raise ValueError(f"Executor for {action_type!r} already registered")
        _executors[action_type] = func
        return func

    return decorator


class GatewayError(Exception):
    """Raised for invalid gateway operations (unknown type, bad state...)."""


class ActionGateway:
    async def submit(
        self,
        session: AsyncSession,
        *,
        agent: str,
        action_type: str,
        summary: str,
        payload: dict,
    ) -> ActionRequest:
        """Enqueue a sensitive action for human review."""
        if action_type not in _executors:
            # Fail at submit time, not approval time: an action nobody can
            # execute must never sit in the queue looking approvable.
            raise GatewayError(f"No executor registered for {action_type!r}")

        request = ActionRequest(
            agent=agent, action_type=action_type, summary=summary, payload=payload
        )
        session.add(request)
        await session.flush()
        session.add(
            AuditEvent(
                action_request_id=request.id,
                event="submitted",
                detail=f"{agent} requested {action_type}: {summary}",
            )
        )
        await session.commit()
        logger.info("Action submitted: %s %s (%s)", agent, action_type, request.id)
        return request

    async def approve(self, session: AsyncSession, request_id: str) -> ActionRequest:
        """Human said yes: mark approved, run the executor, record the outcome."""
        request = await self._get_pending(session, request_id)
        request.status = "approved"
        request.decided_at = datetime.now(timezone.utc)
        session.add(AuditEvent(action_request_id=request.id, event="approved"))
        await session.commit()

        try:
            result = await _executors[request.action_type](request.payload)
            request.status = "executed"
            request.result = result
            session.add(
                AuditEvent(action_request_id=request.id, event="executed", detail=result)
            )
        except Exception as exc:  # noqa: BLE001 — outcome must be recorded, whatever failed
            request.status = "failed"
            request.result = f"{type(exc).__name__}: {exc}"
            session.add(
                AuditEvent(
                    action_request_id=request.id, event="failed", detail=request.result
                )
            )
            logger.exception("Executor failed for action %s", request.id)
        await session.commit()
        return request

    async def reject(
        self, session: AsyncSession, request_id: str, reason: str = ""
    ) -> ActionRequest:
        """Human said no: nothing executes, decision is recorded."""
        request = await self._get_pending(session, request_id)
        request.status = "rejected"
        request.decided_at = datetime.now(timezone.utc)
        session.add(
            AuditEvent(action_request_id=request.id, event="rejected", detail=reason)
        )
        await session.commit()
        return request

    async def list_requests(
        self, session: AsyncSession, status: str | None = None
    ) -> list[ActionRequest]:
        query = select(ActionRequest).order_by(ActionRequest.created_at.desc())
        if status:
            query = query.where(ActionRequest.status == status)
        return list((await session.execute(query)).scalars())

    async def audit_trail(
        self, session: AsyncSession, request_id: str
    ) -> list[AuditEvent]:
        result = await session.execute(
            select(AuditEvent)
            .where(AuditEvent.action_request_id == request_id)
            .order_by(AuditEvent.created_at)
        )
        return list(result.scalars())

    async def _get_pending(
        self, session: AsyncSession, request_id: str
    ) -> ActionRequest:
        request = await session.get(ActionRequest, request_id)
        if request is None:
            raise GatewayError("Action request not found")
        if request.status != "pending":
            # Approving twice must be impossible — an action runs at most once.
            raise GatewayError(f"Action is {request.status}, not pending")
        return request
