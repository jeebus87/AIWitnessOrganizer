"""Celery background tasks for document processing and witness extraction"""
import asyncio
import gc
from datetime import datetime
from typing import List, Optional, Dict, Any

from celery import shared_task, group, chord
from celery.utils.log import get_task_logger
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from app.worker.celery_app import celery_app
from app.worker.db import get_worker_session
from app.core.config import settings
from app.core.security import decrypt_token
from app.db.models import (
    User, ClioIntegration, Matter, Document, Witness,
    ProcessingJob, JobStatus, WitnessRole, ImportanceLevel, RelevanceLevel,
    SyncStatus, CaseClaim, ClaimType, WitnessClaimLink, LegalResearchResult, LegalResearchStatus
)
from app.services.clio_client import ClioClient
from app.services.document_processor import DocumentProcessor
from app.services.bedrock_client import BedrockClient
from app.services.legal_authority_service import LegalAuthorityService
from app.services.canonicalization_service import CanonicalizationService, WitnessInput
from app.services.legal_research_service import get_legal_research_service

logger = get_task_logger(__name__)


def run_async(coro):
    """Run async function in sync context"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _parse_claim_ref(claim_ref: str) -> tuple:
    """
    Parse a claim reference like "A1" or "D2" into claim_type and claim_number.
    Returns (claim_type: ClaimType, claim_number: int) or (None, None) if invalid.
    """
    if not claim_ref or len(claim_ref) < 2:
        return None, None

    prefix = claim_ref[0].upper()
    try:
        number = int(claim_ref[1:])
    except ValueError:
        return None, None

    if prefix == "A":
        return ClaimType.ALLEGATION, number
    elif prefix == "D":
        return ClaimType.DEFENSE, number
    else:
        return None, None


# === WORK PRODUCT & ATTORNEY EXCLUSION FILTERS ===

STRONG_FILENAME_PATTERNS = [
    "confidential notes", "work product", "attorney notes",
    "privileged", "internal memo", "legal memo", "draft motion",
    "strategy", "research memo"
]

STRONG_HEADER_PATTERNS = [
    "ATTORNEY WORK PRODUCT",
    "PREPARED IN ANTICIPATION OF LITIGATION",
    "ATTORNEY-CLIENT PRIVILEGED",
    "CONFIDENTIAL LEGAL MEMORANDUM"
]

CASE_ATTORNEY_EXCLUSION_PHRASES = [
    "counsel for", "attorney for", "represents",
    "on behalf of", "representing", "legal counsel"
]


def _is_work_product(filename: str, content_preview: str) -> bool:
    """
    Return True if document should be skipped as attorney work product.

    Args:
        filename: Document filename
        content_preview: First ~2KB of document content
    """
    filename_lower = filename.lower()
    if any(p in filename_lower for p in STRONG_FILENAME_PATTERNS):
        return True

    content_upper = content_preview[:2048].upper() if content_preview else ""
    return any(p in content_upper for p in STRONG_HEADER_PATTERNS)


def _is_case_attorney(witness_role: str, observation: str) -> bool:
    """
    Return True if witness should be excluded as case attorney of record.

    Args:
        witness_role: The extracted role (e.g., "attorney")
        observation: The observation text about the witness
    """
    if witness_role != "attorney":
        return False

    observation_lower = (observation or "").lower()
    return any(phrase in observation_lower for phrase in CASE_ATTORNEY_EXCLUSION_PHRASES)


@celery_app.task(bind=True)
def sync_matter_documents(self, matter_id: int, user_id: int):
    """
    Sync documents from Clio for a specific matter.
    This is separate from processing - just updates the local document cache.
    """
    return run_async(_sync_matter_documents_async(matter_id, user_id))


async def _sync_matter_documents_async(matter_id: int, user_id: int, force: bool = False):
    """
    Async implementation of document sync with locking and mark-and-sweep.

    Args:
        matter_id: Database ID of the matter
        user_id: Database ID of the user
        force: If True, skip the lock check (for internal use only)
    """
    async with get_worker_session() as session:
        # Get matter
        result = await session.execute(
            select(Matter).where(Matter.id == matter_id)
        )
        matter = result.scalar_one_or_none()

        if not matter:
            logger.error(f"Matter {matter_id} not found for sync")
            return {"success": False, "error": "Matter not found"}

        # Check if sync is already in progress (unless force=True)
        if not force and matter.sync_status == SyncStatus.SYNCING:
            logger.warning(f"Matter {matter_id} is already syncing, skipping")
            return {"success": False, "error": "Sync already in progress"}

        # Acquire lock
        matter.sync_status = SyncStatus.SYNCING
        matter.sync_started_at = datetime.utcnow()
        await session.commit()

        try:
            # Get user's Clio integration
            result = await session.execute(
                select(ClioIntegration).where(ClioIntegration.user_id == user_id)
            )
            clio_integration = result.scalar_one_or_none()

            if not clio_integration:
                logger.error(f"No Clio integration for user {user_id}")
                matter.sync_status = SyncStatus.FAILED
                matter.sync_started_at = None  # Clear stale detection timestamp
                await session.commit()
                return {"success": False, "error": "Clio integration not found"}

            # Decrypt tokens
            access_token = decrypt_token(clio_integration.access_token_encrypted)
            refresh_token = decrypt_token(clio_integration.refresh_token_encrypted)

            logger.info(f"Syncing documents for matter {matter_id} (Clio ID: {matter.clio_matter_id})")

            async with ClioClient(
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=clio_integration.token_expires_at,
                region=clio_integration.clio_region
            ) as clio:
                docs_synced = 0
                docs_updated = 0
                docs_soft_deleted = 0

                # STEP 1: Get ALL document IDs from Clio (mark phase)
                logger.info(f"Fetching all documents from Clio for matter {matter_id}")
                clio_doc_ids = set()
                all_clio_docs = []

                doc_iterator = clio.get_all_matter_documents_via_folders(
                    matter_id=int(matter.clio_matter_id),
                    exclude_folder_ids=[]
                )

                async for doc_data in doc_iterator:
                    clio_doc_ids.add(str(doc_data["id"]))
                    all_clio_docs.append(doc_data)

                logger.info(f"Found {len(all_clio_docs)} documents in Clio")

                # STEP 2: Soft-delete local docs NOT in Clio (sweep phase)
                result = await session.execute(
                    select(Document.id, Document.clio_document_id).where(
                        Document.matter_id == matter.id,
                        Document.is_soft_deleted == False
                    )
                )
                local_docs = result.all()

                # SAFETY CHECK: If Clio returned 0 documents but we have local docs,
                # this is likely an API issue (rate limit, timeout) - skip soft-delete
                if len(all_clio_docs) == 0 and len(local_docs) > 0:
                    logger.warning(
                        f"Clio returned 0 documents for matter {matter_id} but we have "
                        f"{len(local_docs)} local documents - skipping soft-delete (possible API issue)"
                    )
                else:
                    docs_to_delete_ids = []
                    for doc_id, clio_doc_id in local_docs:
                        if clio_doc_id not in clio_doc_ids:
                            docs_to_delete_ids.append(doc_id)

                    if docs_to_delete_ids:
                        await session.execute(
                            update(Document)
                            .where(Document.id.in_(docs_to_delete_ids))
                            .values(is_soft_deleted=True)
                        )
                        docs_soft_deleted = len(docs_to_delete_ids)
                        logger.info(f"Soft-deleted {docs_soft_deleted} documents no longer in Clio")

                # STEP 3: Upsert documents from Clio
                for doc_data in all_clio_docs:
                    clio_doc_id = str(doc_data["id"])
                    doc_name = doc_data.get("name", "unknown")

                    result = await session.execute(
                        select(Document).where(
                            Document.matter_id == matter.id,
                            Document.clio_document_id == clio_doc_id
                        )
                    )
                    doc = result.scalar_one_or_none()

                    if not doc:
                        # New document
                        doc = Document(
                            matter_id=matter.id,
                            clio_document_id=clio_doc_id,
                            filename=doc_name,
                            file_type=doc_data.get("content_type", "").split("/")[-1] if doc_data.get("content_type") else None,
                            file_size=doc_data.get("size"),
                            etag=doc_data.get("etag"),
                            clio_folder_id=str(doc_data.get("parent", {}).get("id")) if doc_data.get("parent") else None,
                            is_soft_deleted=False
                        )
                        session.add(doc)
                        docs_synced += 1
                    else:
                        # Update existing document metadata and un-delete if needed
                        doc.filename = doc_name
                        doc.file_size = doc_data.get("size")
                        doc.etag = doc_data.get("etag")
                        doc.clio_folder_id = str(doc_data.get("parent", {}).get("id")) if doc_data.get("parent") else None
                        doc.is_soft_deleted = False  # Un-delete if it was soft-deleted
                        docs_updated += 1

                await session.commit()

                # Update matter's last sync time and release lock
                matter.last_synced_at = datetime.utcnow()
                matter.sync_status = SyncStatus.IDLE
                matter.sync_started_at = None  # Clear stale detection timestamp
                await session.commit()

                logger.info(f"Sync complete for matter {matter_id}: {docs_synced} new, {docs_updated} updated, {docs_soft_deleted} deleted")

                return {
                    "success": True,
                    "matter_id": matter_id,
                    "documents_synced": docs_synced,
                    "documents_updated": docs_updated,
                    "documents_deleted": docs_soft_deleted,
                    "total_documents": len(all_clio_docs)
                }

        except Exception as e:
            # Release lock on error
            logger.error(f"Sync failed for matter {matter_id}: {e}")
            matter.sync_status = SyncStatus.FAILED
            matter.sync_started_at = None  # Clear stale detection timestamp
            await session.commit()
            raise


@celery_app.task(bind=True)
def sync_all_user_matters(self, user_id: int):
    """
    Sync documents for all matters belonging to a user.
    Called when user enters the matters page.
    """
    return run_async(_sync_all_user_matters_async(user_id))


async def _sync_all_user_matters_async(user_id: int):
    """Async implementation of sync all matters"""
    async with get_worker_session() as session:
        # Get all matters for this user
        result = await session.execute(
            select(Matter).where(Matter.user_id == user_id)
        )
        matters = result.scalars().all()
        
        if not matters:
            return {"success": True, "matters_synced": 0}
        
        logger.info(f"Starting background sync for {len(matters)} matters for user {user_id}")
        
        # Queue sync tasks for each matter
        for matter in matters:
            sync_matter_documents.delay(matter.id, user_id)
        
        return {
            "success": True,
            "matters_queued": len(matters)
        }


@celery_app.task(bind=True, max_retries=3)
def process_single_document(
    self,
    document_id: int,
    search_targets: Optional[List[str]] = None,
    legal_context: Optional[str] = None,
    job_id: Optional[int] = None
):
    """
    Process a single document for witness extraction.

    Args:
        document_id: Database ID of the document
        search_targets: Optional list of specific names to search for
        legal_context: Optional legal standards context from RAG
        job_id: Optional job ID for progress tracking
    """
    return run_async(_process_single_document_async(
        self, document_id, search_targets, legal_context, job_id
    ))


async def _process_single_document_async(
    task,
    document_id: int,
    search_targets: Optional[List[str]] = None,
    legal_context: Optional[str] = None,
    job_id: Optional[int] = None
):
    """Async implementation of document processing"""
    async with get_worker_session() as session:
        # Get document with related data
        result = await session.execute(
            select(Document)
            .options(selectinload(Document.matter))
            .where(Document.id == document_id)
        )
        document = result.scalar_one_or_none()

        if not document:
            logger.error(f"Document {document_id} not found")
            return {"success": False, "error": "Document not found"}

        # Get user's Clio integration
        matter = document.matter
        result = await session.execute(
            select(ClioIntegration)
            .where(ClioIntegration.user_id == matter.user_id)
        )
        clio_integration = result.scalar_one_or_none()

        if not clio_integration:
            logger.error(f"No Clio integration for user {matter.user_id}")
            return {"success": False, "error": "Clio integration not found"}

        try:
            # Decrypt tokens
            access_token = decrypt_token(clio_integration.access_token_encrypted)
            refresh_token = decrypt_token(clio_integration.refresh_token_encrypted)

            # Download document from Clio
            async with ClioClient(
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=clio_integration.token_expires_at,
                region=clio_integration.clio_region
            ) as clio:
                # Refresh document info if filename is unknown
                if document.filename == "unknown" or not document.filename:
                    logger.info(f"Refreshing document info from Clio for document {document.id}")
                    doc_info = await clio.get_document(int(document.clio_document_id))
                    if doc_info.get("name"):
                        document.filename = doc_info["name"]
                        document.file_type = doc_info.get("content_type", "").split("/")[-1] if doc_info.get("content_type") else None
                        await session.commit()
                        logger.info(f"Updated document filename to: {document.filename}")

                content = await clio.download_document(int(document.clio_document_id))

            # === WORK PRODUCT FILTER ===
            # Check if document is attorney work product before processing
            content_preview = content[:2048].decode('utf-8', errors='ignore') if content else ""
            if _is_work_product(document.filename or "", content_preview):
                logger.info(f"Document {document_id} is attorney work product, skipping witness extraction")
                document.is_processed = True
                document.processing_error = "Skipped: Attorney work product"
                await session.commit()

                # Update job progress
                if job_id:
                    from sqlalchemy import text
                    await session.execute(
                        text("UPDATE processing_jobs SET processed_documents = processed_documents + 1, last_activity_at = NOW() WHERE id = :job_id"),
                        {"job_id": job_id}
                    )
                    await session.commit()

                return {
                    "success": True,
                    "document_id": document_id,
                    "witnesses_found": 0,
                    "tokens_used": 0,
                    "skipped": True,
                    "reason": "Attorney work product"
                }

            # === CONTENT HASH CACHING ===
            # Calculate file hash upfront for caching
            processor = DocumentProcessor()
            file_hash = processor.get_file_hash(content)

            # Check if document is unchanged and already processed (skip re-processing)
            if document.content_hash == file_hash and document.is_processed:
                logger.info(f"Document {document_id} unchanged (hash match), skipping re-processing")

                # Still update job progress
                if job_id:
                    from sqlalchemy import text
                    await session.execute(
                        text("UPDATE processing_jobs SET processed_documents = processed_documents + 1, last_activity_at = NOW() WHERE id = :job_id"),
                        {"job_id": job_id}
                    )
                    await session.commit()

                return {
                    "success": True,
                    "document_id": document_id,
                    "witnesses_found": 0,
                    "tokens_used": 0,
                    "cached": True,
                    "message": "Document unchanged, skipped re-processing"
                }

            # === DEBUG MODE: Skip Bedrock processing ===
            DEBUG_MODE = False  # Set to True to skip AI processing for debugging

            logger.info(f"")
            logger.info(f"{'='*60}")
            logger.info(f"=== PROCESSING DOCUMENT ===")
            logger.info(f"{'='*60}")
            logger.info(f"  Document ID (db): {document_id}")
            logger.info(f"  Clio Document ID: {document.clio_document_id}")
            logger.info(f"  Filename: {document.filename}")
            logger.info(f"  File type: {document.file_type}")
            logger.info(f"  File size (from Clio): {document.file_size}")
            logger.info(f"  Downloaded content size: {len(content)} bytes")
            logger.info(f"  Content hash: {file_hash}")
            logger.info(f"  Previous hash: {document.content_hash}")
            logger.info(f"  Matter ID: {document.matter_id}")
            logger.info(f"  Job ID: {job_id}")
            logger.info(f"  DEBUG_MODE: {DEBUG_MODE}")
            logger.info(f"{'='*60}")

            if DEBUG_MODE:
                logger.info(f"DEBUG: Skipping Bedrock processing - just marking document as processed")

                # Update job progress and activity timestamp
                if job_id:
                    from sqlalchemy import text
                    await session.execute(
                        text("UPDATE processing_jobs SET processed_documents = processed_documents + 1, last_activity_at = NOW() WHERE id = :job_id"),
                        {"job_id": job_id}
                    )
                    await session.commit()
                    logger.info(f"DEBUG: Incremented processed_documents for job {job_id}")

                return {
                    "success": True,
                    "document_id": document_id,
                    "witnesses_found": 0,
                    "tokens_used": 0,
                    "debug_mode": True
                }

            # === END DEBUG MODE ===

            # Initialize AI client (processor already created above for hash)
            bedrock = BedrockClient()

            # Check if this is a large PDF that needs chunked processing
            # Large = > 20MB, which typically means 100+ pages
            is_large_pdf = (
                len(content) > 20 * 1024 * 1024 and
                (document.filename.lower().endswith('.pdf') or content[:4] == b'%PDF')
            )
            
            all_witnesses = []
            
            if is_large_pdf:
                logger.info(f"Large PDF detected ({len(content)} bytes), using chunked processing")
                
                # Process PDF in chunks to avoid memory exhaustion
                chunk_num = 0
                async for chunk_assets in processor.process_pdf_chunked(
                    content=content,
                    filename=document.filename,
                    chunk_size=30  # Process 30 pages at a time
                ):
                    chunk_num += 1
                    logger.info(f"Processing chunk {chunk_num} with {len(chunk_assets)} pages")
                    
                    # Extract witnesses from this chunk
                    extraction_result = await bedrock.extract_witnesses(
                        assets=chunk_assets,
                        search_targets=search_targets,
                        legal_context=legal_context
                    )
                    
                    if extraction_result.success:
                        all_witnesses.extend(extraction_result.witnesses)
                        logger.info(f"Chunk {chunk_num}: found {len(extraction_result.witnesses)} witnesses")
                    else:
                        logger.warning(f"Chunk {chunk_num} extraction failed: {extraction_result.error}")
                    
                    # Clear chunk memory
                    del chunk_assets
                    gc.collect()
                
                logger.info(f"Large PDF processing complete: {len(all_witnesses)} total witnesses found")
                
                # Create a mock successful extraction result with all witnesses
                from app.services.bedrock_client import ExtractionResult
                extraction_result = ExtractionResult(
                    success=True,
                    witnesses=all_witnesses
                )
            else:
                # Standard processing for smaller documents
                proc_result = await processor.process(
                    content=content,
                    filename=document.filename
                )

                if not proc_result.success:
                    document.processing_error = proc_result.error
                    await session.commit()
                    return {"success": False, "error": proc_result.error}

                # Extract witnesses using AI
                extraction_result = await bedrock.extract_witnesses(
                    assets=proc_result.assets,
                    search_targets=search_targets,
                    legal_context=legal_context
                )

                if not extraction_result.success:
                    document.processing_error = extraction_result.error
                    await session.commit()
                    return {"success": False, "error": extraction_result.error}

            # Run verification pass to improve accuracy
            verified_witnesses = await bedrock.verify_witnesses(
                extraction_result.witnesses,
                document.filename
            )
            logger.info(f"Verification complete: {len(verified_witnesses)} witnesses")

            # Delete existing witnesses for this document before adding new ones
            from sqlalchemy import delete
            delete_stmt = delete(Witness).where(Witness.document_id == document.id)
            await session.execute(delete_stmt)
            logger.info(f"Deleted existing witnesses for document {document.id}")

            # Initialize canonicalization service for deduplication + case attorney filtering
            canon_service = CanonicalizationService()

            # Save witnesses to database with canonicalization
            witnesses_created = 0
            witnesses_excluded = 0
            canonical_new = 0
            canonical_merged = 0

            for w_data in verified_witnesses:
                # Create witness input for canonicalization service
                witness_input = WitnessInput(
                    full_name=w_data.full_name,
                    role=w_data.role,
                    importance=w_data.importance,
                    observation=w_data.observation,
                    source_page=w_data.source_page,
                    email=w_data.email,
                    phone=w_data.phone,
                    address=w_data.address,
                    confidence_score=w_data.confidence_score,
                    relevance=getattr(w_data, 'relevance', None),
                    relevance_reason=getattr(w_data, 'relevance_reason', None)
                )

                # Canonicalize: deduplicate + filter case attorneys
                result = await canon_service.create_or_update_canonical(
                    db=session,
                    matter_id=document.matter_id,
                    witness_input=witness_input,
                    document_id=document.id,
                    filename=document.filename,
                    exclude_case_attorneys=True
                )

                if result.is_excluded:
                    logger.info(
                        f"Excluding: {w_data.full_name} - {result.exclusion_reason}"
                    )
                    witnesses_excluded += 1
                else:
                    # Update witness with job_id
                    if result.witness_record:
                        result.witness_record.job_id = job_id

                        # Save claim links if present
                        claim_links = getattr(w_data, 'claim_links', [])
                        if claim_links:
                            for link in claim_links:
                                claim_type, claim_number = _parse_claim_ref(link.claim_ref)
                                if claim_type and claim_number:
                                    # Find the matching claim
                                    claim_result = await session.execute(
                                        select(CaseClaim).where(
                                            CaseClaim.matter_id == document.matter_id,
                                            CaseClaim.claim_type == claim_type,
                                            CaseClaim.claim_number == claim_number
                                        )
                                    )
                                    claim = claim_result.scalar_one_or_none()

                                    if claim:
                                        # Create the witness-claim link
                                        witness_link = WitnessClaimLink(
                                            witness_id=result.witness_record.id,
                                            case_claim_id=claim.id,
                                            supports_or_undermines=link.relationship,
                                            relevance_explanation=link.explanation[:500] if link.explanation else None
                                        )
                                        session.add(witness_link)
                                        logger.debug(
                                            f"Linked witness {result.witness_record.id} to claim {link.claim_ref}"
                                        )

                    witnesses_created += 1
                    if result.is_new_canonical:
                        canonical_new += 1
                    else:
                        canonical_merged += 1

            if witnesses_excluded > 0:
                logger.info(f"Excluded {witnesses_excluded} case attorneys from document {document_id}")
            if canonical_merged > 0:
                logger.info(f"Merged {canonical_merged} witnesses into existing canonical records")

            # Update document status and save content hash for caching
            document.is_processed = True
            document.processed_at = datetime.utcnow()
            document.content_hash = file_hash  # Save hash for future cache checks
            tokens_used = extraction_result.input_tokens + extraction_result.output_tokens
            document.analysis_cache = {
                "witnesses_count": witnesses_created,
                "input_tokens": extraction_result.input_tokens,
                "output_tokens": extraction_result.output_tokens
            }
            document.analysis_cache_key = file_hash

            await session.commit()

            logger.info(f"Document {document_id} processed: {witnesses_created} witnesses found")

            # Update job progress and activity timestamp (for parallel processing)
            if job_id:
                from sqlalchemy import text
                await session.execute(
                    text("UPDATE processing_jobs SET processed_documents = processed_documents + 1, last_activity_at = NOW() WHERE id = :job_id"),
                    {"job_id": job_id}
                )
                await session.commit()
                logger.info(f"=== PROGRESS UPDATE === Job {job_id}: incremented processed_documents (doc {document_id} SUCCESS)")

            # Clean up memory after successful processing
            del content
            del extraction_result
            gc.collect()

            return {
                "success": True,
                "document_id": document_id,
                "witnesses_found": witnesses_created,
                "tokens_used": tokens_used
            }

        except Exception as e:
            import traceback
            error_details = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
            logger.exception(f"Error processing document {document_id}: {error_details}")
            document.processing_error = error_details[:4000]  # Truncate to fit in column
            await session.commit()

            # Update job progress and activity timestamp even on failure (for parallel processing)
            if job_id:
                from sqlalchemy import text
                await session.execute(
                    text("UPDATE processing_jobs SET processed_documents = processed_documents + 1, last_activity_at = NOW() WHERE id = :job_id"),
                    {"job_id": job_id}
                )
                await session.commit()
                logger.info(f"=== PROGRESS UPDATE === Job {job_id}: incremented processed_documents (doc {document_id} FAILED)")

            # Clean up memory even on error
            gc.collect()

            # Return failure instead of retrying indefinitely
            return {"success": False, "error": str(e), "document_id": document_id}


@celery_app.task(bind=True)
def process_matter(
    self,
    job_id: int,
    matter_id: int,
    search_targets: Optional[List[str]] = None,
    scan_folder_id: Optional[int] = None,
    legal_authority_folder_id: Optional[int] = None,
    include_subfolders: bool = True
):
    """
    Process all documents in a matter.

    Args:
        job_id: ProcessingJob ID for progress tracking
        matter_id: Database ID of the matter
        search_targets: Optional list of specific names to search for
        scan_folder_id: Optional folder ID to scan (None = all documents)
        legal_authority_folder_id: Optional folder ID to exclude from scanning
        include_subfolders: Whether to include subfolders when scanning
    """
    return run_async(_process_matter_async(
        self, job_id, matter_id, search_targets,
        scan_folder_id, legal_authority_folder_id, include_subfolders
    ))


async def _process_matter_async(
    task,
    job_id: int,
    matter_id: int,
    search_targets: Optional[List[str]] = None,
    scan_folder_id: Optional[int] = None,
    legal_authority_folder_id: Optional[int] = None,
    include_subfolders: bool = True
):
    """Async implementation of matter processing"""
    async with get_worker_session() as session:
        # Update job status
        result = await session.execute(
            select(ProcessingJob).where(ProcessingJob.id == job_id)
        )
        job = result.scalar_one_or_none()

        if not job:
            return {"success": False, "error": "Job not found"}

        job.status = JobStatus.PROCESSING
        job.started_at = datetime.utcnow()
        await session.commit()

        try:
            # Get matter with user info
            result = await session.execute(
                select(Matter).where(Matter.id == matter_id)
            )
            matter = result.scalar_one_or_none()

            if not matter:
                job.status = JobStatus.FAILED
                job.error_message = "Matter not found"
                await session.commit()
                return {"success": False, "error": "Matter not found"}

            # Get user's Clio integration
            result = await session.execute(
                select(ClioIntegration).where(ClioIntegration.user_id == matter.user_id)
            )
            clio_integration = result.scalar_one_or_none()

            if not clio_integration:
                job.status = JobStatus.FAILED
                job.error_message = "No Clio integration found"
                await session.commit()
                return {"success": False, "error": "Clio integration not found"}

            # Documents should already be synced - just query from database
            # Sync happens on matters page load or manual sync, not during processing

            logger.info(f"")
            logger.info(f"{'='*60}")
            logger.info(f"=== PROCESSING MATTER (USING PRE-SYNCED DOCS) ===")
            logger.info(f"{'='*60}")
            logger.info(f"  Database matter_id: {matter_id}")
            logger.info(f"  Clio matter_id: {matter.clio_matter_id}")
            logger.info(f"  Job ID: {job_id}")
            logger.info(f"  scan_folder_id: {scan_folder_id}")
            logger.info(f"  legal_authority_folder_id: {legal_authority_folder_id}")
            logger.info(f"{'='*60}")

            # Check if job has a document snapshot (preferred - created at job creation time)
            if job.document_ids_snapshot:
                logger.info(f"Using document snapshot from job creation ({len(job.document_ids_snapshot)} documents)")
                snapshot_ids = job.document_ids_snapshot

                # Query actual Document objects that are unprocessed
                result = await session.execute(
                    select(Document).where(
                        Document.id.in_(snapshot_ids),
                        Document.is_processed == False,
                        Document.is_soft_deleted == False
                    )
                )
                unprocessed_docs = list(result.scalars().all())
                document_ids_to_process = [d.id for d in unprocessed_docs]

                if len(snapshot_ids) > len(unprocessed_docs):
                    logger.info(f"RESUME MODE: Skipping {len(snapshot_ids) - len(unprocessed_docs)} already-processed documents")
            else:
                # Fallback: Query documents from database (for backwards compatibility)
                logger.info(f"No snapshot - querying documents from database")
                result = await session.execute(
                    select(Document).where(
                        Document.matter_id == matter.id,
                        Document.is_soft_deleted == False
                    )
                )
                docs_in_scope = list(result.scalars().all())

                # Folder filtering (only works after documents have been synced with folder info)
                if scan_folder_id:
                    logger.info(f"Folder filter requested: {scan_folder_id}")
                    filtered = [d for d in docs_in_scope if hasattr(d, 'clio_folder_id') and d.clio_folder_id == str(scan_folder_id)]
                    if filtered:
                        docs_in_scope = filtered
                        logger.info(f"Filtered to {len(docs_in_scope)} documents in folder")
                    else:
                        logger.info(f"No folder filtering applied (documents may need re-sync)")

                # Exclude legal authority folder documents if specified
                if legal_authority_folder_id:
                    original_count = len(docs_in_scope)
                    docs_in_scope = [d for d in docs_in_scope if not (hasattr(d, 'clio_folder_id') and d.clio_folder_id == str(legal_authority_folder_id))]
                    if len(docs_in_scope) < original_count:
                        logger.info(f"Excluded {original_count - len(docs_in_scope)} legal authority documents")

                # Filter out already processed documents (for job resume)
                unprocessed_docs = [d for d in docs_in_scope if not d.is_processed]
                document_ids_to_process = [d.id for d in unprocessed_docs]

                if len(docs_in_scope) > len(unprocessed_docs):
                    logger.info(f"RESUME MODE: Skipping {len(docs_in_scope) - len(unprocessed_docs)} already-processed documents")

            logger.info(f"Found {len(document_ids_to_process)} unprocessed documents for processing")


            # Process Legal Authority folder if specified (needs Clio access for RAG)
            legal_context = ""
            if legal_authority_folder_id:
                logger.info(f"Processing Legal Authority folder: {legal_authority_folder_id}")

                # Decrypt tokens for legal authority access
                access_token = decrypt_token(clio_integration.access_token_encrypted)
                refresh_token = decrypt_token(clio_integration.refresh_token_encrypted)

                legal_auth_service = LegalAuthorityService()
                doc_processor = DocumentProcessor()

                async with ClioClient(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    token_expires_at=clio_integration.token_expires_at,
                    region=clio_integration.clio_region
                ) as clio:
                    # Get documents from the legal authority folder
                    async for la_doc in clio.get_documents_in_folder(
                        legal_authority_folder_id,
                        matter_id=int(matter.clio_matter_id)
                    ):
                        try:
                            # Download and process the legal authority document
                            doc_content = await clio.download_document(la_doc["id"])
                            if doc_content:
                                # Extract text from the document
                                assets = await doc_processor.process(doc_content, la_doc.get("name", "document"))
                                # Combine all text from assets
                                doc_text = ""
                                for asset in assets:
                                    if asset.asset_type in ("text", "email_body"):
                                        doc_text += asset.content.decode("utf-8", errors="replace") + "\n"

                                if doc_text.strip():
                                    # Process and embed the legal authority document
                                    await legal_auth_service.process_legal_authority_document(
                                        db=session,
                                        matter_id=matter_id,
                                        document_text=doc_text,
                                        filename=la_doc.get("name", "unknown"),
                                        clio_document_id=str(la_doc["id"]),
                                        clio_folder_id=str(legal_authority_folder_id)
                                    )
                                    logger.info(f"Processed legal authority: {la_doc.get('name')}")
                        except Exception as e:
                            logger.warning(f"Failed to process legal authority doc {la_doc.get('name')}: {e}")

                # Get legal context for witness extraction (outside clio context)
                legal_context = await legal_auth_service.get_legal_context_for_witness_extraction(
                    db=session,
                    matter_id=matter_id,
                    document_summary="Analyze witness relevance based on legal claims and defenses in this matter."
                )
                if legal_context:
                    logger.info(f"Retrieved legal context: {len(legal_context)} chars")

            # Use the already-filtered unprocessed documents (no need for another query)
            documents = unprocessed_docs

            logger.info(f"")
            logger.info(f"{'='*60}")
            logger.info(f"=== FINAL DOCUMENT COUNT ===")
            logger.info(f"{'='*60}")
            logger.info(f"  Job ID: {job_id}")
            logger.info(f"  Database matter_id: {matter_id}")
            logger.info(f"  scan_folder_id: {scan_folder_id}")
            logger.info(f"  Documents IDs collected: {len(document_ids_to_process)}")
            logger.info(f"  Documents retrieved from DB: {len(documents)}")
            logger.info(f"  Setting job.total_documents = {len(documents)}")
            logger.info(f"")
            logger.info(f"--- Document Details (first 20) ---")
            for i, doc in enumerate(documents[:20]):
                logger.info(f"  [{i+1}] db_id={doc.id}, clio_id={doc.clio_document_id}, name={doc.filename}")
            if len(documents) > 20:
                logger.info(f"  ... and {len(documents) - 20} more documents")
            logger.info(f"{'='*60}")

            job.total_documents = len(documents)
            await session.commit()
            logger.info(f"  Committed total_documents update to database")

            if not documents:
                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.utcnow()
                await session.commit()
                logger.info(f"No documents to process for job {job_id}")
                return {"success": True, "job_id": job_id, "documents_processed": 0, "witnesses_found": 0, "failed": 0}

            # PARALLEL PROCESSING: Create a group of tasks to process documents concurrently
            # This dramatically speeds up processing for large jobs (10k+ documents)
            logger.info(f"Launching parallel processing for {len(documents)} documents")

            processing_tasks = group(
                process_single_document.s(
                    document_id=doc.id,
                    search_targets=search_targets,
                    legal_context=legal_context,
                    job_id=job_id
                )
                for doc in documents
            )

            # Use chord to run finalize_job after all documents are processed
            processing_chord = chord(processing_tasks, finalize_job.s(job_id=job_id))
            processing_chord.apply_async()

            logger.info(f"Started parallel processing for job {job_id} with {len(documents)} documents")

            return {
                "success": True,
                "job_id": job_id,
                "message": f"Started processing {len(documents)} documents in parallel"
            }

        except Exception as e:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()
            await session.commit()

            logger.exception(f"Job {job_id} failed")
            return {"success": False, "error": str(e)}


@celery_app.task(bind=True)
def process_full_database(
    self,
    job_id: int,
    user_id: int,
    search_targets: Optional[List[str]] = None,
    include_archived: bool = False
):
    """
    Process all matters for a user (full database scan).

    Args:
        job_id: ProcessingJob ID for progress tracking
        user_id: User ID
        search_targets: Optional list of specific names to search for
        include_archived: Whether to include archived matters
    """
    return run_async(_process_full_database_async(
        self, job_id, user_id, search_targets, include_archived
    ))


async def _process_full_database_async(
    task,
    job_id: int,
    user_id: int,
    search_targets: Optional[List[str]] = None,
    include_archived: bool = False
):
    """Async implementation of full database processing"""
    async with get_worker_session() as session:
        # Update job status
        result = await session.execute(
            select(ProcessingJob).where(ProcessingJob.id == job_id)
        )
        job = result.scalar_one_or_none()

        if not job:
            return {"success": False, "error": "Job not found"}

        job.status = JobStatus.PROCESSING
        job.started_at = datetime.utcnow()
        await session.commit()

        try:
            # Get user's Clio integration
            result = await session.execute(
                select(ClioIntegration)
                .where(ClioIntegration.user_id == user_id)
            )
            clio_integration = result.scalar_one_or_none()

            if not clio_integration:
                job.status = JobStatus.FAILED
                job.error_message = "No Clio integration found"
                await session.commit()
                return {"success": False, "error": "Clio integration not found"}

            # Decrypt tokens
            access_token = decrypt_token(clio_integration.access_token_encrypted)
            refresh_token = decrypt_token(clio_integration.refresh_token_encrypted)

            # Sync matters from Clio
            async with ClioClient(
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=clio_integration.token_expires_at,
                region=clio_integration.clio_region
            ) as clio:
                # Get all matters
                status = "All" if include_archived else "Open"
                matters_synced = 0

                async for matter_data in clio.get_matters(status=status):
                    # Create or update matter in database
                    result = await session.execute(
                        select(Matter).where(
                            Matter.user_id == user_id,
                            Matter.clio_matter_id == str(matter_data["id"])
                        )
                    )
                    matter = result.scalar_one_or_none()

                    if not matter:
                        matter = Matter(
                            user_id=user_id,
                            clio_matter_id=str(matter_data["id"]),
                            display_number=matter_data.get("display_number"),
                            description=matter_data.get("description"),
                            status=matter_data.get("status"),
                            client_name=matter_data.get("client", {}).get("name"),
                            last_synced_at=datetime.utcnow()
                        )
                        session.add(matter)
                        await session.flush()

                    # Sync documents for this matter
                    async for doc_data in clio.get_documents(matter_id=int(matter_data["id"])):
                        result = await session.execute(
                            select(Document).where(
                                Document.matter_id == matter.id,
                                Document.clio_document_id == str(doc_data["id"])
                            )
                        )
                        doc = result.scalar_one_or_none()

                        if not doc:
                            doc = Document(
                                matter_id=matter.id,
                                clio_document_id=str(doc_data["id"]),
                                filename=doc_data.get("name", "unknown"),
                                file_type=doc_data.get("content_type", "").split("/")[-1],
                                file_size=doc_data.get("size"),
                                etag=doc_data.get("etag")
                            )
                            session.add(doc)

                    matters_synced += 1
                    await session.commit()

            logger.info(f"Synced {matters_synced} matters for user {user_id}")

            # Now get all unprocessed documents and process them
            result = await session.execute(
                select(Document)
                .join(Matter)
                .where(
                    Matter.user_id == user_id,
                    Document.is_processed == False
                )
            )
            documents = result.scalars().all()

            job.total_documents = len(documents)
            await session.commit()

            if not documents:
                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.utcnow()
                await session.commit()
                logger.info(f"No documents to process for job {job_id}")
                return {"success": True, "job_id": job_id, "documents_processed": 0, "witnesses_found": 0, "failed": 0}

            # PARALLEL PROCESSING: Create a group of tasks to process documents concurrently
            logger.info(f"Launching parallel processing for {len(documents)} documents")

            processing_tasks = group(
                process_single_document.s(
                    document_id=doc.id,
                    search_targets=search_targets,
                    job_id=job_id
                )
                for doc in documents
            )

            # Use chord to run finalize_job after all documents are processed
            processing_chord = chord(processing_tasks, finalize_job.s(job_id=job_id))
            processing_chord.apply_async()

            logger.info(f"Started parallel processing for job {job_id} with {len(documents)} documents")

            return {
                "success": True,
                "job_id": job_id,
                "message": f"Started processing {len(documents)} documents in parallel"
            }

        except Exception as e:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()
            await session.commit()

            logger.exception(f"Full database job {job_id} failed")
            return {"success": False, "error": str(e)}


@celery_app.task(bind=True)
def finalize_job(self, results: List[Dict[str, Any]], job_id: int):
    """
    Finalize a processing job after all documents have been processed in parallel.
    This task is used as a callback in a Celery chord.

    Args:
        results: List of results from all process_single_document tasks
        job_id: ProcessingJob ID to finalize
    """
    return run_async(_finalize_job_async(self, results, job_id))


async def _finalize_job_async(
    task,
    results: List[Dict[str, Any]],
    job_id: int
):
    """Async implementation of job finalization"""
    async with get_worker_session() as session:
        result = await session.execute(
            select(ProcessingJob).where(ProcessingJob.id == job_id)
        )
        job = result.scalar_one_or_none()

        if not job:
            logger.error(f"Finalize job: Job {job_id} not found")
            return {"success": False, "error": "Job not found"}

        total_witnesses = 0
        failed_count = 0
        successful_count = 0

        for res in results:
            if isinstance(res, dict) and res.get("success"):
                total_witnesses += res.get("witnesses_found", 0)
                successful_count += 1
            else:
                failed_count += 1

        job.processed_documents = successful_count + failed_count

        # Update job completion
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.utcnow()
        job.total_witnesses_found = total_witnesses
        job.failed_documents = failed_count
        job.result_summary = {
            "total_documents": job.total_documents,
            "processed": job.processed_documents,
            "failed": failed_count,
            "witnesses_found": total_witnesses
        }
        await session.commit()

        logger.info(f"Job {job_id} finalized. Processed: {job.processed_documents}, Witnesses: {total_witnesses}, Failed: {failed_count}")

        # Queue legal research if witnesses were found
        # This searches CourtListener for relevant case law based on extracted content
        if total_witnesses > 0 and job.target_matter_id and job.user_id:
            try:
                search_legal_authorities.delay(
                    job_id=job_id,
                    matter_id=job.target_matter_id,
                    user_id=job.user_id
                )
                logger.info(f"Queued legal research for job {job_id}")
            except Exception as e:
                logger.warning(f"Failed to queue legal research for job {job_id}: {e}")

        return {
            "success": True,
            "job_id": job_id,
            "documents_processed": job.processed_documents,
            "witnesses_found": total_witnesses,
            "failed": failed_count
        }


def _map_role(role_str: str) -> WitnessRole:
    """Map string role to WitnessRole enum"""
    role_map = {
        "plaintiff": WitnessRole.PLAINTIFF,
        "defendant": WitnessRole.DEFENDANT,
        "eyewitness": WitnessRole.EYEWITNESS,
        "expert": WitnessRole.EXPERT,
        "attorney": WitnessRole.ATTORNEY,
        "physician": WitnessRole.PHYSICIAN,
        "police_officer": WitnessRole.POLICE_OFFICER,
        "family_member": WitnessRole.FAMILY_MEMBER,
        "colleague": WitnessRole.COLLEAGUE,
        "bystander": WitnessRole.BYSTANDER,
        "mentioned": WitnessRole.MENTIONED,
    }
    return role_map.get(role_str.lower().replace(" ", "_"), WitnessRole.OTHER)


def _map_importance(importance_str: str) -> ImportanceLevel:
    """Map string importance to ImportanceLevel enum"""
    importance_map = {
        "high": ImportanceLevel.HIGH,
        "medium": ImportanceLevel.MEDIUM,
        "low": ImportanceLevel.LOW,
    }
    return importance_map.get(importance_str.lower(), ImportanceLevel.LOW)


@celery_app.task(bind=True)
def recover_stuck_jobs(self):
    """
    Recover jobs that are stuck in 'processing' status with no recent activity.
    Called on worker startup to resume interrupted jobs.
    """
    return run_async(_recover_stuck_jobs_async())


async def _recover_stuck_jobs_async():
    """Async implementation of stuck job recovery"""
    from datetime import timedelta

    async with get_worker_session() as session:
        # Find jobs that are "processing" but have no activity for > 5 minutes
        # These are likely jobs that were interrupted by a worker restart
        stale_threshold = datetime.utcnow() - timedelta(minutes=5)

        result = await session.execute(
            select(ProcessingJob).where(
                ProcessingJob.status == JobStatus.PROCESSING,
                ProcessingJob.is_resumable == True,
                # Either no activity timestamp or activity is stale
                (
                    (ProcessingJob.last_activity_at == None) |
                    (ProcessingJob.last_activity_at < stale_threshold)
                )
            )
        )
        stuck_jobs = result.scalars().all()

        if not stuck_jobs:
            logger.info("No stuck jobs found to recover")
            return {"recovered": 0}

        logger.info(f"Found {len(stuck_jobs)} stuck job(s) to recover")

        recovered_count = 0
        for job in stuck_jobs:
            try:
                logger.info(f"Recovering job {job.id} (type: {job.job_type}, matter: {job.target_matter_id})")

                # Update activity timestamp to prevent other workers from also recovering
                job.last_activity_at = datetime.utcnow()
                await session.commit()

                # Resume the job based on type
                if job.job_type == "single_matter" and job.target_matter_id:
                    # Resume matter processing - will skip already processed documents
                    process_matter.delay(
                        job_id=job.id,
                        matter_id=job.target_matter_id,
                        search_targets=job.search_witnesses
                    )
                    logger.info(f"Resumed single_matter job {job.id} for matter {job.target_matter_id}")
                    recovered_count += 1

                elif job.job_type == "full_database":
                    # Resume full database scan
                    process_full_database.delay(
                        job_id=job.id,
                        user_id=job.user_id,
                        search_targets=job.search_witnesses,
                        include_archived=job.include_archived
                    )
                    logger.info(f"Resumed full_database job {job.id} for user {job.user_id}")
                    recovered_count += 1

                else:
                    logger.warning(f"Unknown job type {job.job_type} for job {job.id}, marking as failed")
                    job.status = JobStatus.FAILED
                    job.error_message = "Could not recover: unknown job type"
                    await session.commit()

            except Exception as e:
                logger.exception(f"Failed to recover job {job.id}: {e}")
                # Don't mark as failed - let it be retried on next worker restart

        return {"recovered": recovered_count, "total_stuck": len(stuck_jobs)}


# === LEGAL RESEARCH TASKS ===

@celery_app.task(bind=True)
def search_legal_authorities(self, job_id: int, matter_id: int, user_id: int):
    """
    Search for relevant case law after document processing completes.

    This task searches CourtListener for relevant legal authorities based on
    the witness observations and case claims extracted from documents.

    Args:
        job_id: ProcessingJob ID that triggered this search
        matter_id: Database ID of the matter
        user_id: User ID who owns the matter
    """
    return run_async(_search_legal_authorities_async(job_id, matter_id, user_id))


async def _search_legal_authorities_async(job_id: int, matter_id: int, user_id: int):
    """Async implementation of legal authority search."""
    async with get_worker_session() as session:
        try:
            # Get matter details for jurisdiction detection
            result = await session.execute(
                select(Matter).where(Matter.id == matter_id)
            )
            matter = result.scalar_one_or_none()

            if not matter:
                logger.error(f"Legal research: Matter {matter_id} not found")
                return {"success": False, "error": "Matter not found"}

            # Detect jurisdiction from case number
            legal_research_service = get_legal_research_service()
            jurisdiction = legal_research_service.detect_jurisdiction(matter.display_number or "")

            logger.info(f"Legal research for job {job_id}: detected jurisdiction {jurisdiction}")

            # Get relevant witnesses for context
            witness_result = await session.execute(
                select(Witness).where(
                    Witness.matter_id == matter_id,
                    Witness.relevance.in_([RelevanceLevel.HIGHLY_RELEVANT, RelevanceLevel.RELEVANT])
                ).limit(10)
            )
            witnesses = witness_result.scalars().all()

            # Get case claims for context
            claims_result = await session.execute(
                select(CaseClaim).where(CaseClaim.matter_id == matter_id).limit(10)
            )
            claims = claims_result.scalars().all()

            # Build search queries from case context
            claim_dicts = [{"claim_text": c.claim_text} for c in claims]
            witness_observations = [w.observation for w in witnesses if w.observation]

            queries = legal_research_service.build_search_queries(
                claims=claim_dicts,
                witness_observations=witness_observations,
                max_queries=5
            )

            if not queries:
                logger.info(f"Legal research: No queries generated for job {job_id}")
                return {"success": True, "message": "No search queries generated", "count": 0}

            logger.info(f"Legal research: Searching with {len(queries)} queries")

            # Search CourtListener for each query
            all_results = []
            for query in queries:
                try:
                    results = await legal_research_service.search_case_law(
                        query=query,
                        jurisdiction=jurisdiction,
                        max_results=5
                    )
                    all_results.extend(results)
                except Exception as e:
                    logger.warning(f"Legal research query failed: {query[:50]}... Error: {e}")
                    continue

            # Deduplicate by case ID
            seen_ids = set()
            unique_results = []
            for r in all_results:
                if r.id not in seen_ids:
                    seen_ids.add(r.id)
                    unique_results.append(r)

            # Convert to dict format for JSON storage
            results_json = [
                {
                    "id": r.id,
                    "case_name": r.case_name,
                    "citation": r.citation,
                    "court": r.court,
                    "date_filed": r.date_filed,
                    "snippet": r.snippet,
                    "absolute_url": r.absolute_url,
                    "pdf_url": r.pdf_url,
                    "relevance_score": r.relevance_score
                }
                for r in unique_results[:15]  # Top 15 results
            ]

            # Create legal research record
            research_result = LegalResearchResult(
                job_id=job_id,
                matter_id=matter_id,
                user_id=user_id,
                status=LegalResearchStatus.READY if results_json else LegalResearchStatus.COMPLETED,
                results=results_json,
            )
            session.add(research_result)
            await session.commit()

            logger.info(f"Legal research complete for job {job_id}: {len(results_json)} cases found")

            return {
                "success": True,
                "research_id": research_result.id,
                "count": len(results_json)
            }

        except Exception as e:
            logger.exception(f"Legal research failed for job {job_id}: {e}")
            return {"success": False, "error": str(e)}


@celery_app.task(bind=True)
def save_legal_research_to_clio(self, research_id: int):
    """
    Download selected cases and upload to Clio as PDFs.

    Args:
        research_id: LegalResearchResult ID with selected cases
    """
    return run_async(_save_legal_research_to_clio_async(research_id))


async def _save_legal_research_to_clio_async(research_id: int):
    """Async implementation of saving legal research to Clio."""
    async with get_worker_session() as session:
        try:
            # Get the research record
            result = await session.execute(
                select(LegalResearchResult).where(LegalResearchResult.id == research_id)
            )
            research = result.scalar_one_or_none()

            if not research:
                logger.error(f"Legal research {research_id} not found")
                return {"success": False, "error": "Research not found"}

            if not research.selected_ids:
                logger.warning(f"No cases selected for research {research_id}")
                research.status = LegalResearchStatus.COMPLETED
                await session.commit()
                return {"success": True, "message": "No cases selected"}

            # Get user's Clio integration
            result = await session.execute(
                select(ClioIntegration).where(ClioIntegration.user_id == research.user_id)
            )
            clio_integration = result.scalar_one_or_none()

            if not clio_integration:
                logger.error(f"No Clio integration for user {research.user_id}")
                return {"success": False, "error": "Clio integration not found"}

            # Get matter for Clio matter ID
            result = await session.execute(
                select(Matter).where(Matter.id == research.matter_id)
            )
            matter = result.scalar_one_or_none()

            if not matter:
                logger.error(f"Matter {research.matter_id} not found")
                return {"success": False, "error": "Matter not found"}

            # Initialize Clio client
            async with ClioClient(
                access_token=decrypt_token(clio_integration.access_token_encrypted),
                refresh_token=decrypt_token(clio_integration.refresh_token_encrypted),
                token_expires_at=clio_integration.token_expires_at,
                region=clio_integration.clio_region
            ) as clio:
                # Try to create "Legal Research" folder in matter
                # If folder creation fails (403), we'll upload to matter root
                folder_id = None
                folder_name = "Legal Research"
                try:
                    folder = await clio.create_folder(
                        matter_id=int(matter.clio_matter_id),
                        name=folder_name
                    )
                    if folder and folder.get("id"):
                        folder_id = folder["id"]
                        research.clio_folder_id = str(folder_id)
                        logger.info(f"Created Legal Research folder {folder_id} in Clio")
                except Exception as e:
                    # Folder creation failed - continue without folder
                    logger.warning(f"Could not create folder in Clio: {e}. Uploading to matter root.")

                # Download and upload each selected case
                legal_research_service = get_legal_research_service()
                uploaded_count = 0

                for case_id in research.selected_ids:
                    # Find case info in results
                    case_info = next(
                        (r for r in research.results if r.get("id") == case_id),
                        None
                    )
                    if not case_info:
                        continue

                    try:
                        # Try to download PDF
                        pdf_content = await legal_research_service.download_opinion_pdf(case_id)

                        if pdf_content:
                            # Generate filename with "Legal Research - " prefix if no folder
                            citation = case_info.get("citation") or case_info.get("case_name", "Unknown")
                            # Sanitize filename
                            filename = "".join(c for c in citation if c.isalnum() or c in " -_.,").strip()
                            if not folder_id:
                                filename = f"Legal Research - {filename[:80]}.pdf"
                            else:
                                filename = f"{filename[:100]}.pdf"

                            # Upload to Clio
                            await clio.upload_document(
                                matter_id=int(matter.clio_matter_id),
                                file_content=pdf_content,
                                filename=filename,
                                folder_id=folder_id
                            )
                            uploaded_count += 1
                            logger.info(f"Uploaded {filename} to Clio")
                        else:
                            logger.warning(f"No PDF available for case {case_id}")

                    except Exception as e:
                        logger.warning(f"Failed to upload case {case_id}: {e}")
                        continue

                research.status = LegalResearchStatus.COMPLETED
                await session.commit()

                logger.info(f"Legal research {research_id} complete: uploaded {uploaded_count} cases")

                return {
                    "success": True,
                    "uploaded": uploaded_count,
                    "folder_id": research.clio_folder_id
                }

        except Exception as e:
            logger.exception(f"Failed to save legal research {research_id} to Clio: {e}")
            return {"success": False, "error": str(e)}
