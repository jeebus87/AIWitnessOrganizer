"""Processing job schemas"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class JobCreateRequest(BaseModel):
    """Request to create a processing job"""
    job_type: str = Field(
        ...,
        description="Type of job: 'single_matter' or 'full_database'"
    )
    matter_id: Optional[int] = Field(
        None,
        description="Matter ID for single_matter jobs"
    )
    search_witnesses: Optional[List[str]] = Field(
        None,
        description="Optional list of specific witness names to search for"
    )
    include_archived: bool = Field(
        False,
        description="Include archived matters (for full_database jobs)"
    )


class JobResponse(BaseModel):
    """Processing job response"""
    id: int
    job_type: str
    status: str
    total_documents: int
    processed_documents: int
    failed_documents: int
    total_witnesses_found: int
    progress_percent: float = 0.0
    error_message: Optional[str] = None
    result_summary: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class JobListResponse(BaseModel):
    """List of jobs response"""
    jobs: List[JobResponse]
    total: int


class JobProgressUpdate(BaseModel):
    """Real-time job progress update (for WebSocket)"""
    job_id: int
    status: str
    processed_documents: int
    total_documents: int
    progress_percent: float
    current_document: Optional[str] = None
    witnesses_found: int = 0


class ExportRequest(BaseModel):
    """Export request for PDF/Excel"""
    format: str = Field(
        ...,
        description="Export format: 'pdf' or 'excel'"
    )
    matter_id: Optional[int] = Field(
        None,
        description="Specific matter to export (if None, exports all)"
    )
    importance_filter: Optional[List[str]] = Field(
        None,
        description="Filter by importance levels: ['HIGH', 'MEDIUM', 'LOW']"
    )
    role_filter: Optional[List[str]] = Field(
        None,
        description="Filter by witness roles"
    )
