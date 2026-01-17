"""Processing job routes for document scanning"""
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from sqlalchemy.orm import joinedload

from app.db.session import get_db
from app.db.models import ProcessingJob, Matter, JobStatus, User, OrganizationJobCounter
from app.api.v1.schemas.jobs import JobCreateRequest, JobResponse, JobListResponse
from app.worker.tasks import process_matter, process_full_database
from app.api.deps import get_current_user


async def get_next_job_number(db: AsyncSession, organization_id: int) -> int:
    """Atomically increment and return the next job number for an organization"""
    if not organization_id:
        return None

    # Use INSERT ... ON CONFLICT to handle race conditions
    # This ensures the counter is created if it doesn't exist
    result = await db.execute(
        text("""
            INSERT INTO organization_job_counters (organization_id, job_counter)
            VALUES (:org_id, 1)
            ON CONFLICT (organization_id)
            DO UPDATE SET job_counter = organization_job_counters.job_counter + 1
            RETURNING job_counter
        """),
        {"org_id": organization_id}
    )
    job_number = result.scalar_one()
    return job_number

router = APIRouter(prefix="/jobs", tags=["Processing Jobs"])


@router.post("", response_model=JobResponse)
async def create_job(
    request: JobCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Create a new document processing job.
    """
    # Validate job type
    if request.job_type not in ("single_matter", "full_database"):
        raise HTTPException(
            status_code=400,
            detail="Invalid job type. Must be 'single_matter' or 'full_database'"
        )

    # Validate matter_id for single_matter jobs
    if request.job_type == "single_matter":
        if not request.matter_id:
            raise HTTPException(
                status_code=400,
                detail="matter_id required for single_matter jobs"
            )

        # Verify matter belongs to user
        result = await db.execute(
            select(Matter).where(
                Matter.id == request.matter_id,
                Matter.user_id == current_user.id
            )
        )
        matter = result.scalar_one_or_none()
        if not matter:
            raise HTTPException(status_code=404, detail="Matter not found")

    # Get sequential job number for the organization
    job_number = None
    if current_user.organization_id:
        job_number = await get_next_job_number(db, current_user.organization_id)

    # Create job record
    job = ProcessingJob(
        user_id=current_user.id,
        job_type=request.job_type,
        target_matter_id=request.matter_id,
        search_witnesses=request.search_witnesses,
        include_archived=request.include_archived,
        status=JobStatus.PENDING,
        job_number=job_number
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Start Celery task
    if request.job_type == "single_matter":
        task = process_matter.delay(
            job_id=job.id,
            matter_id=request.matter_id,
            search_targets=request.search_witnesses
        )
    else:
        task = process_full_database.delay(
            job_id=job.id,
            user_id=current_user.id,
            search_targets=request.search_witnesses,
            include_archived=request.include_archived
        )

    # Store task ID
    job.celery_task_id = task.id
    await db.commit()

    return _job_to_response(job)


@router.get("", response_model=JobListResponse)
async def list_jobs(
    current_user: User = Depends(get_current_user),
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """
    List processing jobs for the current user.
    """
    query = select(ProcessingJob).options(joinedload(ProcessingJob.target_matter)).where(ProcessingJob.user_id == current_user.id)

    if status:
        query = query.where(ProcessingJob.status == JobStatus(status))

    # Order by most recent first
    query = query.order_by(ProcessingJob.created_at.desc())

    # Count total
    from sqlalchemy import func
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    # Apply pagination
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    jobs = result.scalars().all()

    return JobListResponse(
        jobs=[_job_to_response(j) for j in jobs],
        total=total
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a specific job by ID.
    """
    result = await db.execute(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.user_id == current_user.id
        )
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return _job_to_response(job)


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Cancel a running job.
    """
    result = await db.execute(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.user_id == current_user.id
        )
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in (JobStatus.PENDING, JobStatus.PROCESSING):
        raise HTTPException(
            status_code=400,
            detail="Can only cancel pending or processing jobs"
        )

    # Revoke Celery task if it exists
    if job.celery_task_id:
        from app.worker.celery_app import celery_app
        celery_app.control.revoke(job.celery_task_id, terminate=True)

    job.status = JobStatus.CANCELLED
    job.completed_at = datetime.utcnow()
    await db.commit()

    return {"success": True, "message": "Job cancelled"}




@router.delete("/{job_id}")
async def delete_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Delete a cancelled or failed job.
    """
    result = await db.execute(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.user_id == current_user.id
        )
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status not in (JobStatus.CANCELLED, JobStatus.FAILED, JobStatus.COMPLETED):
        raise HTTPException(
            status_code=400,
            detail="Can only delete cancelled, failed, or completed jobs"
        )

    await db.delete(job)
    await db.commit()

    return {"success": True, "message": "Job deleted"}


@router.delete("")
async def clear_finished_jobs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Clear all cancelled and failed jobs for the current user.
    """
    from sqlalchemy import delete

    result = await db.execute(
        delete(ProcessingJob).where(
            ProcessingJob.user_id == current_user.id,
            ProcessingJob.status.in_([JobStatus.CANCELLED, JobStatus.FAILED])
        )
    )
    await db.commit()

    return {"success": True, "deleted_count": result.rowcount}


@router.get("/{job_id}/export/pdf")
async def export_job_pdf(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Export witnesses found in a job to PDF.
    """
    from fastapi.responses import RedirectResponse

    result = await db.execute(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.user_id == current_user.id
        )
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Redirect to witnesses export with matter_id
    if job.target_matter_id:
        return RedirectResponse(
            url=f"/api/v1/witnesses/export/pdf?matter_id={job.target_matter_id}",
            status_code=307
        )
    else:
        return RedirectResponse(url="/api/v1/witnesses/export/pdf", status_code=307)


@router.get("/{job_id}/export/excel")
async def export_job_excel(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Export witnesses found in a job to Excel.
    """
    from fastapi.responses import RedirectResponse

    result = await db.execute(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.user_id == current_user.id
        )
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Redirect to witnesses export with matter_id
    if job.target_matter_id:
        return RedirectResponse(
            url=f"/api/v1/witnesses/export/excel?matter_id={job.target_matter_id}",
            status_code=307
        )
    else:
        return RedirectResponse(url="/api/v1/witnesses/export/excel", status_code=307)


def _job_to_response(job: ProcessingJob) -> JobResponse:
    """Convert a ProcessingJob to JobResponse"""
    progress = 0.0
    if job.total_documents > 0:
        progress = (job.processed_documents / job.total_documents) * 100

    # Get matter name if available
    matter_name = None
    if job.target_matter:
        matter_name = job.target_matter.display_number or job.target_matter.description

    return JobResponse(
        id=job.id,
        job_number=job.job_number,
        job_type=job.job_type,
        status=job.status.value,
        matter_name=matter_name,
        total_documents=job.total_documents,
        processed_documents=job.processed_documents,
        failed_documents=job.failed_documents,
        total_witnesses_found=job.total_witnesses_found,
        progress_percent=round(progress, 1),
        error_message=job.error_message,
        result_summary=job.result_summary,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at
    )
