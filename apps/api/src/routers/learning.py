"""Learning coach endpoints: topic tracker + tutor tools."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents import learning
from src.db import get_session
from src.llm import get_router
from src.llm.router import TaskClass
from src.models import LearningTopic

router = APIRouter(prefix="/learning", tags=["learning"])

STATUSES = {"learning", "comfortable", "mastered"}


class TopicIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=5_000)


class TopicUpdate(BaseModel):
    status: str | None = None
    notes: str | None = Field(default=None, max_length=5_000)


class TopicOut(BaseModel):
    id: str
    name: str
    status: str
    notes: str

    model_config = {"from_attributes": True}


class ExplainIn(BaseModel):
    concept: str = Field(min_length=1, max_length=500)
    context: str = Field(default="", max_length=5_000)


class ReviewIn(BaseModel):
    code: str = Field(min_length=1, max_length=50_000)
    question: str = Field(default="", max_length=2_000)


class PathIn(BaseModel):
    goal: str = Field(min_length=1, max_length=1_000)


class TextOut(BaseModel):
    text: str


# ---------- topic tracker ----------

@router.post("/topics", response_model=TopicOut, status_code=201)
async def add_topic(body: TopicIn, session: AsyncSession = Depends(get_session)):
    topic = LearningTopic(**body.model_dump())
    session.add(topic)
    await session.commit()
    return topic


@router.get("/topics", response_model=list[TopicOut])
async def list_topics(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(LearningTopic).order_by(LearningTopic.created_at)
    )
    return list(result.scalars())


@router.patch("/topics/{topic_id}", response_model=TopicOut)
async def update_topic(
    topic_id: str, body: TopicUpdate, session: AsyncSession = Depends(get_session)
):
    topic = await session.get(LearningTopic, topic_id)
    if topic is None:
        raise HTTPException(404, "Topic not found")
    if body.status is not None:
        if body.status not in STATUSES:
            raise HTTPException(422, f"status must be one of {sorted(STATUSES)}")
        topic.status = body.status
    if body.notes is not None:
        topic.notes = body.notes
    await session.commit()
    return topic


@router.delete("/topics/{topic_id}", status_code=204)
async def delete_topic(topic_id: str, session: AsyncSession = Depends(get_session)):
    topic = await session.get(LearningTopic, topic_id)
    if topic is None:
        raise HTTPException(404, "Topic not found")
    await session.delete(topic)
    await session.commit()


# ---------- tutor tools ----------

@router.post("/explain", response_model=TextOut)
async def explain(
    body: ExplainIn,
    session: AsyncSession = Depends(get_session),
    model_router=Depends(get_router),
):
    # Teaching a beginner correctly is high-value: a wrong explanation is
    # worse than none, so this is REASON-class work.
    routed = model_router.resolve(TaskClass.REASON)
    text = await learning.explain(
        routed.provider, session, concept=body.concept, context=body.context
    )
    return TextOut(text=text)


@router.post("/review", response_model=TextOut)
async def review(
    body: ReviewIn,
    session: AsyncSession = Depends(get_session),
    model_router=Depends(get_router),
):
    routed = model_router.resolve(TaskClass.REASON)
    text = await learning.review_code(
        routed.provider, session, code=body.code, question=body.question
    )
    return TextOut(text=text)


@router.post("/path", response_model=TextOut)
async def path(
    body: PathIn,
    session: AsyncSession = Depends(get_session),
    model_router=Depends(get_router),
):
    routed = model_router.resolve(TaskClass.REASON)
    return TextOut(
        text=await learning.learning_path(routed.provider, session, goal=body.goal)
    )
