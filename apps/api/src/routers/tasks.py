"""Task endpoints: tasks, reminders, and deadlines.

`GET /tasks` returns open items sorted by urgency (dated first, soonest
first) so the UI's Overdue / Today / Upcoming grouping is trivial.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.models import Task

router = APIRouter(prefix="/tasks", tags=["tasks"])

KINDS = {"task", "reminder", "deadline", "interview"}


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    notes: str = Field(default="", max_length=10_000)
    kind: str = "task"
    due_at: datetime | None = None
    job_id: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    notes: str | None = None
    status: str | None = None
    due_at: datetime | None = None


class TaskOut(BaseModel):
    id: str
    title: str
    notes: str
    kind: str
    status: str
    due_at: datetime | None
    job_id: str | None

    model_config = {"from_attributes": True}


@router.post("", response_model=TaskOut, status_code=201)
async def add_task(body: TaskIn, session: AsyncSession = Depends(get_session)):
    if body.kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(KINDS)}")
    task = Task(**body.model_dump())
    session.add(task)
    await session.commit()
    return task


@router.get("", response_model=list[TaskOut])
async def list_tasks(
    status: str | None = None, session: AsyncSession = Depends(get_session)
):
    query = select(Task)
    if status:
        query = query.where(Task.status == status)
    # Urgency order: items with a due date first (soonest on top), then
    # undated ones, newest first.
    query = query.order_by(
        Task.due_at.is_(None), Task.due_at, Task.created_at.desc()
    )
    return list((await session.execute(query)).scalars())


@router.patch("/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: str, body: TaskUpdate, session: AsyncSession = Depends(get_session)
):
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    if body.status is not None:
        if body.status not in {"open", "done"}:
            raise HTTPException(422, "status must be 'open' or 'done'")
        task.status = body.status
    if body.title is not None:
        task.title = body.title
    if body.notes is not None:
        task.notes = body.notes
    if body.due_at is not None:
        task.due_at = body.due_at
    await session.commit()
    return task


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: str, session: AsyncSession = Depends(get_session)):
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    await session.delete(task)
    await session.commit()
