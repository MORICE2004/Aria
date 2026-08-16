"""Memory service: ingest, search, delete.

Search strategy depends on the database:
  - PostgreSQL: pgvector does the similarity math IN the database (fast,
    scales to millions of chunks).
  - SQLite (tests only): cosine similarity computed in Python over all
    chunks — identical results, no Postgres required.
"""

import logging
import math
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.memory.chunking import chunk_text
from src.memory.embeddings import EmbeddingProvider
from src.models import MemoryChunk, MemoryItem

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchHit:
    """One retrieved memory chunk with its source item and match score (0-1)."""

    item_id: str
    title: str
    kind: str
    content: str
    score: float


class MemoryService:
    def __init__(self, embedder: EmbeddingProvider) -> None:
        self._embedder = embedder

    async def ingest(
        self,
        session: AsyncSession,
        *,
        title: str,
        content: str,
        kind: str,
        explicit: bool = False,
        provenance: str = "",
    ) -> MemoryItem:
        """Store a memory item: judge it, chunk it, embed the chunks, save.

        Governance runs first so every memory carries a type, an importance
        score, a lifetime, and a reason it exists.
        """
        from src.memory import governance

        verdict = governance.judge(
            title=title, content=content, kind=kind, explicit=explicit
        )
        item = MemoryItem(
            title=title,
            kind=kind,
            content=content,
            memory_type=verdict.memory_type,
            importance=verdict.importance,
            expires_at=verdict.expires_at,
            provenance=provenance or verdict.reason,
        )
        session.add(item)
        await session.flush()  # assigns item.id before we reference it below

        chunks = chunk_text(content)
        if chunks:
            vectors = self._embedder.embed(chunks)
            for text, vector in zip(chunks, vectors):
                session.add(
                    MemoryChunk(item_id=item.id, content=text, embedding=vector)
                )
        await session.commit()
        logger.info("Ingested memory %r (%d chunks)", title, len(chunks))
        return item

    async def search(
        self, session: AsyncSession, query: str, k: int = 4
    ) -> list[SearchHit]:
        """Return the k chunks whose meaning is closest to the query."""
        query_vector = self._embedder.embed([query])[0]

        if session.bind.dialect.name == "postgresql":
            distance = MemoryChunk.embedding.cosine_distance(query_vector)
            result = await session.execute(
                select(MemoryChunk, MemoryItem, distance.label("distance"))
                .join(MemoryItem, MemoryChunk.item_id == MemoryItem.id)
                .order_by(distance)
                .limit(k)
            )
            return [
                SearchHit(
                    item_id=item.id,
                    title=item.title,
                    kind=item.kind,
                    content=chunk.content,
                    score=round(1.0 - dist, 4),
                )
                for chunk, item, dist in result.all()
            ]

        # SQLite fallback (tests): score everything in Python.
        result = await session.execute(
            select(MemoryChunk, MemoryItem).join(
                MemoryItem, MemoryChunk.item_id == MemoryItem.id
            )
        )
        scored = [
            SearchHit(
                item_id=item.id,
                title=item.title,
                kind=item.kind,
                content=chunk.content,
                score=round(_cosine_similarity(query_vector, chunk.embedding), 4),
            )
            for chunk, item in result.all()
        ]
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:k]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0
