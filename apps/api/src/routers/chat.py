"""Chat endpoints.

Flow for sending a message:
  1. Save the user's message to the database.
  2. Send the whole conversation to the LLM and stream the reply to the
     browser chunk by chunk (Server-Sent Events style).
  3. When the stream ends, save the assistant's full reply.

If the stream is interrupted, whatever was generated so far is still saved,
so history never silently loses an exchange.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import SessionMaker, get_session
from src.llm import get_router
from src.llm.base import ChatMessage
from src.llm.router import TaskClass
from src.memory import get_memory_service
from src.memory.service import MemoryService
from src.models import Conversation, Message

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/conversations", tags=["chat"])

SYSTEM_PROMPT = (
    "You are ARIA, MORICE's personal AI assistant. Be concise, warm, and "
    "practical. MORICE is a beginner programmer: when a technical topic comes "
    "up, explain it simply and never assume prior knowledge."
)


# ---------- request/response shapes (validated by FastAPI) ----------

class ConversationOut(BaseModel):
    id: str
    title: str

    model_config = {"from_attributes": True}  # allows building from DB objects


class MessageOut(BaseModel):
    id: str
    role: str
    content: str

    model_config = {"from_attributes": True}


class SendMessageIn(BaseModel):
    # min/max length: reject empty spam and absurdly large payloads at the boundary.
    content: str = Field(min_length=1, max_length=32_000)


# ---------- endpoints ----------

@router.post("", response_model=ConversationOut, status_code=201)
async def create_conversation(
    session: AsyncSession = Depends(get_session),
) -> Conversation:
    conversation = Conversation()
    session.add(conversation)
    await session.commit()
    return conversation


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    session: AsyncSession = Depends(get_session),
) -> list[Conversation]:
    result = await session.execute(
        select(Conversation).order_by(Conversation.created_at.desc())
    )
    return list(result.scalars())


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: str, session: AsyncSession = Depends(get_session)
) -> list[Message]:
    await _get_conversation_or_404(session, conversation_id)
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    return list(result.scalars())


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: SendMessageIn,
    session: AsyncSession = Depends(get_session),
    model_router=Depends(get_router),
    memory: MemoryService = Depends(get_memory_service),
) -> StreamingResponse:
    """Save the user message, then stream the assistant's reply as plain text."""
    conversation = await _get_conversation_or_404(session, conversation_id)

    # RAG: fetch memories relevant to this message and give them to the model.
    # Only well-matching hits are included — irrelevant context hurts quality.
    hits = await memory.search(session, body.content, k=4)
    relevant = [h for h in hits if h.score >= 0.55]
    system_prompt = SYSTEM_PROMPT
    if relevant:
        memory_block = "\n\n".join(
            f"[{h.kind}: {h.title}]\n{h.content}" for h in relevant
        )
        system_prompt += (
            "\n\nRelevant entries from MORICE's personal memory (use them when "
            "helpful; do not invent memories that are not listed):\n" + memory_block
        )

    # Load prior history BEFORE adding the new message, then append it.
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    history = [ChatMessage(role=m.role, content=m.content) for m in result.scalars()]
    history.append(ChatMessage(role="user", content=body.content))

    session.add(Message(conversation_id=conversation_id, role="user", content=body.content))
    # First message? Use its opening words as the conversation title.
    if not conversation.title or conversation.title == "New conversation":
        conversation.title = body.content[:60]
    await session.commit()

    # Conversation is CONVERSE-class work: local by default (free and private),
    # cloud if CONVERSE_LOCAL=false.
    routed = model_router.resolve(TaskClass.CONVERSE)

    async def stream():
        """Yield chunks to the browser; persist the full reply at the end."""
        parts: list[str] = []
        try:
            async for chunk in routed.provider.stream_chat(
                history, system=system_prompt
            ):
                parts.append(chunk)
                yield chunk
        finally:
            # Runs even if the client disconnects mid-stream. The request's
            # session may be closed by then, so persist with a fresh one.
            if parts:
                async with SessionMaker() as s:
                    s.add(
                        Message(
                            conversation_id=conversation_id,
                            role="assistant",
                            content="".join(parts),
                        )
                    )
                    await s.commit()

    return StreamingResponse(stream(), media_type="text/plain; charset=utf-8")


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: str, session: AsyncSession = Depends(get_session)
) -> None:
    conversation = await _get_conversation_or_404(session, conversation_id)
    await session.delete(conversation)
    await session.commit()


async def _get_conversation_or_404(
    session: AsyncSession, conversation_id: str
) -> Conversation:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation
