"""Matter routes for syncing and browsing Clio matters"""
import logging
from typing import Optional
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, delete, distinct, asc, desc, text

from app.core.security import decrypt_token
from app.db.session import get_db
from app.db.models import Matter, Document, Witness, ClioIntegration, User, ProcessingJob, JobStatus, SyncStatus
from app.api.v1.schemas.witnesses import MatterResponse, MatterListResponse, DocumentResponse
from app.services.clio_client import ClioClient
from app.api.deps import get_current_user
# renumber_all_jobs removed - job_number now equals job.id
from app.worker.tasks import sync_matter_documents, sync_all_user_matters

router = APIRouter(prefix="/matters", tags=["Matters"])


@router.post("/sync-all")
async def sync_all_matters_endpoint(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Trigger background sync for all matters belonging to the current user.
    Called automatically when user enters the matters page.
    """
    # Queue the sync task
    task = sync_all_user_matters.delay(current_user.id)
    
    return {
        "success": True,
        "message": "Document sync started in background",
        "task_id": task.id
    }


@router.get("/sync-status")
async def get_sync_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the current sync status for the user.
    Returns whether any matters are currently syncing.
    Used by frontend to determine when to hide the sync overlay.
    """
    # Check if any matters are currently syncing
    result = await db.execute(
        select(func.count(Matter.id)).where(
            Matter.user_id == current_user.id,
            Matter.sync_status == SyncStatus.SYNCING
        )
    )
    syncing_count = result.scalar() or 0

    # Check for stale syncs (started more than 30 minutes ago)
    stale_timeout = timedelta(minutes=30)
    stale_check = await db.execute(
        select(Matter).where(
            Matter.user_id == current_user.id,
            Matter.sync_status == SyncStatus.SYNCING,
            Matter.sync_started_at.isnot(None),
            Matter.sync_started_at < datetime.utcnow() - stale_timeout
        )
    )
    stale_matters = stale_check.scalars().all()

    # Auto-recover stale syncs
    for matter in stale_matters:
        matter.sync_status = SyncStatus.IDLE
        matter.sync_started_at = None
        syncing_count -= 1
        logger.info(f"Auto-recovered stale sync for matter {matter.id}")

    if stale_matters:
        await db.commit()

    return {
        "is_syncing": syncing_count > 0,
        "syncing_count": syncing_count,
        "recovered_stale_count": len(stale_matters)
    }


@router.post("/{matter_id}/sync")
async def sync_single_matter_endpoint(
    matter_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Trigger background sync for a specific matter.
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
    
    # Queue the sync task
    task = sync_matter_documents.delay(matter_id, current_user.id)
    
    return {
        "success": True,
        "message": f"Sync started for matter {matter_id}",
        "task_id": task.id
    }


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


@router.get("/{matter_id}/folders")
async def get_matter_folders(
    matter_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the folder tree for a matter from Clio.
    Returns a nested structure of folders.
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

    # Get Clio integration
    integration_result = await db.execute(
        select(ClioIntegration).where(
            ClioIntegration.user_id == current_user.id,
            ClioIntegration.is_active == True
        )
    )
    integration = integration_result.scalar_one_or_none()

    if not integration:
        raise HTTPException(status_code=400, detail="Clio integration not connected")

    try:
        access_token = decrypt_token(integration.access_token_encrypted)
        refresh_token = decrypt_token(integration.refresh_token_encrypted)

        async with ClioClient(
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=integration.token_expires_at,
            region=integration.clio_region
        ) as clio:
            folder_tree = await clio.get_folder_tree(int(matter.clio_matter_id))
            return {"folders": folder_tree}

    except Exception as e:
        logger.error(f"Failed to get folders: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get folders: {str(e)}")


from pydantic import BaseModel
from typing import Optional, List

class ProcessMatterRequest(BaseModel):
    scan_folder_id: Optional[int] = None  # Folder to scan for documents (None = all documents)
    legal_authority_folder_id: Optional[int] = None  # Folder with legal authorities for RAG
    include_subfolders: bool = True  # Whether to scan subfolders recursively


@router.post("/{matter_id}/process")
async def process_matter(
    matter_id: int,
    request: Optional[ProcessMatterRequest] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Start processing a matter to extract witnesses from its documents.

    Args:
        matter_id: The matter ID to process
        request: Optional processing options:
            - scan_folder_id: Specific folder to scan (None = all documents)
            - legal_authority_folder_id: Folder with case law for AI context
            - include_subfolders: Whether to include subfolders (default: True)
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

    # Check if sync is in progress (with stale sync detection)
    SYNC_STALE_TIMEOUT = timedelta(minutes=30)
    if matter.sync_status == SyncStatus.SYNCING:
        # Check if sync started more than 30 minutes ago (likely crashed worker)
        if matter.sync_started_at and (datetime.utcnow() - matter.sync_started_at) > SYNC_STALE_TIMEOUT:
            # Auto-recover from stale sync
            matter.sync_status = SyncStatus.FAILED
            matter.sync_started_at = None
            await db.commit()
            logger.warning(f"Auto-recovered stale sync for matter {matter_id} (started {matter.sync_started_at})")
        else:
            raise HTTPException(
                status_code=409,
                detail="Matter is currently syncing. Please wait for sync to complete."
            )

    # Parse request options
    scan_folder_id = None
    legal_authority_folder_id = None
    include_subfolders = True

    if request:
        scan_folder_id = request.scan_folder_id
        legal_authority_folder_id = request.legal_authority_folder_id
        include_subfolders = request.include_subfolders

    # Debug logging
    logger.info(f"[PROCESS] matter_id={matter_id}, scan_folder_id={scan_folder_id}, legal_authority_folder_id={legal_authority_folder_id}, include_subfolders={include_subfolders}")

    # Get Clio integration for syncing documents
    integration_result = await db.execute(
        select(ClioIntegration).where(
            ClioIntegration.user_id == current_user.id,
            ClioIntegration.is_active == True
        )
    )
    integration = integration_result.scalar_one_or_none()

    if not integration:
        raise HTTPException(status_code=400, detail="Clio integration not connected")

    # AUTO-SYNC: Sync documents from Clio if needed (foolproof user experience)
    # This ensures users never see "No documents found" when Clio has documents
    access_token = decrypt_token(integration.access_token_encrypted)
    refresh_token = decrypt_token(integration.refresh_token_encrypted)

    async with ClioClient(
        access_token=access_token,
        refresh_token=refresh_token,
        token_expires_at=integration.token_expires_at,
        region=integration.clio_region
    ) as clio:
        # Fetch documents from Clio and sync to local database
        logger.info(f"Auto-syncing documents for matter {matter_id} from Clio")
        synced_count = 0
        synced_clio_doc_ids = []  # Track Clio document IDs for snapshot

        try:
            if scan_folder_id:
                # Sync documents from specific folder
                if include_subfolders:
                    logger.info(f"[PROCESS] Using get_documents_recursive for folder {scan_folder_id}")
                    doc_iterator = clio.get_documents_recursive(
                        matter_id=int(matter.clio_matter_id),
                        folder_id=scan_folder_id,
                        exclude_folder_ids=[legal_authority_folder_id] if legal_authority_folder_id else None
                    )
                else:
                    logger.info(f"[PROCESS] Using get_documents_in_folder for folder {scan_folder_id} (NO subfolders)")
                    doc_iterator = clio.get_documents_in_folder(
                        scan_folder_id,
                        matter_id=int(matter.clio_matter_id)
                    )
            else:
                # Sync all documents for matter
                logger.info(f"[PROCESS] Using get_documents for all matter documents")
                doc_iterator = clio.get_documents(matter_id=int(matter.clio_matter_id))

            async for clio_doc in doc_iterator:
                # Skip if in legal authority folder
                if legal_authority_folder_id:
                    doc_folder = clio_doc.get("parent", {})
                    if doc_folder and doc_folder.get("id") == legal_authority_folder_id:
                        continue

                # Track this document for the snapshot
                synced_clio_doc_ids.append(str(clio_doc["id"]))

                # Check if document already exists locally
                existing = await db.execute(
                    select(Document).where(
                        Document.clio_document_id == str(clio_doc["id"]),
                        Document.matter_id == matter_id
                    )
                )
                existing_doc = existing.scalar_one_or_none()

                if existing_doc:
                    # Update existing document
                    existing_doc.filename = clio_doc.get("name", existing_doc.filename)
                    existing_doc.file_type = clio_doc.get("content_type")
                    existing_doc.clio_folder_id = str(clio_doc.get("parent", {}).get("id")) if clio_doc.get("parent") else None
                    existing_doc.is_soft_deleted = False  # Un-delete if it was soft-deleted
                else:
                    # Create new document record
                    new_doc = Document(
                        matter_id=matter_id,
                        clio_document_id=str(clio_doc["id"]),
                        filename=clio_doc.get("name", "Untitled"),
                        file_type=clio_doc.get("content_type"),
                        clio_folder_id=str(clio_doc.get("parent", {}).get("id")) if clio_doc.get("parent") else None,
                        is_soft_deleted=False
                    )
                    db.add(new_doc)

                synced_count += 1

            await db.commit()
            logger.info(f"Auto-synced {synced_count} documents for matter {matter_id}")

            # Update matter sync timestamp
            matter.last_synced_at = datetime.utcnow()
            await db.commit()

        except Exception as e:
            logger.error(f"Error syncing documents from Clio: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to sync documents from Clio: {str(e)}")

    # Build document snapshot from the exact documents that were synced
    # This ensures subfolder documents are included when include_subfolders=True
    if synced_clio_doc_ids:
        # Use the exact documents that were synced (respects include_subfolders setting)
        result = await db.execute(
            select(Document.id).where(
                Document.matter_id == matter_id,
                Document.clio_document_id.in_(synced_clio_doc_ids),
                Document.is_soft_deleted == False
            )
        )
        document_ids = [row[0] for row in result.all()]
        logger.info(f"Document snapshot: {len(document_ids)} documents from sync (include_subfolders={include_subfolders})")
    else:
        # Fallback: No documents synced, query from database
        doc_query = select(Document.id).where(
            Document.matter_id == matter_id,
            Document.is_soft_deleted == False
        )
        if legal_authority_folder_id:
            doc_query = doc_query.where(Document.clio_folder_id != str(legal_authority_folder_id))
        result = await db.execute(doc_query)
        document_ids = [row[0] for row in result.all()]
        logger.info(f"Document snapshot: {len(document_ids)} documents from database fallback")

    if not document_ids:
        raise HTTPException(
            status_code=400,
            detail="No documents found in the selected folder. Please select a different folder or check that documents exist in Clio."
        )

    # Create job record with document snapshot
    job = ProcessingJob(
        user_id=current_user.id,
        job_type="single_matter",
        target_matter_id=matter_id,
        status=JobStatus.PENDING,
        total_documents=len(document_ids),
        document_ids_snapshot=document_ids  # Freeze the document list
    )
    db.add(job)
    await db.flush()  # Flush to get the job ID without committing

    # Set job_number to match database id
    job.job_number = job.id

    await db.commit()
    await db.refresh(job)

    # Start Celery task with folder options
    from app.worker.tasks import process_matter as process_matter_task
    task = process_matter_task.delay(
        job_id=job.id,
        matter_id=matter_id,
        search_targets=None,
        scan_folder_id=scan_folder_id,
        legal_authority_folder_id=legal_authority_folder_id,
        include_subfolders=include_subfolders
    )

    # Store task ID
    job.celery_task_id = task.id
    await db.commit()

    return {
        "id": job.id,
        "job_number": job.job_number,
        "status": job.status.value,
        "total_documents": len(document_ids),
        "message": f"Processing started for matter {matter.display_number}"
    }


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


@router.get("/{matter_id}/documents/count")
async def get_document_count(
    matter_id: int,
    folder_id: Optional[str] = None,
    include_subfolders: bool = Query(False, description="Include documents in subfolders"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the count of documents for a matter, optionally filtered by folder.
    Fetches count directly from Clio API for accuracy (not local DB).

    Args:
        matter_id: The matter ID
        folder_id: Optional Clio folder ID to filter by
        include_subfolders: Whether to include documents in subfolders (default: False)

    Returns:
        {count: int, folder_id: str|null, matter_id: int, include_subfolders: bool, source: "clio"}
    """
    # Debug logging to verify parameters
    logger.info(f"[DOC_COUNT] matter_id={matter_id}, folder_id={folder_id}, include_subfolders={include_subfolders}")
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

    # Get Clio integration for live document count
    integration_result = await db.execute(
        select(ClioIntegration).where(
            ClioIntegration.user_id == current_user.id,
            ClioIntegration.is_active == True
        )
    )
    integration = integration_result.scalar_one_or_none()

    if not integration:
        raise HTTPException(status_code=400, detail="Clio integration not connected")

    try:
        access_token = decrypt_token(integration.access_token_encrypted)
        refresh_token = decrypt_token(integration.refresh_token_encrypted)

        async with ClioClient(
            access_token=access_token,
            refresh_token=refresh_token,
            token_expires_at=integration.token_expires_at,
            region=integration.clio_region
        ) as clio:
            count = 0
            # Use minimal fields for speed - just need to count
            fields = ["id"]

            if folder_id:
                if include_subfolders:
                    # Count documents recursively in folder and all subfolders
                    async for _ in clio.get_documents_recursive(
                        matter_id=int(matter.clio_matter_id),
                        folder_id=int(folder_id),
                        fields=fields
                    ):
                        count += 1
                else:
                    # Count documents in specific folder only (not subfolders)
                    async for _ in clio.get_documents_in_folder(
                        int(folder_id),
                        matter_id=int(matter.clio_matter_id),
                        fields=fields
                    ):
                        count += 1
            else:
                # Count all documents for the matter
                async for _ in clio.get_documents(matter_id=int(matter.clio_matter_id), fields=fields):
                    count += 1

            # Return count with debug info
            from datetime import datetime
            return {
                "count": count,
                "folder_id": folder_id,
                "include_subfolders": include_subfolders,
                "matter_id": matter_id,
                "sync_status": matter.sync_status.value if matter.sync_status else "idle",
                "last_synced_at": matter.last_synced_at.isoformat() if matter.last_synced_at else None,
                "source": "clio",
                "debug_timestamp": datetime.utcnow().isoformat(),
                "debug_method": "recursive" if (folder_id and include_subfolders) else ("direct" if folder_id else "all_matter")
            }

    except Exception as e:
        logger.error(f"Failed to get document count from Clio: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get document count: {str(e)}")


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

    # Only clear existing matters if explicitly requested (preserves documents!)
    # NOTE: Deleting matters CASCADE DELETES all documents - avoid unless necessary
    if clear_existing:
        print(f"SYNC: Clearing existing matters for user {current_user.id}")
        # First delete processing jobs that reference these matters (foreign key constraint)
        await db.execute(
            delete(ProcessingJob).where(ProcessingJob.user_id == current_user.id)
        )
        # Then delete the matters (CASCADE deletes documents!)
        await db.execute(
            delete(Matter).where(Matter.user_id == current_user.id)
        )
        await db.commit()
        print("SYNC: Existing jobs and matters cleared")

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

        # Trigger document sync for all matters in background
        # This ensures documents are synced after matters are created/updated
        sync_all_user_matters.delay(current_user.id)
        print(f"SYNC: Queued document sync for all matters")

        return {
            "success": True,
            "matters_synced": synced_count,
            "document_sync_queued": True
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Sync failed: {str(e)}"
        )
