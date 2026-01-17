"""Celery background tasks for document processing and witness extraction"""
import asyncio
import gc
from datetime import datetime
from typing import List, Optional, Dict, Any

from celery import shared_task
from celery.utils.log import get_task_logger
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.worker.celery_app import celery_app
from app.core.config import settings
from app.core.security import decrypt_token
from app.db.session import AsyncSessionLocal
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
    legal_context: Optional[str] = None
):
    """
    Process a single document for witness extraction.

    Args:
        document_id: Database ID of the document
        search_targets: Optional list of specific names to search for
        legal_context: Optional legal standards context from RAG
    """
    return run_async(_process_single_document_async(
        self, document_id, search_targets, legal_context
    ))


async def _process_single_document_async(
    task,
    document_id: int,
    search_targets: Optional[List[str]] = None,
    legal_context: Optional[str] = None
):
    """Async implementation of document processing"""
    async with AsyncSessionLocal() as session:
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
    async with AsyncSessionLocal() as session:
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

            logger.info(f"Syncing documents for matter {matter_id} from Clio...")
            if scan_folder_id:
                logger.info(f"Scanning specific folder: {scan_folder_id}, include_subfolders={include_subfolders}")
            if legal_authority_folder_id:
                logger.info(f"Excluding legal authority folder: {legal_authority_folder_id}")

            async with ClioClient(
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=clio_integration.token_expires_at,
                region=clio_integration.clio_region
            ) as clio:
                # Sync documents for this matter from Clio
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
                    # All documents in matter (original behavior)
                    doc_iterator = clio.get_documents(matter_id=int(matter.clio_matter_id))

                async for doc_data in doc_iterator:
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
                            file_type=doc_data.get("content_type", "").split("/")[-1] if doc_data.get("content_type") else None,
                            file_size=doc_data.get("size"),
                            etag=doc_data.get("etag")
                        )
                        session.add(doc)
                        docs_synced += 1

                await session.commit()
                logger.info(f"Synced {docs_synced} new documents for matter {matter_id}")

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

            # Get all documents for this matter (now including newly synced ones)
            result = await session.execute(
                select(Document).where(Document.matter_id == matter_id)
            )
            documents = result.scalars().all()

            job.total_documents = len(documents)
            await session.commit()

            total_witnesses = 0
            failed_count = 0

            for doc in documents:
                try:
                    # Process each document with legal context
                    doc_result = await _process_single_document_async(
                        task, doc.id, search_targets, legal_context
                    )

                    if doc_result.get("success"):
                        total_witnesses += doc_result.get("witnesses_found", 0)
                    else:
                        failed_count += 1

                    job.processed_documents += 1
                    await session.commit()

                except Exception as e:
                    logger.error(f"Failed to process document {doc.id}: {e}")
                    failed_count += 1
                    job.processed_documents += 1
                    await session.commit()

                # Force garbage collection after each document to prevent memory buildup
                gc.collect()

            # Update job completion
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            job.total_witnesses_found = total_witnesses
            job.failed_documents = failed_count
            job.result_summary = {
                "total_documents": len(documents),
                "processed": job.processed_documents,
                "failed": failed_count,
                "witnesses_found": total_witnesses
            }
            await session.commit()

            return {
                "success": True,
                "job_id": job_id,
                "documents_processed": job.processed_documents,
                "witnesses_found": total_witnesses,
                "failed": failed_count
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
    async with AsyncSessionLocal() as session:
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

            total_witnesses = 0
            failed_count = 0

            for doc in documents:
                try:
                    doc_result = await _process_single_document_async(
                        task, doc.id, search_targets
                    )

                    if doc_result.get("success"):
                        total_witnesses += doc_result.get("witnesses_found", 0)
                    else:
                        failed_count += 1

                    job.processed_documents += 1
                    await session.commit()

                except Exception as e:
                    logger.error(f"Failed to process document {doc.id}: {e}")
                    failed_count += 1
                    job.processed_documents += 1
                    await session.commit()

                # Force garbage collection after each document to prevent memory buildup
                gc.collect()

            # Update job completion
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            job.total_witnesses_found = total_witnesses
            job.failed_documents = failed_count
            job.result_summary = {
                "matters_synced": matters_synced,
                "total_documents": len(documents),
                "processed": job.processed_documents,
                "failed": failed_count,
                "witnesses_found": total_witnesses
            }
            await session.commit()

            return {
                "success": True,
                "job_id": job_id,
                "matters_synced": matters_synced,
                "documents_processed": job.processed_documents,
                "witnesses_found": total_witnesses
            }

        except Exception as e:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()
            await session.commit()

            logger.exception(f"Full database job {job_id} failed")
            return {"success": False, "error": str(e)}


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
