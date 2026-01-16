"""Matter routes for syncing and browsing Clio matters"""
import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, delete, distinct, asc, desc

from app.core.security import decrypt_token
from app.db.session import get_db
from app.db.models import Matter, Document, Witness, ClioIntegration, User
from app.api.v1.schemas.witnesses import MatterResponse, MatterListResponse, DocumentResponse
from app.services.clio_client import ClioClient
from app.api.deps import get_current_user

router = APIRouter(prefix="/matters", tags=["Matters"])


@router.delete("/clear")
async def clear_all_matters(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete all matters for the current user."""
    result = await db.execute(
        delete(Matter).where(Matter.user_id == current_user.id)
    )
    await db.commit()
    return {"deleted": result.rowcount}


@router.get("/filters")
async def get_matter_filters(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get distinct values for filter dropdowns."""
    statuses_result = await db.execute(
        select(distinct(Matter.status)).where(Matter.user_id == current_user.id)
    )
    practice_areas_result = await db.execute(
        select(distinct(Matter.practice_area)).where(Matter.user_id == current_user.id)
    )
    clients_result = await db.execute(
        select(distinct(Matter.client_name)).where(Matter.user_id == current_user.id)
    )

    return {
        "statuses": sorted([s for s in statuses_result.scalars().all() if s]),
        "practice_areas": sorted([p for p in practice_areas_result.scalars().all() if p]),
        "clients": sorted([c for c in clients_result.scalars().all() if c])
    }


@router.get("", response_model=MatterListResponse)
async def list_matters(
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    status: Optional[str] = None,
    practice_area: Optional[str] = None,
    client_name: Optional[str] = None,
    synced_after: Optional[datetime] = None,
    synced_before: Optional[datetime] = None,
    sort_by: str = Query("display_number", pattern="^(display_number|client_name|status|practice_area|last_synced_at|description)$"),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db)
):
    """
    List matters for the current user with sorting, filtering, and pagination.
    """
    query = select(Matter).where(Matter.user_id == current_user.id)

    # Text search across multiple fields
    if search:
        query = query.where(
            Matter.description.ilike(f"%{search}%") |
            Matter.display_number.ilike(f"%{search}%") |
            Matter.client_name.ilike(f"%{search}%")
        )

    # Exact match filters
    if status:
        query = query.where(Matter.status == status)

    if practice_area:
        query = query.where(Matter.practice_area == practice_area)

    # Partial match for client name
    if client_name:
        query = query.where(Matter.client_name.ilike(f"%{client_name}%"))

    # Date range filters
    if synced_after:
        query = query.where(Matter.last_synced_at >= synced_after)

    if synced_before:
        query = query.where(Matter.last_synced_at <= synced_before)

    # Count total (before pagination)
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    # Apply sorting
    sort_column = getattr(Matter, sort_by, Matter.display_number)
    if sort_order == "desc":
        query = query.order_by(desc(sort_column))
    else:
        query = query.order_by(asc(sort_column))

    # Apply pagination
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    matters = result.scalars().all()

    # Get document and witness counts
    matter_responses = []
    for m in matters:
        # Count documents
        doc_count = await db.scalar(
            select(func.count()).where(Document.matter_id == m.id)
        )

        # Count witnesses
        witness_count = await db.scalar(
            select(func.count())
            .select_from(Witness)
            .join(Document)
            .where(Document.matter_id == m.id)
        )

        matter_responses.append(MatterResponse(
            id=m.id,
            clio_matter_id=m.clio_matter_id,
            display_number=m.display_number,
            description=m.description,
            status=m.status,
            practice_area=m.practice_area,
            client_name=m.client_name,
            document_count=doc_count,
            witness_count=witness_count,
            last_synced_at=m.last_synced_at
        ))

    total_pages = (total + page_size - 1) // page_size if total else 0

    return MatterListResponse(
        matters=matter_responses,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/{matter_id}", response_model=MatterResponse)
async def get_matter(
    matter_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get a specific matter by ID.
    """
    result = await db.execute(
        select(Matter).where(
            Matter.id == matter_id,
            Matter.user_id == current_user.id
        )
    )
    matter = result.scalar_one_or_none()

    if not matter:
        raise HTTPException(status_code=404, detail="Matter not found")

    # Count documents
    doc_count = await db.scalar(
        select(func.count()).where(Document.matter_id == matter.id)
    )

    # Count witnesses
    witness_count = await db.scalar(
        select(func.count())
        .select_from(Witness)
        .join(Document)
        .where(Document.matter_id == matter.id)
    )

    return MatterResponse(
        id=matter.id,
        clio_matter_id=matter.clio_matter_id,
        display_number=matter.display_number,
        description=matter.description,
        status=matter.status,
        practice_area=matter.practice_area,
        client_name=matter.client_name,
        document_count=doc_count,
        witness_count=witness_count,
        last_synced_at=matter.last_synced_at
    )


@router.get("/{matter_id}/documents")
async def list_matter_documents(
    matter_id: int,
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """
    List documents for a specific matter.
    """
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

    # Query documents
    query = select(Document).where(Document.matter_id == matter_id)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    # Apply pagination
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)
    query = query.order_by(Document.filename)

    result = await db.execute(query)
    documents = result.scalars().all()

    # Get witness counts for each document
    doc_responses = []
    for doc in documents:
        witness_count = await db.scalar(
            select(func.count()).where(Witness.document_id == doc.id)
        )

        doc_responses.append(DocumentResponse(
            id=doc.id,
            clio_document_id=doc.clio_document_id,
            filename=doc.filename,
            file_type=doc.file_type,
            file_size=doc.file_size,
            is_processed=doc.is_processed,
            witness_count=witness_count,
            processing_error=doc.processing_error,
            processed_at=doc.processed_at,
            created_at=doc.created_at
        ))

    return {
        "documents": doc_responses,
        "total": total,
        "page": page,
        "page_size": page_size
    }


@router.post("/sync")
async def sync_matters_from_clio(
    current_user: User = Depends(get_current_user),
    include_archived: bool = False,
    clear_existing: bool = False,
    db: AsyncSession = Depends(get_db)
):
    """
    Sync matters from Clio to local database.

    Args:
        include_archived: If True, sync all matters including archived. Default syncs only Open.
        clear_existing: If True, delete all existing matters before syncing.
    """
    print(f"SYNC v2: Starting sync, clear_existing={clear_existing}, include_archived={include_archived}")

    # Always clear existing matters to ensure clean sync (removes matters without clients from previous syncs)
    if True:  # Always clear
        print(f"SYNC: Clearing existing matters for user {current_user.id}")
        await db.execute(
            delete(Matter).where(Matter.user_id == current_user.id)
        )
        await db.commit()
        print("SYNC: Existing matters cleared")

    # Get Clio integration
    result = await db.execute(
        select(ClioIntegration).where(
            ClioIntegration.user_id == current_user.id,
            ClioIntegration.is_active == True
        )
    )
    integration = result.scalar_one_or_none()

    if not integration:
        raise HTTPException(
            status_code=400,
            detail="Clio integration not connected"
        )

    try:
        # Decrypt tokens
        access_token = decrypt_token(integration.access_token_encrypted)
        refresh_token = decrypt_token(integration.refresh_token_encrypted)

        # Sync matters
        async with ClioClient(
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=integration.token_expires_at,
            region=integration.clio_region
        ) as clio:
            # Pass None for status to get ALL matters, "Open" to get only open ones
            status = None if include_archived else "Open"
            synced_count = 0

            async for matter_data in clio.get_matters(status=status):
                # Check if matter exists
                result = await db.execute(
                    select(Matter).where(
                        Matter.user_id == current_user.id,
                        Matter.clio_matter_id == str(matter_data["id"])
                    )
                )
                matter = result.scalar_one_or_none()

                # Extract nested fields - Clio returns {status: {name: "Open"}} not {status: "Open"}
                # Handle both dict (nested) and string (direct) responses
                def extract_nested(data, field):
                    val = data.get(field)
                    if val is None:
                        return None
                    if isinstance(val, dict):
                        return val.get("name")
                    return str(val)  # If it's already a string, use it directly

                status_name = extract_nested(matter_data, "status")
                practice_area_name = extract_nested(matter_data, "practice_area")
                client_name = extract_nested(matter_data, "client")

                # Skip matters without a client (check both client_name and display_number)
                display_number = matter_data.get("display_number", "")
                if not client_name or "No Client Associated" in (display_number or ""):
                    continue

                if matter:
                    # Update existing - use direct SQL UPDATE to bypass ORM tracking issues
                    await db.execute(
                        update(Matter)
                        .where(Matter.id == matter.id)
                        .values(
                            display_number=matter_data.get("display_number"),
                            description=matter_data.get("description"),
                            status=status_name,
                            practice_area=practice_area_name,
                            client_name=client_name,
                            last_synced_at=datetime.utcnow()
                        )
                    )
                else:
                    # Create new
                    matter = Matter(
                        user_id=current_user.id,
                        clio_matter_id=str(matter_data["id"]),
                        display_number=matter_data.get("display_number"),
                        description=matter_data.get("description"),
                        status=status_name,
                        practice_area=practice_area_name,
                        client_name=client_name,
                        last_synced_at=datetime.utcnow()
                    )
                    db.add(matter)

                synced_count += 1

                # Commit in batches
                if synced_count % 100 == 0:
                    await db.flush()
                    await db.commit()
                    print(f"SYNC: Synced {synced_count} matters...")

            # Final commit for remaining items
            await db.flush()
            await db.commit()
            print(f"SYNC: Complete - {synced_count} matters synced")

        return {
            "success": True,
            "matters_synced": synced_count
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Sync failed: {str(e)}"
        )
