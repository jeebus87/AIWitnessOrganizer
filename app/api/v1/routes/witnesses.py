"""Witness routes for searching and managing witness data"""
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete
from sqlalchemy.orm import selectinload

from app.db.session import get_db
from app.db.models import Witness, Document, Matter, ImportanceLevel, WitnessRole, User, ClioIntegration, CanonicalWitness, RelevanceLevel
from app.api.v1.schemas.witnesses import (
    WitnessResponse, WitnessListResponse, MatterResponse,
    MatterListResponse, DocumentResponse,
    CanonicalWitnessResponse, CanonicalWitnessListResponse, CanonicalObservation
)
from app.services.export_service import ExportService
from app.services.clio_client import get_clio_account_info
from app.core.security import decrypt_token
from app.api.deps import get_current_user

logger = logging.getLogger(__name__)

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


@router.get("/canonical", response_model=CanonicalWitnessListResponse)
async def list_canonical_witnesses(
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    matter_id: Optional[int] = None,
    relevance: Optional[List[str]] = Query(None),
    role: Optional[List[str]] = Query(None),
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    List canonical (deduplicated) witnesses with filtering and pagination.
    Returns consolidated witness records with merged observations from all documents.
    """
    # Base query
    query = (
        select(CanonicalWitness)
        .join(Matter)
        .where(Matter.user_id == current_user.id)
    )

    # Apply filters
    if matter_id:
        query = query.where(CanonicalWitness.matter_id == matter_id)

    if relevance:
        relevance_enums = [RelevanceLevel(r.lower()) for r in relevance]
        query = query.where(CanonicalWitness.relevance.in_(relevance_enums))

    if role:
        role_enums = [WitnessRole(r.lower()) for r in role]
        query = query.where(CanonicalWitness.role.in_(role_enums))

    if search:
        query = query.where(CanonicalWitness.full_name.ilike(f"%{search}%"))

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    # Apply pagination and ordering
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    query = query.order_by(
        CanonicalWitness.source_document_count.desc(),  # Most referenced first
        CanonicalWitness.full_name
    )

    result = await db.execute(query)
    canonical_witnesses = result.scalars().all()

    # Build response
    witness_responses = []
    for cw in canonical_witnesses:
        # Parse merged_observations JSON into CanonicalObservation objects
        observations = []
        if cw.merged_observations:
            for obs in cw.merged_observations:
                observations.append(CanonicalObservation(
                    document_id=obs.get("doc_id", 0),
                    document_filename=obs.get("filename", "Unknown"),
                    page=obs.get("page"),
                    text=obs.get("text", "")
                ))

        witness_responses.append(CanonicalWitnessResponse(
            id=cw.id,
            matter_id=cw.matter_id,
            full_name=cw.full_name,
            role=cw.role.value,
            relevance=cw.relevance.value.upper() if cw.relevance else None,
            relevance_reason=cw.relevance_reason,
            observations=observations,
            email=cw.email,
            phone=cw.phone,
            address=cw.address,
            source_document_count=cw.source_document_count,
            max_confidence_score=cw.max_confidence_score,
            created_at=cw.created_at,
            updated_at=cw.updated_at
        ))

    return CanonicalWitnessListResponse(
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


@router.delete("/clear")
async def clear_witnesses(
    current_user: User = Depends(get_current_user),
    matter_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Clear all witnesses for a specific matter or all matters.
    Use this to reset before re-processing with correct folder filtering.

    Args:
        matter_id: Optional matter ID. If provided, only clears witnesses for that matter.
                   If not provided, clears ALL witnesses for the user.
    """
    if matter_id:
        # Verify matter belongs to user
        result = await db.execute(
            select(Matter).where(
                Matter.id == matter_id,
                Matter.user_id == current_user.id
            )
        )
        matter = result.scalar_one_or_none()
        if not matter:
            raise HTTPException(status_code=404, detail="Matter not found")

        # Get document IDs for this matter
        doc_result = await db.execute(
            select(Document.id).where(Document.matter_id == matter_id)
        )
        doc_ids = [row[0] for row in doc_result.fetchall()]

        if doc_ids:
            # Delete witnesses for these documents
            await db.execute(
                delete(Witness).where(Witness.document_id.in_(doc_ids))
            )
            await db.commit()

            # Also reset document processing status
            await db.execute(
                select(Document).where(Document.id.in_(doc_ids))
            )
            from sqlalchemy import update
            await db.execute(
                update(Document)
                .where(Document.id.in_(doc_ids))
                .values(is_processed=False, processed_at=None, analysis_cache=None)
            )
            await db.commit()

        logger.info(f"Cleared witnesses for matter {matter_id} ({len(doc_ids)} documents)")
        return {
            "success": True,
            "matter_id": matter_id,
            "documents_reset": len(doc_ids),
            "message": f"Cleared all witnesses for matter and reset {len(doc_ids)} documents"
        }
    else:
        # Clear ALL witnesses for user's matters
        # Get all matter IDs for user
        matter_result = await db.execute(
            select(Matter.id).where(Matter.user_id == current_user.id)
        )
        matter_ids = [row[0] for row in matter_result.fetchall()]

        # Get all document IDs for these matters
        doc_result = await db.execute(
            select(Document.id).where(Document.matter_id.in_(matter_ids))
        )
        doc_ids = [row[0] for row in doc_result.fetchall()]

        if doc_ids:
            # Delete all witnesses
            result = await db.execute(
                delete(Witness).where(Witness.document_id.in_(doc_ids))
            )
            deleted_count = result.rowcount

            # Reset document processing status
            from sqlalchemy import update
            await db.execute(
                update(Document)
                .where(Document.id.in_(doc_ids))
                .values(is_processed=False, processed_at=None, analysis_cache=None)
            )
            await db.commit()

            logger.info(f"Cleared all {deleted_count} witnesses for user {current_user.id}")
            return {
                "success": True,
                "witnesses_deleted": deleted_count,
                "documents_reset": len(doc_ids),
                "message": f"Cleared {deleted_count} witnesses and reset {len(doc_ids)} documents"
            }

        return {"success": True, "witnesses_deleted": 0, "documents_reset": 0, "message": "No witnesses found"}


async def _get_firm_name(db: AsyncSession, user: User) -> Optional[str]:
    """Get firm name from Clio for the user"""
    try:
        # Get Clio integration for user
        clio_result = await db.execute(
            select(ClioIntegration).where(ClioIntegration.user_id == user.id)
        )
        clio_integration = clio_result.scalar_one_or_none()

        if clio_integration and clio_integration.access_token_encrypted:
            access_token = decrypt_token(clio_integration.access_token_encrypted)
            account_info = await get_clio_account_info(access_token)
            return account_info.get("name")
    except Exception as e:
        logger.warning(f"Failed to fetch firm info from Clio: {e}")

    return None


@router.get("/export/pdf")
async def export_witnesses_pdf(
    current_user: User = Depends(get_current_user),
    matter_id: Optional[int] = None,
    job_id: Optional[int] = None,
    importance: Optional[List[str]] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Export witnesses to PDF.

    Args:
        matter_id: Filter by matter (legacy, use job_id for job-specific exports)
        job_id: Filter by job - only witnesses created by this specific job
        importance: Filter by importance levels
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

    # Job ID filter takes precedence (more specific)
    if job_id:
        query = query.where(Witness.job_id == job_id)
    elif matter_id:
        query = query.where(Matter.id == matter_id)

    if importance:
        importance_enums = [ImportanceLevel(i.lower()) for i in importance]
        query = query.where(Witness.importance.in_(importance_enums))

    result = await db.execute(query)
    witnesses = result.scalars().all()

    # Get matter info from job or matter_id
    matter_name = None
    matter_number = None
    job_number = None
    if job_id:
        from app.db.models import ProcessingJob
        job_result = await db.execute(
            select(ProcessingJob).where(ProcessingJob.id == job_id)
        )
        job = job_result.scalar_one_or_none()
        if job:
            job_number = job.job_number
            if job.target_matter_id:
                matter_result = await db.execute(
                    select(Matter).where(Matter.id == job.target_matter_id)
                )
                matter = matter_result.scalar_one_or_none()
                if matter:
                    matter_name = matter.description
                    matter_number = matter.display_number
    elif matter_id:
        matter_result = await db.execute(
            select(Matter).where(Matter.id == matter_id)
        )
        matter = matter_result.scalar_one_or_none()
        if matter:
            matter_name = matter.description
            matter_number = matter.display_number

    # Get firm name from Clio
    firm_name = await _get_firm_name(db, current_user)

    # Get user's display name for "generated by"
    generated_by = current_user.display_name or current_user.email

    # Convert to dict format for export
    witness_data = []
    for w in witnesses:
        witness_data.append({
            "full_name": w.full_name,
            "role": w.role.value,
            "importance": w.importance.value.upper(),
            "relevance": w.relevance.value.upper() if w.relevance else None,
            "relevance_reason": w.relevance_reason,
            "observation": w.observation,
            "source_quote": w.source_quote,
            "source_page": w.source_page,
            "email": w.email,
            "phone": w.phone,
            "address": w.address,
            "document_filename": w.document.filename if w.document else None,
            "confidence_score": w.confidence_score
        })

    # Generate PDF
    export_service = ExportService()
    pdf_bytes = export_service.generate_pdf(
        witnesses=witness_data,
        matter_name=matter_name,
        matter_number=matter_number,
        firm_name=firm_name,
        generated_by=generated_by
    )

    # Build filename with job number if available
    if job_number:
        filename = f"witnesses_job{job_number}_{datetime.now().strftime('%Y%m%d')}.pdf"
    else:
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
    job_id: Optional[int] = None,
    importance: Optional[List[str]] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Export witnesses to Excel.

    Args:
        matter_id: Filter by matter (legacy, use job_id for job-specific exports)
        job_id: Filter by job - only witnesses created by this specific job
        importance: Filter by importance levels
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

    # Job ID filter takes precedence (more specific)
    if job_id:
        query = query.where(Witness.job_id == job_id)
    elif matter_id:
        query = query.where(Matter.id == matter_id)

    if importance:
        importance_enums = [ImportanceLevel(i.lower()) for i in importance]
        query = query.where(Witness.importance.in_(importance_enums))

    result = await db.execute(query)
    witnesses = result.scalars().all()

    # Get matter info from job or matter_id
    matter_name = None
    matter_number = None
    job_number = None
    if job_id:
        from app.db.models import ProcessingJob
        job_result = await db.execute(
            select(ProcessingJob).where(ProcessingJob.id == job_id)
        )
        job = job_result.scalar_one_or_none()
        if job:
            job_number = job.job_number
            if job.target_matter_id:
                matter_result = await db.execute(
                    select(Matter).where(Matter.id == job.target_matter_id)
                )
                matter = matter_result.scalar_one_or_none()
                if matter:
                    matter_name = matter.description
                    matter_number = matter.display_number
    elif matter_id:
        matter_result = await db.execute(
            select(Matter).where(Matter.id == matter_id)
        )
        matter = matter_result.scalar_one_or_none()
        if matter:
            matter_name = matter.description
            matter_number = matter.display_number

    # Get firm name from Clio
    firm_name = await _get_firm_name(db, current_user)

    # Get user's display name for "generated by"
    generated_by = current_user.display_name or current_user.email

    # Convert to dict format for export
    witness_data = []
    for w in witnesses:
        witness_data.append({
            "full_name": w.full_name,
            "role": w.role.value,
            "importance": w.importance.value.upper(),
            "relevance": w.relevance.value.upper() if w.relevance else None,
            "relevance_reason": w.relevance_reason,
            "observation": w.observation,
            "source_quote": w.source_quote,
            "source_page": w.source_page,
            "email": w.email,
            "phone": w.phone,
            "address": w.address,
            "document_filename": w.document.filename if w.document else None,
            "matter_name": w.document.matter.description if w.document and w.document.matter else None,
            "confidence_score": w.confidence_score
        })

    # Generate Excel
    export_service = ExportService()
    excel_bytes = export_service.generate_excel(
        witnesses=witness_data,
        matter_name=matter_name,
        matter_number=matter_number,
        firm_name=firm_name,
        generated_by=generated_by
    )

    # Build filename with job number if available
    if job_number:
        filename = f"witnesses_job{job_number}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    else:
        filename = f"witnesses_{matter_number or 'all'}_{datetime.now().strftime('%Y%m%d')}.xlsx"

    return StreamingResponse(
        iter([excel_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/export/docx")
async def export_witnesses_docx(
    current_user: User = Depends(get_current_user),
    matter_id: Optional[int] = None,
    job_id: Optional[int] = None,
    importance: Optional[List[str]] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """
    Export witnesses to DOCX (Word).

    Args:
        matter_id: Filter by matter (legacy, use job_id for job-specific exports)
        job_id: Filter by job - only witnesses created by this specific job
        importance: Filter by importance levels
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

    # Job ID filter takes precedence (more specific)
    if job_id:
        query = query.where(Witness.job_id == job_id)
    elif matter_id:
        query = query.where(Matter.id == matter_id)

    if importance:
        importance_enums = [ImportanceLevel(i.lower()) for i in importance]
        query = query.where(Witness.importance.in_(importance_enums))

    result = await db.execute(query)
    witnesses = result.scalars().all()

    # Get matter info from job or matter_id
    matter_name = None
    matter_number = None
    job_number = None
    if job_id:
        from app.db.models import ProcessingJob
        job_result = await db.execute(
            select(ProcessingJob).where(ProcessingJob.id == job_id)
        )
        job = job_result.scalar_one_or_none()
        if job:
            job_number = job.job_number
            if job.target_matter_id:
                matter_result = await db.execute(
                    select(Matter).where(Matter.id == job.target_matter_id)
                )
                matter = matter_result.scalar_one_or_none()
                if matter:
                    matter_name = matter.description
                    matter_number = matter.display_number
    elif matter_id:
        matter_result = await db.execute(
            select(Matter).where(Matter.id == matter_id)
        )
        matter = matter_result.scalar_one_or_none()
        if matter:
            matter_name = matter.description
            matter_number = matter.display_number

    # Get firm name from Clio
    firm_name = await _get_firm_name(db, current_user)

    # Get user's display name for "generated by"
    generated_by = current_user.display_name or current_user.email

    # Convert to dict format for export
    witness_data = []
    for w in witnesses:
        witness_data.append({
            "full_name": w.full_name,
            "role": w.role.value,
            "importance": w.importance.value.upper(),
            "relevance": w.relevance.value.upper() if w.relevance else None,
            "relevance_reason": w.relevance_reason,
            "observation": w.observation,
            "source_quote": w.source_quote,
            "source_page": w.source_page,
            "email": w.email,
            "phone": w.phone,
            "address": w.address,
            "document_filename": w.document.filename if w.document else None,
            "matter_name": w.document.matter.description if w.document and w.document.matter else None,
            "confidence_score": w.confidence_score,
            "document_relevance": w.document_relevance.value.upper() if w.document_relevance else None,
            "document_relevance_reason": w.document_relevance_reason,
        })

    # Generate DOCX
    export_service = ExportService()
    docx_bytes = export_service.generate_docx(
        witnesses=witness_data,
        matter_name=matter_name,
        matter_number=matter_number,
        firm_name=firm_name,
        generated_by=generated_by
    )

    # Build filename with job number if available
    if job_number:
        filename = f"witnesses_job{job_number}_{datetime.now().strftime('%Y%m%d')}.docx"
    else:
        filename = f"witnesses_{matter_number or 'all'}_{datetime.now().strftime('%Y%m%d')}.docx"

    return StreamingResponse(
        iter([docx_bytes]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# Import datetime at the top level
from datetime import datetime
