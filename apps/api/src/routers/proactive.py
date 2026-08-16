"""Proactive endpoints — what ARIA noticed, and whether she is still watching."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.models import Insight
from src.proactive import get_engine
from src.proactive.scheduler import scheduler_status

router = APIRouter(prefix="/proactive", tags=["proactive"])


class InsightOut(BaseModel):
    id: str
    key: str
    severity: str
    title: str
    detail: str
    link: str
    action: str
    status: str
    created_at: datetime
    last_seen_at: datetime

    model_config = {"from_attributes": True}


# Most severe first, then newest — so the thing that is actually on fire is
# never below a two-day-old FYI.
_SEVERITY_ORDER = {"urgent": 0, "attention": 1, "fyi": 2}


@router.get("", response_model=list[InsightOut])
async def list_insights(
    status: str = "open",
    session: AsyncSession = Depends(get_session),
):
    rows = list(
        (
            await session.execute(
                select(Insight)
                .where(Insight.status == status)
                .order_by(Insight.created_at.desc())
            )
        ).scalars()
    )
    return sorted(rows, key=lambda r: (_SEVERITY_ORDER.get(r.severity, 3),))


@router.post("/{insight_id}/dismiss", response_model=InsightOut)
async def dismiss_insight(
    insight_id: str, session: AsyncSession = Depends(get_session)
):
    """Acknowledge an insight.

    Dismissal is respected for a cooldown period rather than forever: a
    problem MORICE dismissed but never fixed should eventually be raised
    again, or ARIA would help him forget about it.
    """
    row = await session.get(Insight, insight_id)
    if row is None:
        raise HTTPException(404, "Insight not found")
    row.status = "dismissed"
    row.dismissed_at = datetime.now(timezone.utc)
    await session.commit()
    return row


@router.post("/run")
async def run_checks(session: AsyncSession = Depends(get_session)):
    """Run the checks now instead of waiting for the timer.

    Exists so the proactive engine can be exercised and tested deliberately,
    rather than by waiting five minutes and hoping.
    """
    new = await get_engine().run(session)
    return {"new_insights": len(new), "keys": [row.key for row in new]}


@router.get("/status")
async def status():
    """Is ARIA still watching?

    A background loop whose state nobody can see is a background loop that
    stops working without anyone noticing.
    """
    return scheduler_status()
