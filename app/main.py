"""
FastAPI application entry point.

Endpoints:
  POST /jobs/upload              – Upload CSV, enqueue job
  GET  /jobs/{job_id}/status     – Poll job status
  GET  /jobs/{job_id}/results    – Full results payload
  GET  /jobs                     – List all jobs (filter by ?status=)
"""
from __future__ import annotations

import os
import shutil
import uuid
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import create_all_tables, get_db
from app.models import Job, JobSummary, Transaction
from app.schemas import (
    CategoryBreakdown,
    JobCreateResponse,
    JobListItem,
    JobResultsResponse,
    JobStatusResponse,
    JobSummaryEmbedded,
    TransactionOut,
)
from app.tasks import process_job

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="AI-Powered Transaction Processing Pipeline",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    await create_all_tables()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_job_or_404(job_id: uuid.UUID, session: AsyncSession) -> Job:
    result = await session.get(Job, job_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return result


def _build_summary_embedded(summary: Optional[JobSummary]) -> Optional[JobSummaryEmbedded]:
    if summary is None:
        return None
    return JobSummaryEmbedded(
        total_spend_inr=float(summary.total_spend_inr) if summary.total_spend_inr else None,
        total_spend_usd=float(summary.total_spend_usd) if summary.total_spend_usd else None,
        anomaly_count=summary.anomaly_count,
        risk_level=summary.risk_level,
        narrative=summary.narrative,
        top_merchants=summary.top_merchants,
    )


# ---------------------------------------------------------------------------
# POST /jobs/upload
# ---------------------------------------------------------------------------

@app.post("/jobs/upload", response_model=JobCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_job(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db),
):
    """Accept a CSV upload, create a Job record, enqueue the pipeline task."""
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only .csv files are accepted")

    # Basic size guard
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    contents = await file.read()
    if len(contents) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_MB} MB",
        )

    # Persist file to temp directory
    job_id = uuid.uuid4()
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(settings.UPLOAD_DIR, f"{job_id}.csv")
    with open(file_path, "wb") as f:
        f.write(contents)

    # Create Job record
    job = Job(id=job_id, filename=file.filename, status="pending")
    session.add(job)
    await session.commit()

    # Enqueue Celery task
    process_job.apply_async(args=[str(job_id), file_path], task_id=str(job_id))

    return JobCreateResponse(
        job_id=job_id,
        status="pending",
        filename=file.filename,
    )


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}/status
# ---------------------------------------------------------------------------

@app.get("/jobs/{job_id}/status", response_model=JobStatusResponse)
async def get_job_status(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    """Return current job status. If completed, include high-level stats."""
    result = await session.execute(
        select(Job)
        .where(Job.id == job_id)
        .options(selectinload(Job.summary))
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    summary_embedded = None
    if job.status == "completed" and job.summary:
        summary_embedded = _build_summary_embedded(job.summary)

    return JobStatusResponse(
        id=job.id,
        filename=job.filename,
        status=job.status,
        row_count_raw=job.row_count_raw,
        row_count_clean=job.row_count_clean,
        created_at=job.created_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
        summary=summary_embedded,
    )


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}/results
# ---------------------------------------------------------------------------

@app.get("/jobs/{job_id}/results", response_model=JobResultsResponse)
async def get_job_results(
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
):
    """Return full structured results: transactions, anomalies, breakdowns, summary."""
    result = await session.execute(
        select(Job)
        .where(Job.id == job_id)
        .options(
            selectinload(Job.transactions),
            selectinload(Job.summary),
        )
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if job.status not in ("completed", "failed"):
        raise HTTPException(
            status_code=409,
            detail=f"Job is not yet completed (current status: {job.status})",
        )

    txns = job.transactions or []

    # Anomalies
    anomalies = [t for t in txns if t.is_anomaly]

    # Per-category spend breakdown (use llm_category if available, else category)
    category_map: dict[str, dict] = {}
    for t in txns:
        cat = t.llm_category or t.category or "Uncategorised"
        amt = float(t.amount) if t.amount else 0.0
        if cat not in category_map:
            category_map[cat] = {"total_spend": 0.0, "transaction_count": 0}
        category_map[cat]["total_spend"] += amt
        category_map[cat]["transaction_count"] += 1

    category_breakdown = [
        CategoryBreakdown(category=k, **v)
        for k, v in sorted(category_map.items(), key=lambda x: -x[1]["total_spend"])
    ]

    return JobResultsResponse(
        job_id=job.id,
        status=job.status,
        row_count_raw=job.row_count_raw,
        row_count_clean=job.row_count_clean,
        transactions=[TransactionOut.model_validate(t) for t in txns],
        anomalies=[TransactionOut.model_validate(t) for t in anomalies],
        category_breakdown=category_breakdown,
        summary=_build_summary_embedded(job.summary),
    )


# ---------------------------------------------------------------------------
# GET /jobs
# ---------------------------------------------------------------------------

@app.get("/jobs", response_model=list[JobListItem])
async def list_jobs(
    status: Optional[str] = Query(default=None, description="Filter by status"),
    session: AsyncSession = Depends(get_db),
):
    """List all jobs, optionally filtered by status."""
    query = select(Job).order_by(Job.created_at.desc())
    if status:
        query = query.where(Job.status == status)

    result = await session.execute(query)
    jobs = result.scalars().all()
    return [JobListItem.model_validate(j) for j in jobs]


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.APP_NAME}
