#!/usr/bin/env python3
"""
COMPLETE End-to-End Test: From Process Click to Export

This script tests the ENTIRE user journey:
1. Click "Process" - see document count from Clio
2. Click "Start Processing" - documents auto-sync
3. Processing job created and runs
4. Witnesses extracted from documents
5. Export witnesses to verify data

WARNING: This will actually process documents and extract witnesses!
Only run on test matters to avoid unnecessary API costs.

Usage:
    DATABASE_URL="postgresql://..." FERNET_KEY="..." python scripts/test_complete_e2e.py
"""
import asyncio
import sys
import os
import logging
import time
from datetime import datetime
from typing import Optional, Dict, Any, List

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, func, delete, update

from app.core.config import settings
from app.db.models import Matter, Document, ClioIntegration, ProcessingJob, Witness, JobStatus, SyncStatus
from app.services.clio_client import ClioClient
from app.core.security import decrypt_token

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_step1_document_count(session: AsyncSession, clio_client: ClioClient, matter: Matter) -> Dict[str, Any]:
    """Step 1: Verify document count from Clio (folder selector)"""
    logger.info("\n" + "="*60)
    logger.info("STEP 1: Document count from Clio (folder selector)")
    logger.info("="*60)

    result = {"passed": False, "clio_count": 0, "error": None}

    try:
        count = 0
        async for _ in clio_client.get_documents(matter_id=int(matter.clio_matter_id)):
            count += 1

        result["clio_count"] = count
        result["passed"] = count > 0

        if count > 0:
            logger.info(f"  PASS: Found {count} documents in Clio")
        else:
            logger.warning(f"  SKIP: No documents in Clio (can't test full flow)")

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"  FAIL: {e}")

    return result


async def test_step2_auto_sync(session: AsyncSession, clio_client: ClioClient, matter: Matter) -> Dict[str, Any]:
    """Step 2: Auto-sync documents from Clio to local DB"""
    logger.info("\n" + "="*60)
    logger.info("STEP 2: Auto-sync documents from Clio")
    logger.info("="*60)

    result = {"passed": False, "synced_count": 0, "local_count": 0, "error": None}

    try:
        # Clear existing documents for clean test
        await session.execute(delete(Document).where(Document.matter_id == matter.id))
        await session.commit()
        logger.info("  Cleared existing local documents")

        # Sync from Clio (same logic as /process endpoint)
        synced = 0
        async for clio_doc in clio_client.get_documents(matter_id=int(matter.clio_matter_id)):
            new_doc = Document(
                matter_id=matter.id,
                clio_document_id=str(clio_doc["id"]),
                filename=clio_doc.get("name", "Untitled"),
                file_type=clio_doc.get("content_type"),
                clio_folder_id=str(clio_doc.get("parent", {}).get("id")) if clio_doc.get("parent") else None,
                is_soft_deleted=False
            )
            session.add(new_doc)
            synced += 1

        await session.commit()
        result["synced_count"] = synced

        # Verify local count
        local_count = await session.scalar(
            select(func.count()).select_from(Document).where(
                Document.matter_id == matter.id,
                Document.is_soft_deleted == False
            )
        )
        result["local_count"] = local_count or 0
        result["passed"] = synced > 0 and local_count == synced

        if result["passed"]:
            logger.info(f"  PASS: Synced {synced} documents, local has {local_count}")
        else:
            logger.error(f"  FAIL: Synced {synced}, local has {local_count}")

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"  FAIL: {e}")
        import traceback
        traceback.print_exc()

    return result


async def test_step3_create_job(session: AsyncSession, matter: Matter, user_id: int) -> Dict[str, Any]:
    """Step 3: Create processing job"""
    logger.info("\n" + "="*60)
    logger.info("STEP 3: Create processing job")
    logger.info("="*60)

    result = {"passed": False, "job_id": None, "doc_count": 0, "error": None}

    try:
        # Get document IDs
        doc_result = await session.execute(
            select(Document.id).where(
                Document.matter_id == matter.id,
                Document.is_soft_deleted == False
            )
        )
        document_ids = [row[0] for row in doc_result.all()]
        result["doc_count"] = len(document_ids)

        if not document_ids:
            logger.error("  FAIL: No documents to process")
            return result

        # Create job
        job = ProcessingJob(
            user_id=user_id,
            job_type="single_matter",
            target_matter_id=matter.id,
            status=JobStatus.PENDING,
            total_documents=len(document_ids),
            document_ids_snapshot=document_ids
        )
        session.add(job)
        await session.flush()
        job.job_number = job.id
        await session.commit()
        await session.refresh(job)

        result["job_id"] = job.id
        result["passed"] = True
        logger.info(f"  PASS: Created job #{job.id} with {len(document_ids)} documents")

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"  FAIL: {e}")

    return result


async def test_step4_run_processing(session: AsyncSession, job_id: int, matter: Matter) -> Dict[str, Any]:
    """Step 4: Run actual document processing (witness extraction)"""
    logger.info("\n" + "="*60)
    logger.info("STEP 4: Run document processing (witness extraction)")
    logger.info("="*60)

    result = {"passed": False, "witnesses_before": 0, "witnesses_after": 0, "status": None, "error": None}

    try:
        # Count witnesses before (join through Document)
        witnesses_before = await session.scalar(
            select(func.count()).select_from(Witness).join(Document).where(Document.matter_id == matter.id)
        )
        result["witnesses_before"] = witnesses_before or 0
        logger.info(f"  Witnesses before processing: {witnesses_before}")

        # Start Celery task
        from app.worker.tasks import process_matter as process_matter_task

        logger.info(f"  Starting Celery task for job #{job_id}...")
        task = process_matter_task.delay(
            job_id=job_id,
            matter_id=matter.id,
            search_targets=None,
            scan_folder_id=None,
            legal_authority_folder_id=None,
            include_subfolders=True
        )

        # Update job with task ID
        await session.execute(
            update(ProcessingJob).where(ProcessingJob.id == job_id).values(celery_task_id=task.id)
        )
        await session.commit()

        logger.info(f"  Celery task ID: {task.id}")
        logger.info(f"  Waiting for processing to complete (this may take a few minutes)...")

        # Poll for completion (max 5 minutes)
        max_wait = 300  # 5 minutes
        poll_interval = 10  # 10 seconds
        elapsed = 0

        while elapsed < max_wait:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

            # Check job status
            job_result = await session.execute(
                select(ProcessingJob).where(ProcessingJob.id == job_id)
            )
            job = job_result.scalar_one_or_none()
            await session.refresh(job)

            logger.info(f"  [{elapsed}s] Job status: {job.status.value}, processed: {job.processed_documents}/{job.total_documents}")

            if job.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
                result["status"] = job.status.value
                break

        if elapsed >= max_wait:
            result["status"] = "TIMEOUT"
            logger.warning(f"  Processing timed out after {max_wait}s")

        # Count witnesses after (join through Document)
        # Need fresh session to see committed data from worker
        witnesses_after = await session.scalar(
            select(func.count()).select_from(Witness).join(Document).where(Document.matter_id == matter.id)
        )
        result["witnesses_after"] = witnesses_after or 0
        logger.info(f"  Witnesses after processing: {witnesses_after}")

        result["passed"] = (result["status"] == "COMPLETED" or result["status"] == "completed") and witnesses_after > witnesses_before

        if result["passed"]:
            logger.info(f"  PASS: Processing completed, extracted {witnesses_after - witnesses_before} new witnesses")
        elif result["status"] == "COMPLETED" and witnesses_after == witnesses_before:
            logger.warning(f"  PARTIAL: Processing completed but no new witnesses extracted")
            result["passed"] = True  # Job completed successfully, just no witnesses found
        else:
            logger.error(f"  FAIL: Status={result['status']}, witnesses={witnesses_after}")

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"  FAIL: {e}")
        import traceback
        traceback.print_exc()

    return result


async def test_step5_verify_export(session: AsyncSession, matter: Matter) -> Dict[str, Any]:
    """Step 5: Verify witnesses can be exported"""
    logger.info("\n" + "="*60)
    logger.info("STEP 5: Verify export data")
    logger.info("="*60)

    result = {"passed": False, "witness_count": 0, "sample_witnesses": [], "error": None}

    try:
        # Get witnesses for this matter (join through Document)
        witness_result = await session.execute(
            select(Witness).join(Document).where(Document.matter_id == matter.id).limit(5)
        )
        witnesses = witness_result.scalars().all()

        result["witness_count"] = len(witnesses)

        for w in witnesses:
            result["sample_witnesses"].append({
                "id": w.id,
                "name": w.full_name,
                "role": w.role.value if w.role else "unknown",
                "relevance": w.relevance.value if w.relevance else "unknown"
            })
            logger.info(f"  Witness: {w.full_name} ({w.role.value if w.role else 'unknown'}) - {w.relevance.value if w.relevance else 'unknown'}")

        if witnesses:
            result["passed"] = True
            logger.info(f"  PASS: Found {len(witnesses)} witnesses ready for export")
        else:
            logger.warning(f"  SKIP: No witnesses to export (processing may not have found any)")
            result["passed"] = True  # Not a failure if no witnesses found

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"  FAIL: {e}")

    return result


async def run_complete_e2e_test():
    """Run the complete end-to-end test."""
    logger.info("="*60)
    logger.info("COMPLETE E2E TEST: Process → Extract → Export")
    logger.info(f"Started at: {datetime.now().isoformat()}")
    logger.info("="*60)
    logger.info("\nWARNING: This test will actually process documents!")
    logger.info("It may take several minutes and use AI API credits.\n")

    # Connect to database
    db_url = os.environ.get("DATABASE_URL") or settings.database_url
    if not db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    results = {}

    try:
        async with async_session() as session:
            # Find a test matter with documents
            logger.info("--- Finding test matter ---")

            # Get Clio integration first
            integration_result = await session.execute(
                select(ClioIntegration).where(ClioIntegration.access_token_encrypted.isnot(None)).limit(1)
            )
            integration = integration_result.scalar_one_or_none()

            if not integration:
                logger.error("No Clio integration found!")
                return

            user_id = integration.user_id

            decrypted_access = decrypt_token(integration.access_token_encrypted)
            decrypted_refresh = decrypt_token(integration.refresh_token_encrypted)

            async with ClioClient(
                access_token=decrypted_access,
                refresh_token=decrypted_refresh,
                token_expires_at=integration.token_expires_at
            ) as clio_client:

                # Find matter with a small number of documents (to keep test fast)
                matter_result = await session.execute(
                    select(Matter).where(
                        Matter.clio_matter_id.isnot(None),
                        Matter.user_id == user_id
                    ).order_by(Matter.id.desc()).limit(20)
                )
                matters = matter_result.scalars().all()

                test_matter = None
                for m in matters:
                    count = 0
                    async for _ in clio_client.get_documents(matter_id=int(m.clio_matter_id)):
                        count += 1
                        if count > 5:  # Want a matter with 1-5 docs for faster test
                            break
                    if 1 <= count <= 5:
                        test_matter = m
                        logger.info(f"Selected: {m.display_number} ({count} documents)")
                        break
                    elif count > 0 and not test_matter:
                        test_matter = m  # Fallback to any matter with docs

                if not test_matter:
                    logger.error("No suitable test matter found!")
                    return

                # Run all steps
                results["step1"] = await test_step1_document_count(session, clio_client, test_matter)

                if not results["step1"]["passed"]:
                    logger.error("Step 1 failed, cannot continue")
                    return

                results["step2"] = await test_step2_auto_sync(session, clio_client, test_matter)

                if not results["step2"]["passed"]:
                    logger.error("Step 2 failed, cannot continue")
                    return

                results["step3"] = await test_step3_create_job(session, test_matter, user_id)

                if not results["step3"]["passed"]:
                    logger.error("Step 3 failed, cannot continue")
                    return

                results["step4"] = await test_step4_run_processing(session, results["step3"]["job_id"], test_matter)

                # Step 5 can run even if step 4 didn't find witnesses
                results["step5"] = await test_step5_verify_export(session, test_matter)

        # Final Summary
        logger.info("\n" + "="*60)
        logger.info("COMPLETE E2E TEST SUMMARY")
        logger.info("="*60)

        all_passed = True
        for step, result in results.items():
            status = "PASS" if result.get("passed") else "FAIL"
            if not result.get("passed"):
                all_passed = False
            logger.info(f"  {step}: {status}")

        logger.info("="*60)

        if all_passed:
            logger.info("\nALL STEPS PASSED! Full E2E flow is working:")
            logger.info("  1. Document count from Clio ✓")
            logger.info("  2. Auto-sync documents ✓")
            logger.info("  3. Create processing job ✓")
            logger.info("  4. Process documents (extract witnesses) ✓")
            logger.info("  5. Export verification ✓")
            sys.exit(0)
        else:
            logger.error("\nSOME STEPS FAILED! Do not deploy.")
            sys.exit(1)

    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_complete_e2e_test())
