"""The briefing endpoint — "ARIA, what happened while I was away?"

Kept in its own router rather than folded into /proactive because it answers a
different question: /proactive is a list of standing concerns, this is an
account of a period. See `src/proactive/briefing.py` for why that distinction
decides what appears here.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.proactive import briefing as briefing_service

router = APIRouter(prefix="/briefing", tags=["briefing"])


class ItemOut(BaseModel):
    title: str
    detail: str
    link: str
    reference_id: str


class SectionOut(BaseModel):
    key: str
    heading: str
    summary: str
    needs_attention: bool
    items: list[ItemOut]


class BriefingOut(BaseModel):
    since: datetime
    until: datetime
    hours: float
    headline: str
    quiet: bool
    sections: list[SectionOut]


@router.get("", response_model=BriefingOut)
async def get_briefing(
    hours: float = Query(
        default=briefing_service.DEFAULT_HOURS,
        gt=0,
        le=24 * 30,
        description="How far back to look. A day by default.",
    ),
    session: AsyncSession = Depends(get_session),
):
    """What arrived, what ARIA did, what she is waiting on, and what it cost.

    Assembled from records, never summarised by a model: this is the one report
    that has to be trustworthy about what ARIA did in MORICE's name while he
    was not watching. `quiet` is true when genuinely nothing happened, which is
    a real answer and not an error.
    """
    result = await briefing_service.build(session, hours=hours)
    return BriefingOut(
        since=result.since,
        until=result.until,
        hours=result.hours,
        headline=result.headline,
        quiet=result.quiet,
        sections=[
            SectionOut(
                key=section.key,
                heading=section.heading,
                summary=section.summary,
                needs_attention=section.needs_attention,
                items=[
                    ItemOut(
                        title=item.title,
                        detail=item.detail,
                        link=item.link,
                        reference_id=item.reference_id,
                    )
                    for item in section.items
                ],
            )
            for section in result.sections
        ],
    )
