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
    ProcessingJob, JobStatus, WitnessRole, ImportanceLevel
)
from app.services.clio_client import ClioClient
from app.services.document_processor import DocumentProcessor
from app.services.bedrock_client import BedrockClient

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
    search_targets: Optional[List[str]] = None
):
    """
    Process a single document for witness extraction.

    Args:
        document_id: Database ID of the document
        search_targets: Optional list of specific names to search for
    """
    return run_async(_process_single_document_async(
        self, document_id, search_targets
    ))


async def _process_single_document_async(
    task,
    document_id: int,
    search_targets: Optional[List[str]] = None
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
                        search_targets=search_targets
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
                    search_targets=search_targets
                )

                if not extraction_result.success:
                    document.processing_error = extraction_result.error
                    await session.commit()
                    return {"success": False, "error": extraction_result.error}

            # Save witnesses to database
            witnesses_created = 0
            for w_data in extraction_result.witnesses:
                witness = Witness(
                    document_id=document.id,
                    full_name=w_data.full_name,
                    role=_map_role(w_data.role),
                    importance=_map_importance(w_data.importance),
                    observation=w_data.observation,
                    source_quote=w_data.source_quote,
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
            logger.exception(f"Error processing document {document_id}")
            document.processing_error = str(e)
            await session.commit()

            # Clean up memory even on error
            gc.collect()

            # Retry if retries remaining
            raise task.retry(exc=e, countdown=60)


@celery_app.task(bind=True)
def process_matter(
    self,
    job_id: int,
    matter_id: int,
    search_targets: Optional[List[str]] = None
):
    """
    Process all documents in a matter.

    Args:
        job_id: ProcessingJob ID for progress tracking
        matter_id: Database ID of the matter
        search_targets: Optional list of specific names to search for
    """
    return run_async(_process_matter_async(
        self, job_id, matter_id, search_targets
    ))


async def _process_matter_async(
    task,
    job_id: int,
    matter_id: int,
    search_targets: Optional[List[str]] = None
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

            async with ClioClient(
                access_token=access_token,
                refresh_token=refresh_token,
                token_expires_at=clio_integration.token_expires_at,
                region=clio_integration.clio_region
            ) as clio:
                # Sync documents for this matter from Clio
                docs_synced = 0
                async for doc_data in clio.get_documents(matter_id=int(matter.clio_matter_id)):
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
                    # Process each document
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
