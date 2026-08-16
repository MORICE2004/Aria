"""Memory endpoints: add, list, search, and delete memories.

Privacy by default: the memory viewer exists so you can always see exactly
what ARIA knows — and delete anything, permanently.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.memory import get_memory_service
from src.memory.service import MemoryService
from src.models import MemoryItem

router = APIRouter(prefix="/memory", tags=["memory"])

ALLOWED_KINDS = {"note", "document", "fact", "style"}


class MemoryIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=500_000)
    kind: str = "note"
    # True when MORICE said "remember this" — overrides every heuristic.
    explicit: bool = False
    provenance: str = Field(default="", max_length=300)


class MemoryItemOut(BaseModel):
    id: str
    title: str
    kind: str
    content: str
    memory_type: str
    importance: float
    # Answers "why do you remember that?"
    provenance: str
    expires_at: datetime | None
    use_count: int

    model_config = {"from_attributes": True}


class SearchHitOut(BaseModel):
    item_id: str
    title: str
    kind: str
    content: str
    score: float


@router.post("", response_model=MemoryItemOut, status_code=201)
async def add_memory(
    body: MemoryIn,
    session: AsyncSession = Depends(get_session),
    memory: MemoryService = Depends(get_memory_service),
) -> MemoryItem:
    if body.kind not in ALLOWED_KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(ALLOWED_KINDS)}")
    return await memory.ingest(
        session,
        title=body.title,
        content=body.content,
        kind=body.kind,
        explicit=body.explicit,
        provenance=body.provenance,
    )


@router.get("", response_model=list[MemoryItemOut])
async def list_memories(
    memory_type: str | None = None, session: AsyncSession = Depends(get_session)
) -> list[MemoryItem]:
    """Most important first, so the list reads as a profile rather than a log."""
    query = select(MemoryItem).order_by(
        MemoryItem.importance.desc(), MemoryItem.created_at.desc()
    )
    if memory_type:
        query = query.where(MemoryItem.memory_type == memory_type)
    return list((await session.execute(query)).scalars())


@router.get("/expired", response_model=list[MemoryItemOut])
async def list_expired(session: AsyncSession = Depends(get_session)):
    """Memories past their lifetime — suggested for cleanup, never auto-deleted.

    ARIA proposes forgetting; MORICE decides. Silently deleting his data
    would be the same class of mistake as silently sending a message.
    """
    from src.memory.governance import is_expired

    rows = (await session.execute(select(MemoryItem))).scalars()
    return [m for m in rows if is_expired(m.expires_at)]


@router.post("/prune", status_code=200)
async def prune_expired(session: AsyncSession = Depends(get_session)) -> dict:
    """Delete everything currently expired. Explicitly invoked, never automatic."""
    from src.memory.governance import is_expired

    rows = list((await session.execute(select(MemoryItem))).scalars())
    doomed = [m for m in rows if is_expired(m.expires_at)]
    for m in doomed:
        await session.delete(m)
    await session.commit()
    return {"deleted": len(doomed), "titles": [m.title for m in doomed]}


@router.get("/search", response_model=list[SearchHitOut])
async def search_memories(
    q: str,
    session: AsyncSession = Depends(get_session),
    memory: MemoryService = Depends(get_memory_service),
):
    if not q.strip():
        raise HTTPException(422, "query must not be empty")
    return await memory.search(session, q)


@router.delete("/{item_id}", status_code=204)
async def delete_memory(
    item_id: str, session: AsyncSession = Depends(get_session)
) -> None:
    item = await session.get(MemoryItem, item_id)
    if item is None:
        raise HTTPException(404, "Memory not found")
    await session.delete(item)
    await session.commit()
