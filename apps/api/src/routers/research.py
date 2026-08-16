"""Research endpoints."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.llm import get_router
from src.llm.router import TaskClass
from src.memory import get_memory_service
from src.research import get_research_agent

router = APIRouter(prefix="/research", tags=["research"])


class ResearchIn(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    # 1 = search the question as asked; 2 = plan sub-questions first.
    depth: int = Field(default=2, ge=1, le=3)
    # Store what was found, so the work is not repeated next week.
    remember: bool = False


class EvidenceOut(BaseModel):
    content: str
    citation: str
    source: str
    score: float
    reference_id: str


class ResearchOut(BaseModel):
    question: str
    answer: str
    sub_questions: list[str]
    evidence: list[EvidenceOut]
    sources_searched: list[str]
    scope_note: str
    ran_on: str
    remembered: bool = False


@router.post("", response_model=ResearchOut)
async def research(
    body: ResearchIn,
    session: AsyncSession = Depends(get_session),
    model_router=Depends(get_router),
    memory_service=Depends(get_memory_service),
):
    """Research a question against ARIA's own knowledge.

    REASON class: synthesising evidence without drifting past it is exactly
    what a small local model is worst at, and drifting past the evidence is
    the one failure that makes a research agent harmful rather than merely
    unhelpful.
    """
    agent = get_research_agent(memory_service)
    routed = model_router.resolve(TaskClass.REASON, session)

    report = await agent.research(
        session, routed.provider, body.question, depth=body.depth
    )

    remembered = False
    if body.remember and report.has_evidence:
        # Stored as a note rather than a fact: it is ARIA's synthesis, not
        # something she was told, and the provenance says so.
        await memory_service.ingest(
            session,
            title=f"Research: {body.question[:150]}",
            content=(
                f"{report.answer}\n\nSources:\n"
                + "\n".join(f"- {e.citation}" for e in report.evidence)
            ),
            kind="note",
            explicit=True,
            provenance=(
                f"ARIA researched this on your request from "
                f"{len(report.evidence)} of your own sources"
            ),
        )
        remembered = True

    return ResearchOut(
        question=report.question,
        answer=report.answer,
        sub_questions=report.sub_questions,
        evidence=[
            EvidenceOut(
                content=e.content[:1500],
                citation=e.citation,
                source=e.source,
                score=e.score,
                reference_id=e.reference_id,
            )
            for e in report.evidence
        ],
        sources_searched=report.sources_searched,
        scope_note=report.scope_note,
        ran_on=routed.model,
        remembered=remembered,
    )


@router.get("/sources")
async def list_sources(memory_service=Depends(get_memory_service)):
    """What ARIA can currently search, and what she cannot.

    Exists so the limitation is discoverable rather than a surprise buried in
    an answer's footnote.
    """
    agent = get_research_agent(memory_service)
    return {
        "available": [s.name for s in agent._sources],
        "unavailable": ["web"],
        "note": (
            "ARIA cannot search the web: no search provider is configured. "
            "Adding one is a single adapter implementing SourceProvider plus "
            "an API key — see src/research/sources.py."
        ),
    }
