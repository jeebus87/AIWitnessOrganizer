"""Witness-related schemas"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class WitnessBase(BaseModel):
    """Base witness schema"""
    full_name: str
    role: str
    importance: str
    observation: Optional[str] = None
    source_quote: Optional[str] = None
    context: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    confidence_score: Optional[float] = None


class WitnessResponse(WitnessBase):
    """Witness response with document info"""
    id: int
    document_id: int
    document_filename: Optional[str] = None
    matter_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class WitnessListResponse(BaseModel):
    """Paginated witness list response"""
    witnesses: List[WitnessResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class WitnessSearchRequest(BaseModel):
    """Request to search for specific witnesses"""
    targets: List[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="List of witness names to search for"
    )
    matter_id: Optional[int] = Field(
        None,
        description="Specific matter to search (if None, searches all)"
    )


class MatterResponse(BaseModel):
    """Matter response"""
    id: int
    clio_matter_id: str
    display_number: Optional[str]
    description: Optional[str]
    status: Optional[str]
    practice_area: Optional[str]
    client_name: Optional[str]
    document_count: int = 0
    witness_count: int = 0
    last_synced_at: Optional[datetime]

    class Config:
        from_attributes = True


class MatterListResponse(BaseModel):
    """Paginated matter list response"""
    matters: List[MatterResponse]
    total: int
    page: int
    page_size: int


class DocumentResponse(BaseModel):
    """Document response"""
    id: int
    clio_document_id: Optional[str]
    filename: str
    file_type: Optional[str]
    file_size: Optional[int]
    is_processed: bool
    witness_count: int = 0
    processing_error: Optional[str]
    processed_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True
