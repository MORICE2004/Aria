"""Where research findings can come from.

One interface, several implementations — the same shape as `llm/base.py`,
because it solved the same problem there: adding a fourth LLM vendor is one
file, and adding a web search provider should be too.

Every result carries enough to cite it. A finding ARIA cannot attribute is a
finding she should not report, so `SourceResult` has no optional citation
field — the citation is the point.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class SourceResult:
    """One piece of evidence, and where it came from."""

    content: str
    # Human-readable attribution: "your CV", "a note from March", "example.com".
    citation: str
    # Which source produced it, for grouping and for the UI.
    source: str
    # 0-1 relevance where the source can compute one. Sources that cannot
    # score honestly report 0.0 rather than inventing a number.
    score: float = 0.0
    # Lets the UI link back to the underlying thing.
    reference_id: str = ""


class SourceProvider(Protocol):
    """Something that can be searched for evidence."""

    name: str

    async def search(
        self, session: AsyncSession, query: str, *, limit: int = 5
    ) -> list[SourceResult]: ...


class MemorySource:
    """ARIA's semantic memory.

    Reuses the existing RAG service rather than reimplementing similarity
    search, so research and chat retrieve from exactly the same index — and
    improving one improves the other.
    """

    name = "memory"

    def __init__(self, memory_service):
        self._memory = memory_service

    async def search(
        self, session: AsyncSession, query: str, *, limit: int = 5
    ) -> list[SourceResult]:
        # MemoryService names this parameter `k`, not `limit` — the existing
        # RAG vocabulary, kept rather than changed to match this interface.
        hits = await self._memory.search(session, query, k=limit)
        return [
            SourceResult(
                content=hit.content,
                citation=f"your memory: {hit.title}",
                source=self.name,
                score=hit.score,
                reference_id=hit.item_id,
            )
            for hit in hits
        ]


class DocumentSource:
    """Uploaded documents, searched by keyword over their full text.

    Deliberately keyword rather than semantic: documents are ALSO in semantic
    memory via MemorySource, so doing embeddings again here would return the
    same passages twice and make a finding look doubly supported when it is
    supported once.

    Keyword search finds a different thing — exact terms, names, numbers —
    which is precisely what semantic search is worst at.
    """

    name = "documents"

    async def search(
        self, session: AsyncSession, query: str, *, limit: int = 5
    ) -> list[SourceResult]:
        from src.models import Document

        terms = [t for t in _keywords(query) if len(t) > 3]
        if not terms:
            return []

        documents = list(
            (await session.execute(select(Document))).scalars()
        )

        results: list[SourceResult] = []
        for document in documents:
            lowered = document.content.lower()
            matched = [t for t in terms if t in lowered]
            if not matched:
                continue
            excerpt = _excerpt_around(document.content, matched[0])
            results.append(
                SourceResult(
                    content=excerpt,
                    citation=f"your document: {document.filename}",
                    source=self.name,
                    # Fraction of the query's terms present. Honest and
                    # explainable, unlike a similarity number from nowhere.
                    score=round(len(matched) / len(terms), 3),
                    reference_id=document.id,
                )
            )

        results.sort(key=lambda r: -r.score)
        return results[:limit]


class ConversationSource:
    """What people have actually said to MORICE.

    Included because a surprising amount of what he knows arrived as a
    WhatsApp message rather than a document — and a research agent that cannot
    see the channel he actually uses would miss most of his life.
    """

    name = "conversations"

    async def search(
        self, session: AsyncSession, query: str, *, limit: int = 5
    ) -> list[SourceResult]:
        from src.models import Contact, WhatsAppMessage

        terms = [t for t in _keywords(query) if len(t) > 3]
        if not terms:
            return []

        rows = list(
            (
                await session.execute(
                    select(WhatsAppMessage, Contact)
                    .join(Contact, Contact.id == WhatsAppMessage.contact_id)
                    .order_by(WhatsAppMessage.sent_at.desc())
                    .limit(500)
                )
            ).all()
        )

        results: list[SourceResult] = []
        for message, contact in rows:
            lowered = message.body.lower()
            matched = [t for t in terms if t in lowered]
            if not matched:
                continue
            who = "you" if message.direction == "out" else contact.name
            results.append(
                SourceResult(
                    content=message.body,
                    citation=(
                        f"a message from {who} on "
                        f"{message.sent_at.date().isoformat()}"
                    ),
                    source=self.name,
                    score=round(len(matched) / len(terms), 3),
                    reference_id=message.id,
                )
            )

        results.sort(key=lambda r: -r.score)
        return results[:limit]


_STOPWORDS = {
    "what", "when", "where", "which", "who", "whom", "whose", "why", "how",
    "does", "did", "do", "is", "are", "was", "were", "the", "and", "for",
    "with", "about", "that", "this", "have", "has", "had", "from", "into",
    "your", "you", "my", "me", "i", "a", "an", "of", "to", "in", "on", "it",
}


def _keywords(query: str) -> list[str]:
    """Content words from a question.

    Without this, "what does my contract say about notice?" searches for
    "what", "does" and "my" and matches every document ever uploaded.
    """
    import re

    words = re.findall(r"[a-z0-9']+", query.lower())
    return [w for w in words if w not in _STOPWORDS]


def _excerpt_around(text: str, term: str, window: int = 400) -> str:
    """The passage around a match, not the whole document.

    A citation the size of a contract is not a citation.
    """
    position = text.lower().find(term)
    if position < 0:
        return text[:window]
    start = max(0, position - window // 2)
    end = min(len(text), position + window // 2)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"
