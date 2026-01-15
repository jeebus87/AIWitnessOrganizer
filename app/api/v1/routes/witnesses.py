"""Witness routes for searching and managing witness data"""
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.db.models import Witness, Document, Matter, ImportanceLevel, WitnessRole, User
from app.api.v1.schemas.witnesses import (
    WitnessResponse, WitnessListResponse, MatterResponse,
    MatterListResponse, DocumentResponse
)
from app.services.export_service import ExportService
from app.api.deps import get_current_user

router = APIRouter(prefix="/witnesses", tags=["Witnesses"])


@router.get("", response_model=WitnessListResponse)
async def list_witnesses(
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    matter_id: Optional[int] = None,
    importance: Optional[List[str]] = Query(None),
    role: Optional[List[str]] = Query(None),
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    List witnesses with filtering and pagination.
    """
    # Base query
    query = (
        select(Witness)
        .join(Document)
        .join(Matter)
        .where(Matter.user_id == current_user.id)
        .options(
            selectinload(Witness.document).selectinload(Document.matter)
        )
    )

    # Apply filters
    if matter_id:
        query = query.where(Matter.id == matter_id)

    if importance:
        importance_enums = [ImportanceLevel(i.lower()) for i in importance]
        query = query.where(Witness.importance.in_(importance_enums))

    if role:
        role_enums = [WitnessRole(r.lower()) for r in role]
        query = query.where(Witness.role.in_(role_enums))

    if search:
        query = query.where(Witness.full_name.ilike(f"%{search}%"))

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    # Apply pagination
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    query = query.order_by(
        Witness.importance.desc(),
        Witness.full_name
    )

    result = await db.execute(query)
    witnesses = result.scalars().all()

    # Build response
    witness_responses = []
    for w in witnesses:
        witness_responses.append(WitnessResponse(
            id=w.id,
            document_id=w.document_id,
            full_name=w.full_name,
            role=w.role.value,
            importance=w.importance.value.upper(),
            observation=w.observation,
            source_quote=w.source_quote,
            context=w.context,
            email=w.email,
            phone=w.phone,
            address=w.address,
            confidence_score=w.confidence_score,
            document_filename=w.document.filename if w.document else None,
            matter_name=w.document.matter.description if w.document and w.document.matter else None,
            created_at=w.created_at
        ))

    return WitnessListResponse(
        witnesses=witness_responses,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size
    )


@router.get("/{witness_id}", response_model=WitnessResponse)
async def get_witness(
    witness_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a specific witness by ID.
    """
    query = (
        select(Witness)
        .join(Document)
        .join(Matter)
        .where(
            Witness.id == witness_id,
            Matter.user_id == current_user.id
        )
        .options(
            selectinload(Witness.document).selectinload(Document.matter)
        )
    )

    result = await db.execute(query)
    witness = result.scalar_one_or_none()

    if not witness:
        raise HTTPException(status_code=404, detail="Witness not found")

    return WitnessResponse(
        id=witness.id,
        document_id=witness.document_id,
        full_name=witness.full_name,
        role=witness.role.value,
        importance=witness.importance.value.upper(),
        observation=witness.observation,
        source_quote=witness.source_quote,
        context=witness.context,
        email=witness.email,
        phone=witness.phone,
        address=witness.address,
        confidence_score=witness.confidence_score,
        document_filename=witness.document.filename,
        matter_name=witness.document.matter.description,
        created_at=witness.created_at
    )


@router.get("/export/pdf")
async def export_witnesses_pdf(
    current_user: User = Depends(get_current_user),
    matter_id: Optional[int] = None,
    importance: Optional[List[str]] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Export witnesses to PDF.
    """
    # Build query
    query = (
        select(Witness)
        .join(Document)
        .join(Matter)
        .where(Matter.user_id == current_user.id)
        .options(
            selectinload(Witness.document).selectinload(Document.matter)
        )
    )

    if matter_id:
        query = query.where(Matter.id == matter_id)

    if importance:
        importance_enums = [ImportanceLevel(i.lower()) for i in importance]
        query = query.where(Witness.importance.in_(importance_enums))

    result = await db.execute(query)
    witnesses = result.scalars().all()

    # Get matter info if specific matter
    matter_name = None
    matter_number = None
    if matter_id:
        matter_result = await db.execute(
            select(Matter).where(Matter.id == matter_id)
        )
        matter = matter_result.scalar_one_or_none()
        if matter:
            matter_name = matter.description
            matter_number = matter.display_number

    # Convert to dict format for export
    witness_data = []
    for w in witnesses:
        witness_data.append({
            "full_name": w.full_name,
            "role": w.role.value,
            "importance": w.importance.value.upper(),
            "observation": w.observation,
            "source_quote": w.source_quote,
            "email": w.email,
            "phone": w.phone,
            "document_filename": w.document.filename if w.document else None,
            "confidence_score": w.confidence_score
        })

    # Generate PDF
    export_service = ExportService()
    pdf_bytes = export_service.generate_pdf(
        witnesses=witness_data,
        matter_name=matter_name,
        matter_number=matter_number
    )

    filename = f"witnesses_{matter_number or 'all'}_{datetime.now().strftime('%Y%m%d')}.pdf"

    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/export/excel")
async def export_witnesses_excel(
    current_user: User = Depends(get_current_user),
    matter_id: Optional[int] = None,
    importance: Optional[List[str]] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Export witnesses to Excel.
    """
    # Build query
    query = (
        select(Witness)
        .join(Document)
        .join(Matter)
        .where(Matter.user_id == current_user.id)
        .options(
            selectinload(Witness.document).selectinload(Document.matter)
        )
    )

    if matter_id:
        query = query.where(Matter.id == matter_id)

    if importance:
        importance_enums = [ImportanceLevel(i.lower()) for i in importance]
        query = query.where(Witness.importance.in_(importance_enums))

    result = await db.execute(query)
    witnesses = result.scalars().all()

    # Get matter info if specific matter
    matter_name = None
    if matter_id:
        matter_result = await db.execute(
            select(Matter).where(Matter.id == matter_id)
        )
        matter = matter_result.scalar_one_or_none()
        if matter:
            matter_name = matter.display_number or matter.description

    # Convert to dict format for export
    witness_data = []
    for w in witnesses:
        witness_data.append({
            "full_name": w.full_name,
            "role": w.role.value,
            "importance": w.importance.value.upper(),
            "observation": w.observation,
            "source_quote": w.source_quote,
            "email": w.email,
            "phone": w.phone,
            "document_filename": w.document.filename if w.document else None,
            "matter_name": w.document.matter.description if w.document and w.document.matter else None,
            "confidence_score": w.confidence_score
        })

    # Generate Excel
    export_service = ExportService()
    excel_bytes = export_service.generate_excel(
        witnesses=witness_data,
        matter_name=matter_name
    )

    filename = f"witnesses_{matter_name or 'all'}_{datetime.now().strftime('%Y%m%d')}.xlsx"

    return StreamingResponse(
        iter([excel_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# Import datetime at the top level
from datetime import datetime
