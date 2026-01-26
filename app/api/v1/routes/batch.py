"""
API routes for batch inference job management.

Provides endpoints for:
- Getting pending batch jobs for a user
- Checking specific job status
- Marking jobs as user-notified
"""

from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.db.session import get_db
from app.db.models import BatchJob, BatchJobType, User
from app.api.deps import get_current_user


router = APIRouter(prefix="/batch", tags=["Batch Jobs"])


class BatchJobResponse(BaseModel):
    """Response model for a batch job."""
    id: int
    job_type: str
    status: str
    processing_job_id: Optional[int] = None
    total_records: int
    processed_records: int
    submitted_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    user_notified: bool

    class Config:
        from_attributes = True


class BatchJobListResponse(BaseModel):
    """Response model for batch job list."""
    jobs: List[BatchJobResponse]
    total: int


@router.get("/pending", response_model=BatchJobListResponse)
async def get_pending_batch_jobs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all pending batch jobs for the current user.

    Returns jobs that are submitted, in progress, or recently completed
    but not yet notified.
    """
    # Get pending jobs (not completed) and completed but not notified
    result = await db.execute(
        select(BatchJob).where(
            BatchJob.user_id == current_user.id,
            # Pending OR (completed and not notified)
            (
                BatchJob.status.in_(["Submitted", "InProgress", "Validating"]) |
                ((BatchJob.status.in_(["Completed", "Failed"])) & (BatchJob.user_notified == False))
            )
        ).order_by(BatchJob.submitted_at.desc())
    )
    jobs = result.scalars().all()

    return BatchJobListResponse(
        jobs=[
            BatchJobResponse(
                id=job.id,
                job_type=job.job_type.value if isinstance(job.job_type, BatchJobType) else job.job_type,
                status=job.status,
                processing_job_id=job.processing_job_id,
                total_records=job.total_records,
                processed_records=job.processed_records,
                submitted_at=job.submitted_at,
                completed_at=job.completed_at,
                error_message=job.error_message,
                user_notified=job.user_notified
            )
            for job in jobs
        ],
        total=len(jobs)
    )


@router.get("/{job_id}", response_model=BatchJobResponse)
async def get_batch_job_status(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get status of a specific batch job."""
    result = await db.execute(
        select(BatchJob).where(
            BatchJob.id == job_id,
            BatchJob.user_id == current_user.id
        )
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")

    return BatchJobResponse(
        id=job.id,
        job_type=job.job_type.value if isinstance(job.job_type, BatchJobType) else job.job_type,
        status=job.status,
        processing_job_id=job.processing_job_id,
        total_records=job.total_records,
        processed_records=job.processed_records,
        submitted_at=job.submitted_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
        user_notified=job.user_notified
    )


@router.post("/{job_id}/notified")
async def mark_batch_job_notified(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Mark a batch job as user-notified.

    Called by frontend after displaying notification toast.
    """
    result = await db.execute(
        select(BatchJob).where(
            BatchJob.id == job_id,
            BatchJob.user_id == current_user.id
        )
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")

    job.user_notified = True
    await db.commit()

    return {"success": True, "message": "Job marked as notified"}


@router.get("", response_model=BatchJobListResponse)
async def list_all_batch_jobs(
    status: Optional[str] = None,
    job_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List all batch jobs for the current user with optional filtering.
    """
    query = select(BatchJob).where(BatchJob.user_id == current_user.id)

    if status:
        query = query.where(BatchJob.status == status)

    if job_type:
        query = query.where(BatchJob.job_type == job_type)

    query = query.order_by(BatchJob.submitted_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    jobs = result.scalars().all()

    # Get total count
    count_query = select(BatchJob).where(BatchJob.user_id == current_user.id)
    if status:
        count_query = count_query.where(BatchJob.status == status)
    if job_type:
        count_query = count_query.where(BatchJob.job_type == job_type)

    count_result = await db.execute(count_query)
    total = len(count_result.scalars().all())

    return BatchJobListResponse(
        jobs=[
            BatchJobResponse(
                id=job.id,
                job_type=job.job_type.value if isinstance(job.job_type, BatchJobType) else job.job_type,
                status=job.status,
                processing_job_id=job.processing_job_id,
                total_records=job.total_records,
                processed_records=job.processed_records,
                submitted_at=job.submitted_at,
                completed_at=job.completed_at,
                error_message=job.error_message,
                user_notified=job.user_notified
            )
            for job in jobs
        ],
        total=total
    )
