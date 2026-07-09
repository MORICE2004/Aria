"""Communication endpoints: draft, summarize, and request-to-send-email."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents import communication as agent
from src.db import get_session
from src.gateway import gateway
from src.llm import get_llm_provider
from src.llm.base import LLMProvider
from src.memory import get_memory_service
from src.memory.service import MemoryService
from src.routers.actions import ActionOut

router = APIRouter(prefix="/communication", tags=["communication"])

Platform = agent.PLATFORM_HINTS.keys()


class DraftIn(BaseModel):
    platform: str = Field(pattern="^(whatsapp|instagram|linkedin|email)$")
    conversation: str = Field(min_length=1, max_length=50_000)
    instructions: str = Field(default="", max_length=2_000)


class TextOut(BaseModel):
    text: str


class SummarizeIn(BaseModel):
    conversation: str = Field(min_length=1, max_length=100_000)


class EmailRequestIn(BaseModel):
    to: EmailStr           # validated as a real email address shape
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=100_000)


@router.post("/draft", response_model=TextOut)
async def draft(
    body: DraftIn,
    session: AsyncSession = Depends(get_session),
    llm: LLMProvider = Depends(get_llm_provider),
    memory: MemoryService = Depends(get_memory_service),
) -> TextOut:
    text = await agent.draft_reply(
        llm,
        memory,
        session,
        platform=body.platform,
        conversation=body.conversation,
        instructions=body.instructions,
    )
    return TextOut(text=text)


@router.post("/summarize", response_model=TextOut)
async def summarize(
    body: SummarizeIn, llm: LLMProvider = Depends(get_llm_provider)
) -> TextOut:
    return TextOut(text=await agent.summarize(llm, conversation=body.conversation))


class InboxMessageOut(BaseModel):
    sender: str
    subject: str
    date: str
    snippet: str


@router.get("/inbox", response_model=list[InboxMessageOut])
async def read_inbox():
    """Recent unread emails (read-only — never marks anything as read)."""
    from fastapi import HTTPException

    from src.integrations import inbox

    try:
        messages = await inbox.fetch_unread(limit=10)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return [
        InboxMessageOut(
            sender=m.sender, subject=m.subject, date=m.date, snippet=m.snippet
        )
        for m in messages
    ]


@router.post("/email-request", response_model=ActionOut, status_code=201)
async def request_email_send(
    body: EmailRequestIn, session: AsyncSession = Depends(get_session)
):
    """Enqueue an email for approval. NOTHING is sent by this endpoint —
    the email goes out only if approved on the Approvals page."""
    return await gateway.submit(
        session,
        agent="communication",
        action_type="email.send",
        summary=f"Send email to {body.to}: {body.subject!r}",
        payload={"to": str(body.to), "subject": body.subject, "body": body.body},
    )
