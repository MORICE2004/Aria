"""Notifications: one endpoint aggregating everything that needs attention.

Sources: unread emails (if IMAP is configured), actions awaiting approval,
and tasks due today or overdue. The dashboard polls this and raises browser
notifications for new items.
"""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.integrations import inbox
from src.models import ActionRequest, Task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/notifications", tags=["notifications"])


class EmailNotification(BaseModel):
    sender: str
    subject: str
    snippet: str


class DueTask(BaseModel):
    id: str
    title: str
    due_at: datetime | None
    overdue: bool


class NotificationsOut(BaseModel):
    pending_approvals: int
    due_tasks: list[DueTask]
    # None = IMAP not configured (distinct from "zero unread emails").
    unread_emails: list[EmailNotification] | None
    email_error: str | None


@router.get("", response_model=NotificationsOut)
async def get_notifications(
    session: AsyncSession = Depends(get_session),
) -> NotificationsOut:
    now = datetime.now(timezone.utc)

    pending = (
        await session.execute(
            select(func.count())
            .select_from(ActionRequest)
            .where(ActionRequest.status == "pending")
        )
    ).scalar_one()

    end_of_today = now + timedelta(days=1)
    due_rows = (
        await session.execute(
            select(Task)
            .where(Task.status == "open", Task.due_at.is_not(None),
                   Task.due_at <= end_of_today)
            .order_by(Task.due_at)
        )
    ).scalars()
    due_tasks = [
        DueTask(
            id=t.id,
            title=t.title,
            due_at=t.due_at,
            overdue=t.due_at is not None
            and t.due_at.replace(tzinfo=t.due_at.tzinfo or timezone.utc) < now,
        )
        for t in due_rows
    ]

    unread: list[EmailNotification] | None = None
    email_error: str | None = None
    try:
        unread = [
            EmailNotification(sender=m.sender, subject=m.subject, snippet=m.snippet)
            for m in await inbox.fetch_unread(limit=10)
        ]
    except RuntimeError as exc:  # not configured — expected, not an error state
        email_error = str(exc)
    except Exception as exc:  # noqa: BLE001 — report, don't break the whole panel
        email_error = f"Inbox check failed: {exc}"
        logger.warning("IMAP fetch failed: %s", exc)

    return NotificationsOut(
        pending_approvals=pending,
        due_tasks=due_tasks,
        unread_emails=unread,
        email_error=email_error,
    )
