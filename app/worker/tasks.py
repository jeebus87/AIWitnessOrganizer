"""Celery background tasks for document processing and witness extraction"""
import asyncio
import gc
from datetime import datetime
from typing import List, Optional, Dict, Any

from celery import shared_task, group, chord
from celery.utils.log import get_task_logger
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.worker.celery_app import celery_app
from app.worker.db import get_worker_session
from app.core.config import settings
from app.core.security import decrypt_token
from app.db.models import (
    User, ClioIntegration, Matter, Document, Witness,
    ProcessingJob, JobStatus, WitnessRole, ImportanceLevel, RelevanceLevel
)
from app.services.clio_client import ClioClient
from app.services.document_processor import DocumentProcessor
from app.services.bedrock_client import BedrockClient
from app.services.legal_authority_service import LegalAuthorityService

logger = get_task_logger(__name__)


def run_async(coro):
    """Run async function in sync context"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


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

            # === DEBUG MODE: Skip Bedrock processing ===
            DEBUG_MODE = False  # Set to True to skip AI processing for debugging

            logger.info(f"")
            logger.info(f"{'='*60}")
            logger.info(f"=== PROCESSING DOCUMENT - DEBUG MODE ===")
            logger.info(f"{'='*60}")
            logger.info(f"  Document ID (db): {document_id}")
            logger.info(f"  Clio Document ID: {document.clio_document_id}")
            logger.info(f"  Filename: {document.filename}")
            logger.info(f"  File type: {document.file_type}")
            logger.info(f"  File size (from Clio): {document.file_size}")
            logger.info(f"  Downloaded content size: {len(content)} bytes")
            logger.info(f"  Matter ID: {document.matter_id}")
            logger.info(f"  Job ID: {job_id}")
            logger.info(f"  DEBUG_MODE: {DEBUG_MODE}")
            logger.info(f"{'='*60}")

            if DEBUG_MODE:
                logger.info(f"DEBUG: Skipping Bedrock processing - just marking document as processed")

                # Update job progress
                if job_id:
                    from sqlalchemy import text
                    await session.execute(
                        text("UPDATE processing_jobs SET processed_documents = processed_documents + 1 WHERE id = :job_id"),
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

            # Process document
            processor = DocumentProcessor()
            bedrock = BedrockClient()

            # Calculate file hash upfront for caching (needed for both paths)
            file_hash = processor.get_file_hash(content)

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

            # Save witnesses to database
            witnesses_created = 0
            for w_data in verified_witnesses:
                witness = Witness(
                    document_id=document.id,
                    full_name=w_data.full_name,
                    role=_map_role(w_data.role),
                    importance=_map_importance(w_data.importance),
                    observation=w_data.observation,
                    source_quote=w_data.source_summary,  # source_summary stored in source_quote column
                    source_page=w_data.source_page,
                    context=w_data.context,
                    email=w_data.email,
                    phone=w_data.phone,
                    address=w_data.address,
                    confidence_score=w_data.confidence_score
                )
                session.add(witness)
                witnesses_created += 1

            # Update document status
            document.is_processed = True
            document.processed_at = datetime.utcnow()
            tokens_used = extraction_result.input_tokens + extraction_result.output_tokens
            document.analysis_cache = {
                "witnesses_count": witnesses_created,
                "input_tokens": extraction_result.input_tokens,
                "output_tokens": extraction_result.output_tokens
            }
            document.analysis_cache_key = file_hash

            await session.commit()

            logger.info(f"Document {document_id} processed: {witnesses_created} witnesses found")

            # Update job progress if job_id provided (for parallel processing)
            if job_id:
                from sqlalchemy import text
                await session.execute(
                    text("UPDATE processing_jobs SET processed_documents = processed_documents + 1 WHERE id = :job_id"),
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

            # Update job progress even on failure (for parallel processing)
            if job_id:
                from sqlalchemy import text
                await session.execute(
                    text("UPDATE processing_jobs SET processed_documents = processed_documents + 1 WHERE id = :job_id"),
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

            # Decrypt tokens and sync documents from Clio
            access_token = decrypt_token(clio_integration.access_token_encrypted)
            refresh_token = decrypt_token(clio_integration.refresh_token_encrypted)

            logger.info(f"")
            logger.info(f"{'='*60}")
            logger.info(f"=== PROCESSING MATTER - DEBUG MODE ===")
            logger.info(f"{'='*60}")
            logger.info(f"  Database matter_id: {matter_id}")
            logger.info(f"  Clio matter_id: {matter.clio_matter_id}")
            logger.info(f"  Matter description: {matter.description}")
            logger.info(f"  Matter display_number: {matter.display_number}")
            logger.info(f"  Job ID: {job_id}")
            logger.info(f"  scan_folder_id: {scan_folder_id} (type: {type(scan_folder_id).__name__})")
            logger.info(f"  legal_authority_folder_id: {legal_authority_folder_id}")
            logger.info(f"  include_subfolders: {include_subfolders}")
            logger.info(f"{'='*60}")

            # Determine scanning mode
            if scan_folder_id:
                if include_subfolders:
                    logger.info(f"SCAN MODE: Recursive folder scan (folder {scan_folder_id} + subfolders)")
                else:
                    logger.info(f"SCAN MODE: Single folder only (folder {scan_folder_id}, NO subfolders)")
            else:
                logger.info(f"SCAN MODE: ALL documents in matter via folder traversal")

            if legal_authority_folder_id:
                logger.info(f"EXCLUSION: Will exclude folder {legal_authority_folder_id} from scanning")

            async with ClioClient(
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=clio_integration.token_expires_at,
                region=clio_integration.clio_region
            ) as clio:
                # Track document IDs to process (only documents from selected folder/scope)
                document_ids_to_process = []
                docs_synced = 0

                # Determine which documents to sync based on folder selection
                if scan_folder_id and include_subfolders:
                    # Recursive folder scanning with optional exclusion
                    exclude_ids = [legal_authority_folder_id] if legal_authority_folder_id else []
                    doc_iterator = clio.get_documents_recursive(
                        matter_id=int(matter.clio_matter_id),
                        folder_id=scan_folder_id,
                        exclude_folder_ids=exclude_ids
                    )
                elif scan_folder_id:
                    # Single folder only (no subfolders)
                    doc_iterator = clio.get_documents_in_folder(scan_folder_id)
                else:
                    # All documents in matter via folder traversal
                    # This avoids the Clio API offset pagination limit (~10,000)
                    logger.info(f"Using folder-based traversal to get all documents for matter {matter.clio_matter_id}")
                    exclude_ids = [legal_authority_folder_id] if legal_authority_folder_id else []
                    doc_iterator = clio.get_all_matter_documents_via_folders(
                        matter_id=int(matter.clio_matter_id),
                        exclude_folder_ids=exclude_ids
                    )

                logger.info(f"")
                logger.info(f"--- Starting document iteration from Clio ---")
                doc_count = 0
                async for doc_data in doc_iterator:
                    doc_count += 1
                    clio_doc_id = str(doc_data["id"])
                    doc_name = doc_data.get("name", "unknown")
                    doc_folder = doc_data.get("parent", {}).get("id") if doc_data.get("parent") else "root"

                    # Log every document found (first 50, then every 100th)
                    if doc_count <= 50 or doc_count % 100 == 0:
                        logger.info(f"  [{doc_count}] Found: {doc_name} (clio_id={clio_doc_id}, folder={doc_folder})")

                    result = await session.execute(
                        select(Document).where(
                            Document.matter_id == matter.id,
                            Document.clio_document_id == clio_doc_id
                        )
                    )
                    doc = result.scalar_one_or_none()

                    if not doc:
                        doc = Document(
                            matter_id=matter.id,
                            clio_document_id=clio_doc_id,
                            filename=doc_name,
                            file_type=doc_data.get("content_type", "").split("/")[-1] if doc_data.get("content_type") else None,
                            file_size=doc_data.get("size"),
                            etag=doc_data.get("etag")
                        )
                        session.add(doc)
                        await session.flush()  # Get the doc.id
                        docs_synced += 1
                        if doc_count <= 50:
                            logger.info(f"      -> NEW document, assigned db_id={doc.id}")
                    else:
                        if doc_count <= 50:
                            logger.info(f"      -> EXISTS in db, db_id={doc.id}")

                    # Track this document ID for processing (whether new or existing)
                    document_ids_to_process.append(doc.id)

                await session.commit()
                logger.info(f"")
                logger.info(f"--- Document iteration complete ---")
                logger.info(f"  Total documents from Clio iterator: {doc_count}")
                logger.info(f"  New documents synced to DB: {docs_synced}")
                logger.info(f"  Document IDs to process: {len(document_ids_to_process)}")
                if len(document_ids_to_process) <= 20:
                    logger.info(f"  Document IDs list: {document_ids_to_process}")
                else:
                    logger.info(f"  First 10 IDs: {document_ids_to_process[:10]}")
                    logger.info(f"  Last 10 IDs: {document_ids_to_process[-10:]}")

                # Process Legal Authority folder if specified
                legal_context = ""
                if legal_authority_folder_id:
                    logger.info(f"Processing Legal Authority folder: {legal_authority_folder_id}")
                    legal_auth_service = LegalAuthorityService()
                    doc_processor = DocumentProcessor()

                    # Get documents from the legal authority folder
                    async for la_doc in clio.get_documents_in_folder(legal_authority_folder_id):
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

                    # Get legal context for witness extraction
                    legal_context = await legal_auth_service.get_legal_context_for_witness_extraction(
                        db=session,
                        matter_id=matter_id,
                        document_summary="Analyze witness relevance based on legal claims and defenses in this matter."
                    )
                    if legal_context:
                        logger.info(f"Retrieved legal context: {len(legal_context)} chars")

            # Get only the documents that were found in the selected folder/scope
            # This ensures we only process what the user selected, not all documents in the matter
            if document_ids_to_process:
                result = await session.execute(
                    select(Document).where(Document.id.in_(document_ids_to_process))
                )
                documents = result.scalars().all()
            else:
                documents = []

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
