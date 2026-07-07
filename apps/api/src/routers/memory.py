"""Memory endpoints: add, list, search, and delete memories.

Privacy by default: the memory viewer exists so you can always see exactly
what ARIA knows — and delete anything, permanently.
"""

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


class MemoryItemOut(BaseModel):
    id: str
    title: str
    kind: str
    content: str

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
        session, title=body.title, content=body.content, kind=body.kind
    )


@router.get("", response_model=list[MemoryItemOut])
async def list_memories(session: AsyncSession = Depends(get_session)) -> list[MemoryItem]:
    result = await session.execute(
        select(MemoryItem).order_by(MemoryItem.created_at.desc())
    )
    return list(result.scalars())


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
