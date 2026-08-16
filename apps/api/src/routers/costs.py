"""Cost and usage reporting.

Answers "what have I spent, and how much of my work stayed local?" — the two
questions the model router exists to improve.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.llm import costs

router = APIRouter(prefix="/costs", tags=["costs"])


@router.get("")
async def usage_summary(session: AsyncSession = Depends(get_session)) -> dict:
    """Usage by period and by model.

    Token counts are exact (reported by the provider). Costs are estimates
    from a published price table and are labelled as such in the response.
    """
    return await costs.summary(session)
