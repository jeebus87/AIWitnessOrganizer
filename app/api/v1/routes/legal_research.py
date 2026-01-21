"""API endpoints for legal research functionality"""
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import User, LegalResearchResult, LegalResearchStatus, ProcessingJob
from app.api.deps import get_current_user
from app.worker.tasks import search_legal_authorities

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/legal-research", tags=["Legal Research"])


class CaseLawResultResponse(BaseModel):
    """Response model for a single case law result"""
    id: int
    case_name: str
    citation: Optional[str]
    court: str
    date_filed: Optional[str]
    snippet: str
    absolute_url: str
    matched_query: Optional[str] = None  # The search query that found this case
    relevance_score: Optional[float] = None  # CourtListener relevance score


class LegalResearchResultResponse(BaseModel):
    """Response model for legal research results"""
    id: int
    job_id: int
    status: str
    results: List[CaseLawResultResponse]
    selected_ids: Optional[List[int]]
    created_at: str

    class Config:
        from_attributes = True


class ApproveResearchRequest(BaseModel):
    """Request model for approving legal research"""
    selected_case_ids: List[int]


@router.get("/job/{job_id}")
async def get_legal_research_for_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get legal research results for a specific job.

    Returns the legal research results if they exist and are ready for review.
    """
    # First verify the job belongs to the user
    job_result = await db.execute(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.user_id == current_user.id
        )
    )
    job = job_result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get the most recent legal research results for this job
    result = await db.execute(
        select(LegalResearchResult).where(
            LegalResearchResult.job_id == job_id,
            LegalResearchResult.user_id == current_user.id
        ).order_by(LegalResearchResult.created_at.desc()).limit(1)
    )
    research = result.scalar_one_or_none()

    if not research:
        return {"has_results": False, "status": None}

    # Format results
    formatted_results = []
    if research.results:
        for r in research.results:
            formatted_results.append({
                "id": r.get("id", 0),
                "case_name": r.get("case_name", "Unknown"),
                "citation": r.get("citation"),
                "court": r.get("court", "Unknown"),
                "date_filed": r.get("date_filed"),
                "snippet": r.get("snippet", "")[:300],
                "absolute_url": r.get("absolute_url", ""),
                "matched_query": r.get("matched_query"),
                "relevance_score": r.get("relevance_score")
            })

    return {
        "has_results": True,
        "id": research.id,
        "job_id": research.job_id,
        "status": research.status.value,
        "results": formatted_results,
        "selected_ids": research.selected_ids or [],
        "created_at": research.created_at.isoformat() if research.created_at else None
    }


@router.post("/{research_id}/approve")
async def approve_legal_research(
    research_id: int,
    request: ApproveResearchRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Approve selected cases from legal research and save to Clio.

    This queues a background task to download the selected cases and
    upload them to a "Legal Research" folder in the matter's Clio documents.
    """
    # Get the research record
    result = await db.execute(
        select(LegalResearchResult).where(
            LegalResearchResult.id == research_id,
            LegalResearchResult.user_id == current_user.id
        )
    )
    research = result.scalar_one_or_none()

    if not research:
        raise HTTPException(status_code=404, detail="Legal research not found")

    if research.status not in [LegalResearchStatus.READY, LegalResearchStatus.PENDING]:
        raise HTTPException(
            status_code=400,
            detail=f"Research cannot be approved in {research.status.value} status"
        )

    # Update the research with selected IDs
    research.selected_ids = request.selected_case_ids
    research.status = LegalResearchStatus.APPROVED
    research.reviewed_at = datetime.utcnow()

    await db.commit()

    # Queue background task to save to Clio
    from app.worker.tasks import save_legal_research_to_clio
    save_legal_research_to_clio.delay(research_id)

    return {
        "status": "approved",
        "message": f"Saving {len(request.selected_case_ids)} cases to Clio",
        "research_id": research_id
    }


@router.post("/{research_id}/dismiss")
async def dismiss_legal_research(
    research_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Dismiss legal research results.

    The user doesn't want to save any of the suggested cases.
    """
    # Get the research record
    result = await db.execute(
        select(LegalResearchResult).where(
            LegalResearchResult.id == research_id,
            LegalResearchResult.user_id == current_user.id
        )
    )
    research = result.scalar_one_or_none()

    if not research:
        raise HTTPException(status_code=404, detail="Legal research not found")

    # Update status
    research.status = LegalResearchStatus.DISMISSED
    research.reviewed_at = datetime.utcnow()

    await db.commit()

    return {
        "status": "dismissed",
        "message": "Legal research dismissed",
        "research_id": research_id
    }


@router.get("/pending")
async def get_pending_legal_research(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get all pending legal research that needs user review.

    Returns a list of jobs that have legal research results ready for review.
    """
    result = await db.execute(
        select(LegalResearchResult).where(
            LegalResearchResult.user_id == current_user.id,
            LegalResearchResult.status == LegalResearchStatus.READY
        ).order_by(LegalResearchResult.created_at.desc())
    )
    research_list = result.scalars().all()

    return {
        "pending_count": len(research_list),
        "items": [
            {
                "id": r.id,
                "job_id": r.job_id,
                "matter_id": r.matter_id,
                "result_count": len(r.results) if r.results else 0,
                "created_at": r.created_at.isoformat() if r.created_at else None
            }
            for r in research_list
        ]
    }


@router.post("/job/{job_id}/rerun")
async def rerun_legal_research(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Re-run legal research for a specific job.

    This will create new legal research results using the latest query logic.
    """
    # Verify the job belongs to the user and is completed
    job_result = await db.execute(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.user_id == current_user.id
        )
    )
    job = job_result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job must be completed to run legal research")

    if not job.matter_id:
        raise HTTPException(status_code=400, detail="Job has no associated matter")

    # Trigger the legal research task
    search_legal_authorities.delay(
        job_id=job_id,
        matter_id=job.matter_id,
        user_id=current_user.id
    )

    return {
        "status": "started",
        "message": "Legal research re-run started",
        "job_id": job_id
    }
