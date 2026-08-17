"""Communication profile endpoints — inspect, teach, and correct ARIA's
understanding of how MORICE writes.

Everything is inspectable and reversible: he can see each pattern, the
evidence behind it, and delete any of it.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.communication import learning, style
from src.db import get_session
from src.memory import get_memory_service
from src.models import Contact

router = APIRouter(prefix="/style", tags=["style"])

FEEDBACK_KINDS = {"approved", "edited", "rejected"}


class PatternOut(BaseModel):
    id: str
    dimension: str
    scope: str
    value: str
    confidence: float
    evidence_count: int
    source: str

    model_config = {"from_attributes": True}


class ProfileOut(BaseModel):
    patterns: list[PatternOut]
    # Exactly what gets injected into drafting prompts — no hidden influence.
    prompt_block: str


class FeedbackIn(BaseModel):
    kind: str
    draft: str = Field(default="", max_length=20_000)
    final: str = Field(default="", max_length=20_000)
    contact_id: str | None = None
    note: str = Field(default="", max_length=2_000)


class FeedbackOut(BaseModel):
    recorded: bool
    # What ARIA actually took away — learning is never silent.
    lessons: list[str]


class RuleIn(BaseModel):
    rule: str = Field(min_length=3, max_length=500)
    contact_id: str | None = None


class RefreshOut(BaseModel):
    dimensions: dict[str, str]
    sample_size: int


@router.get("", response_model=ProfileOut)
async def get_profile(
    contact_id: str | None = None, session: AsyncSession = Depends(get_session)
):
    """The learned profile, plus the exact text ARIA uses when drafting."""
    contact = await session.get(Contact, contact_id) if contact_id else None
    patterns = await learning.list_patterns(session)
    block = await learning.build_profile_block(session, contact)
    return ProfileOut(patterns=patterns, prompt_block=block)


@router.post("/refresh", response_model=RefreshOut)
async def refresh(
    contact_id: str | None = None, session: AsyncSession = Depends(get_session)
):
    """Re-measure style from observed messages MORICE actually wrote."""
    contact = await session.get(Contact, contact_id) if contact_id else None
    dimensions = await learning.refresh_from_messages(session, contact)
    # sample_size is embedded in the stored evidence counts; report it plainly.
    patterns = await learning.list_patterns(
        session, learning.scope_for_contact(contact)
    )
    sample = max((p.evidence_count for p in patterns), default=0)
    return RefreshOut(dimensions=dimensions, sample_size=sample)


class SamplesIn(BaseModel):
    """Real messages MORICE has sent, pasted in bulk."""

    # One message per line. Pasting a WhatsApp export or a handful of recent
    # replies is the fastest honest way to teach ARIA a voice.
    text: str = Field(min_length=1, max_length=100_000)
    label: str = Field(default="pasted messages", max_length=200)


class SamplesOut(BaseModel):
    added: int
    total_samples: int
    confidence: float
    ready_for_autonomy: bool
    note: str


@router.post("/samples", response_model=SamplesOut, status_code=201)
async def add_samples(
    body: SamplesIn,
    session: AsyncSession = Depends(get_session),
    memory_service=Depends(get_memory_service),
):
    """Teach ARIA your voice from messages you have actually written.

    This exists because of a real bottleneck: ARIA learns a writing voice only
    from WhatsApp messages she has observed, which means a new install cannot
    reach the confidence needed for autonomy until weeks of conversation have
    flowed past. Pasting messages you really sent is the same evidence,
    gathered faster.

    Deliberately NOT a generator. ARIA will not invent samples of how MORICE
    writes, because inventing them would train her to imitate a voice he does
    not have — and then send it, in his name, to real people. Every sample
    here must be text he actually wrote.
    """
    lines = [line.strip() for line in body.text.splitlines() if line.strip()]
    if not lines:
        raise HTTPException(422, "No messages found — one message per line.")

    # Stored as a style memory so the sample is inspectable and deletable
    # like everything else ARIA knows, rather than vanishing into statistics.
    await memory_service.ingest(
        session,
        title=f"Writing samples: {body.label}",
        content="\n".join(lines),
        kind="style",
        explicit=True,
        provenance="you pasted these as examples of how you write",
    )

    await learning.refresh_from_messages(session)
    state = await _voice_state(session)

    return SamplesOut(
        added=len(lines),
        total_samples=state["samples"],
        confidence=state["confidence"],
        ready_for_autonomy=state["ready_for_autonomy"],
        note=(
            "ARIA now writes like you confidently enough to reply unattended, "
            "for contacts where you have enabled it."
            if state["ready_for_autonomy"]
            else f"About {state['samples_needed']} more of your messages would "
            "reach the confidence needed for autonomous replies."
        ),
    )


async def _voice_state(session: AsyncSession) -> dict:
    """Sample count and the confidence the autonomy engine actually applies.

    Deliberately calls the engine's own function rather than recomputing from
    the sample count. Those two numbers drift apart — patterns carry different
    weights, explicit rules score higher than measured ones — and a dashboard
    showing a different figure from the one that gates sending is worse than
    showing nothing at all.
    """
    from src.whatsapp import decision

    texts = await learning.collect_own_writing(session)
    confidence = await decision.communication_confidence(session)
    target = learning.samples_needed_for(decision.MIN_CONFIDENCE_FOR_AUTONOMY)
    return {
        "samples": len(texts),
        "confidence": confidence,
        "required_confidence": decision.MIN_CONFIDENCE_FOR_AUTONOMY,
        "samples_needed": max(0, target - len(texts)),
        "ready_for_autonomy": confidence >= decision.MIN_CONFIDENCE_FOR_AUTONOMY,
    }


@router.get("/readiness")
async def voice_readiness(session: AsyncSession = Depends(get_session)):
    """How close ARIA is to writing convincingly as MORICE.

    Reports the same number the autonomy engine gates on.
    """
    return await _voice_state(session)


@router.post("/feedback", response_model=FeedbackOut, status_code=201)
async def feedback(body: FeedbackIn, session: AsyncSession = Depends(get_session)):
    """Record what MORICE did with a draft, and learn from any edit."""
    if body.kind not in FEEDBACK_KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(FEEDBACK_KINDS)}")
    _, lessons = await learning.record_feedback(
        session,
        kind=body.kind,
        draft=body.draft,
        final=body.final,
        contact_id=body.contact_id,
        note=body.note,
    )
    return FeedbackOut(recorded=True, lessons=lessons)


@router.post("/rules", response_model=PatternOut, status_code=201)
async def add_rule(body: RuleIn, session: AsyncSession = Depends(get_session)):
    """Training mode: state a preference directly, e.g.
    'Never use Dear Sir/Madam'. Stored at high confidence — he said it."""
    return await learning.add_rule(
        session, rule=body.rule, contact_id=body.contact_id
    )


@router.delete("/patterns/{pattern_id}", status_code=204)
async def forget(pattern_id: str, session: AsyncSession = Depends(get_session)):
    """Forget a learned pattern. ARIA must be correctable."""
    if not await learning.forget_pattern(session, pattern_id):
        raise HTTPException(404, "Pattern not found")


class PreviewIn(BaseModel):
    draft: str = Field(min_length=1, max_length=20_000)
    final: str = Field(min_length=1, max_length=20_000)


@router.post("/preview-lessons", response_model=FeedbackOut)
async def preview_lessons(body: PreviewIn):
    """Show what ARIA WOULD learn from an edit, without recording it.

    Lets MORICE see the learning rule before trusting it.
    """
    return FeedbackOut(recorded=False, lessons=style.diff_summary(body.draft, body.final))
