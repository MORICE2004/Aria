"""Job tracker endpoints: applications CRUD, AI analysis, drafts, recruiters."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents import jobsearch
from src.db import get_session
from src.llm import get_router
from src.llm.router import TaskClass
from src.memory import get_memory_service
from src.memory.service import MemoryService
from src.models import JobApplication, RecruiterContact

router = APIRouter(tags=["jobs"])

STATUSES = {"saved", "applied", "interview", "offer", "rejected"}


# ---------- shapes ----------

class JobIn(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=200)
    url: str = Field(default="", max_length=1000)
    description: str = Field(default="", max_length=100_000)


class JobUpdate(BaseModel):
    status: str | None = None
    notes: str | None = Field(default=None, max_length=50_000)
    description: str | None = Field(default=None, max_length=100_000)


class JobOut(BaseModel):
    id: str
    company: str
    role: str
    url: str
    description: str
    status: str
    notes: str
    match_score: int | None
    match_notes: str
    cover_letter: str

    model_config = {"from_attributes": True}


class CoverLetterIn(BaseModel):
    extra: str = Field(default="", max_length=2000)


class TextOut(BaseModel):
    text: str


class RecruiterIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    company: str = Field(default="", max_length=200)
    email: EmailStr | None = None
    notes: str = Field(default="", max_length=10_000)


class RecruiterOut(BaseModel):
    id: str
    name: str
    company: str
    email: str
    notes: str

    model_config = {"from_attributes": True}


# ---------- applications ----------

@router.post("/jobs", response_model=JobOut, status_code=201)
async def add_job(body: JobIn, session: AsyncSession = Depends(get_session)):
    job = JobApplication(**body.model_dump())
    session.add(job)
    await session.commit()
    return job


@router.get("/jobs", response_model=list[JobOut])
async def list_jobs(
    status: str | None = None, session: AsyncSession = Depends(get_session)
):
    query = select(JobApplication).order_by(JobApplication.created_at.desc())
    if status:
        query = query.where(JobApplication.status == status)
    return list((await session.execute(query)).scalars())


@router.patch("/jobs/{job_id}", response_model=JobOut)
async def update_job(
    job_id: str, body: JobUpdate, session: AsyncSession = Depends(get_session)
):
    job = await _get_job(session, job_id)
    if body.status is not None:
        if body.status not in STATUSES:
            raise HTTPException(422, f"status must be one of {sorted(STATUSES)}")
        job.status = body.status
    if body.notes is not None:
        job.notes = body.notes
    if body.description is not None:
        job.description = body.description
    await session.commit()
    return job


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(job_id: str, session: AsyncSession = Depends(get_session)):
    job = await _get_job(session, job_id)
    await session.delete(job)
    await session.commit()


# ---------- AI assistance ----------

@router.post("/jobs/{job_id}/analyze", response_model=JobOut)
async def analyze_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    model_router=Depends(get_router),
    memory: MemoryService = Depends(get_memory_service),
):
    """Score the posting against MORICE's profile; stores score + notes."""
    job = await _get_job(session, job_id)
    if not job.description.strip():
        raise HTTPException(422, "Add the job description first, then analyze.")
    # Fit scoring must produce valid JSON and sound judgement — REASON-class,
    # so it goes to the cloud model rather than a small local one.
    routed = model_router.resolve(TaskClass.REASON, session)
    job.match_score, job.match_notes = await jobsearch.analyze(
        routed.provider, memory, session, description=job.description
    )
    await session.commit()
    return job


@router.post("/jobs/{job_id}/cover-letter", response_model=JobOut)
async def draft_cover_letter(
    job_id: str,
    body: CoverLetterIn,
    session: AsyncSession = Depends(get_session),
    model_router=Depends(get_router),
    memory: MemoryService = Depends(get_memory_service),
):
    job = await _get_job(session, job_id)
    if not job.description.strip():
        raise HTTPException(422, "Add the job description first.")
    # A cover letter is high-stakes writing — worth the stronger model.
    routed = model_router.resolve(TaskClass.REASON, session)
    job.cover_letter = await jobsearch.cover_letter(
        routed.provider, memory, session, description=job.description, extra=body.extra
    )
    await session.commit()
    return job


@router.post("/jobs/{job_id}/interview-prep", response_model=TextOut)
async def interview_prep(
    job_id: str,
    session: AsyncSession = Depends(get_session),
    model_router=Depends(get_router),
    memory: MemoryService = Depends(get_memory_service),
):
    job = await _get_job(session, job_id)
    if not job.description.strip():
        raise HTTPException(422, "Add the job description first.")
    routed = model_router.resolve(TaskClass.REASON, session)
    text = await jobsearch.interview_prep(
        routed.provider, memory, session, description=job.description
    )
    return TextOut(text=text)


# ---------- recruiters ----------

@router.post("/recruiters", response_model=RecruiterOut, status_code=201)
async def add_recruiter(
    body: RecruiterIn, session: AsyncSession = Depends(get_session)
):
    contact = RecruiterContact(
        name=body.name,
        company=body.company,
        email=str(body.email) if body.email else "",
        notes=body.notes,
    )
    session.add(contact)
    await session.commit()
    return contact


@router.get("/recruiters", response_model=list[RecruiterOut])
async def list_recruiters(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(RecruiterContact).order_by(RecruiterContact.created_at.desc())
    )
    return list(result.scalars())


@router.delete("/recruiters/{contact_id}", status_code=204)
async def delete_recruiter(
    contact_id: str, session: AsyncSession = Depends(get_session)
):
    contact = await session.get(RecruiterContact, contact_id)
    if contact is None:
        raise HTTPException(404, "Recruiter not found")
    await session.delete(contact)
    await session.commit()


async def _get_job(session: AsyncSession, job_id: str) -> JobApplication:
    job = await session.get(JobApplication, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job
