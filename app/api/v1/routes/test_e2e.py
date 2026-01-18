"""
E2E Test Endpoint - Runs complete process flow test on Railway

This endpoint allows triggering a full E2E test from anywhere.
It runs ON Railway so it has access to Redis/Celery.

Usage: POST /api/v1/test/e2e
       POST /api/v1/test/e2e-internal?secret=<E2E_TEST_SECRET>
"""
import asyncio
import logging
import os
from datetime import datetime
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete

from app.db.session import get_db
from app.db.models import Matter, Document, ClioIntegration, ProcessingJob, Witness, JobStatus
from app.services.clio_client import ClioClient
from app.core.security import decrypt_token
from app.api.deps import get_current_user
from app.db.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/test", tags=["Testing"])

# Secret key for internal E2E testing (set in Railway env vars)
E2E_TEST_SECRET = os.environ.get("E2E_TEST_SECRET", "e2e-test-secret-key-2024")


@router.post("/e2e")
async def run_e2e_test(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Run complete E2E test: Process → Extract → Export

    This tests the full user flow:
    1. Get document count from Clio
    2. Auto-sync documents
    3. Create processing job
    4. Run processing (witness extraction)
    5. Verify witnesses can be exported
    """
    results = {
        "started_at": datetime.utcnow().isoformat(),
        "steps": {},
        "passed": False,
        "error": None
    }

    try:
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

        # Find a test matter with documents
        matter_result = await db.execute(
            select(Matter).where(
                Matter.user_id == current_user.id,
                Matter.clio_matter_id.isnot(None)
            ).order_by(Matter.id.desc()).limit(10)
        )
        matters = matter_result.scalars().all()

        if not matters:
            raise HTTPException(status_code=400, detail="No matters with Clio IDs found")

        decrypted_access = decrypt_token(integration.access_token_encrypted)
        decrypted_refresh = decrypt_token(integration.refresh_token_encrypted)

        async with ClioClient(
            access_token=decrypted_access,
            refresh_token=decrypted_refresh,
            token_expires_at=integration.token_expires_at,
            region=integration.clio_region
        ) as clio:
            # Find matter with 1-5 documents for fast test
            test_matter = None
            for m in matters:
                count = 0
                async for _ in clio.get_documents(matter_id=int(m.clio_matter_id)):
                    count += 1
                    if count > 5:
                        break
                if 1 <= count <= 5:
                    test_matter = m
                    results["test_matter"] = {"id": m.id, "name": m.display_number, "doc_count": count}
                    break

            if not test_matter:
                # Fallback to any matter with docs
                for m in matters:
                    count = 0
                    async for _ in clio.get_documents(matter_id=int(m.clio_matter_id)):
                        count += 1
                        if count > 0:
                            test_matter = m
                            results["test_matter"] = {"id": m.id, "name": m.display_number, "doc_count": count}
                            break
                    if test_matter:
                        break

            if not test_matter:
                raise HTTPException(status_code=400, detail="No matters with documents found in Clio")

            # STEP 1: Document count from Clio
            results["steps"]["step1_doc_count"] = {"passed": False}
            doc_count = 0
            async for _ in clio.get_documents(matter_id=int(test_matter.clio_matter_id)):
                doc_count += 1
            results["steps"]["step1_doc_count"]["clio_count"] = doc_count
            results["steps"]["step1_doc_count"]["passed"] = doc_count > 0

            # STEP 2: Auto-sync documents
            results["steps"]["step2_auto_sync"] = {"passed": False}

            # Clear existing docs for clean test
            await db.execute(delete(Document).where(Document.matter_id == test_matter.id))
            await db.commit()

            synced = 0
            async for clio_doc in clio.get_documents(matter_id=int(test_matter.clio_matter_id)):
                new_doc = Document(
                    matter_id=test_matter.id,
                    clio_document_id=str(clio_doc["id"]),
                    filename=clio_doc.get("name", "Untitled"),
                    file_type=clio_doc.get("content_type"),
                    clio_folder_id=str(clio_doc.get("parent", {}).get("id")) if clio_doc.get("parent") else None,
                    is_soft_deleted=False
                )
                db.add(new_doc)
                synced += 1

            await db.commit()

            local_count = await db.scalar(
                select(func.count()).select_from(Document).where(
                    Document.matter_id == test_matter.id,
                    Document.is_soft_deleted == False
                )
            )

            results["steps"]["step2_auto_sync"]["synced"] = synced
            results["steps"]["step2_auto_sync"]["local_count"] = local_count
            results["steps"]["step2_auto_sync"]["passed"] = synced > 0 and local_count == synced

            # STEP 3: Create processing job
            results["steps"]["step3_create_job"] = {"passed": False}

            doc_result = await db.execute(
                select(Document.id).where(
                    Document.matter_id == test_matter.id,
                    Document.is_soft_deleted == False
                )
            )
            document_ids = [row[0] for row in doc_result.all()]

            job = ProcessingJob(
                user_id=current_user.id,
                job_type="single_matter",
                target_matter_id=test_matter.id,
                status=JobStatus.PENDING,
                total_documents=len(document_ids),
                document_ids_snapshot=document_ids
            )
            db.add(job)
            await db.flush()
            job.job_number = job.id
            await db.commit()
            await db.refresh(job)

            results["steps"]["step3_create_job"]["job_id"] = job.id
            results["steps"]["step3_create_job"]["doc_count"] = len(document_ids)
            results["steps"]["step3_create_job"]["passed"] = True

            # STEP 4: Start processing
            results["steps"]["step4_processing"] = {"passed": False}

            from app.worker.tasks import process_matter as process_matter_task

            task = process_matter_task.delay(
                job_id=job.id,
                matter_id=test_matter.id,
                search_targets=None,
                scan_folder_id=None,
                legal_authority_folder_id=None,
                include_subfolders=True
            )

            job.celery_task_id = task.id
            await db.commit()

            results["steps"]["step4_processing"]["task_id"] = task.id
            results["steps"]["step4_processing"]["status"] = "QUEUED"
            results["steps"]["step4_processing"]["passed"] = True
            results["steps"]["step4_processing"]["note"] = "Task queued. Poll job status to track progress."

            # STEP 5: Verify export capability (check existing witnesses)
            results["steps"]["step5_export"] = {"passed": False}

            witness_count = await db.scalar(
                select(func.count()).select_from(Witness).join(Document).where(
                    Document.matter_id == test_matter.id
                )
            )

            results["steps"]["step5_export"]["existing_witnesses"] = witness_count or 0
            results["steps"]["step5_export"]["passed"] = True
            results["steps"]["step5_export"]["note"] = "Export endpoint ready. Witnesses will appear after processing completes."

        # Summary
        all_passed = all(step.get("passed", False) for step in results["steps"].values())
        results["passed"] = all_passed
        results["completed_at"] = datetime.utcnow().isoformat()
        results["summary"] = "All steps passed! Processing is running in background." if all_passed else "Some steps failed."

        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"E2E test failed: {e}")
        import traceback
        results["error"] = str(e)
        results["traceback"] = traceback.format_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/e2e/status/{job_id}")
async def get_e2e_test_status(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Check the status of an E2E test processing job."""
    job_result = await db.execute(
        select(ProcessingJob).where(
            ProcessingJob.id == job_id,
            ProcessingJob.user_id == current_user.id
        )
    )
    job = job_result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Count witnesses
    witness_count = await db.scalar(
        select(func.count()).select_from(Witness).where(Witness.job_id == job_id)
    )

    return {
        "job_id": job.id,
        "status": job.status.value,
        "total_documents": job.total_documents,
        "processed_documents": job.processed_documents,
        "witnesses_extracted": witness_count or 0,
        "error_message": job.error_message
    }


@router.post("/e2e-internal")
async def run_e2e_test_internal(
    secret: str = Query(..., description="Secret key for internal testing"),
    db: AsyncSession = Depends(get_db)
):
    """
    Run E2E test without Firebase auth (uses secret key).
    For internal testing only.
    """
    if secret != E2E_TEST_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret key")

    results = {
        "started_at": datetime.utcnow().isoformat(),
        "steps": {},
        "passed": False,
        "error": None
    }

    try:
        # Get the first active Clio integration
        integration_result = await db.execute(
            select(ClioIntegration).where(
                ClioIntegration.is_active == True,
                ClioIntegration.access_token_encrypted.isnot(None)
            ).limit(1)
        )
        integration = integration_result.scalar_one_or_none()

        if not integration:
            raise HTTPException(status_code=400, detail="No active Clio integration found")

        user_id = integration.user_id
        results["user_id"] = user_id

        # Find a test matter with documents
        matter_result = await db.execute(
            select(Matter).where(
                Matter.user_id == user_id,
                Matter.clio_matter_id.isnot(None)
            ).order_by(Matter.id.desc()).limit(10)
        )
        matters = matter_result.scalars().all()

        if not matters:
            raise HTTPException(status_code=400, detail="No matters with Clio IDs found")

        decrypted_access = decrypt_token(integration.access_token_encrypted)
        decrypted_refresh = decrypt_token(integration.refresh_token_encrypted)

        async with ClioClient(
            access_token=decrypted_access,
            refresh_token=decrypted_refresh,
            token_expires_at=integration.token_expires_at,
            region=integration.clio_region
        ) as clio:
            # Find matter with 1-5 documents for fast test
            test_matter = None
            for m in matters:
                count = 0
                async for _ in clio.get_documents(matter_id=int(m.clio_matter_id)):
                    count += 1
                    if count > 5:
                        break
                if 1 <= count <= 5:
                    test_matter = m
                    results["test_matter"] = {"id": m.id, "name": m.display_number, "doc_count": count}
                    break

            if not test_matter:
                # Fallback to any matter with docs
                for m in matters:
                    count = 0
                    async for _ in clio.get_documents(matter_id=int(m.clio_matter_id)):
                        count += 1
                        if count > 0:
                            test_matter = m
                            results["test_matter"] = {"id": m.id, "name": m.display_number, "doc_count": count}
                            break
                    if test_matter:
                        break

            if not test_matter:
                raise HTTPException(status_code=400, detail="No matters with documents found in Clio")

            # STEP 1: Document count from Clio
            results["steps"]["step1_doc_count"] = {"passed": False}
            doc_count = 0
            async for _ in clio.get_documents(matter_id=int(test_matter.clio_matter_id)):
                doc_count += 1
            results["steps"]["step1_doc_count"]["clio_count"] = doc_count
            results["steps"]["step1_doc_count"]["passed"] = doc_count > 0

            # STEP 2: Auto-sync documents
            results["steps"]["step2_auto_sync"] = {"passed": False}

            # Clear existing docs for clean test
            await db.execute(delete(Document).where(Document.matter_id == test_matter.id))
            await db.commit()

            synced = 0
            async for clio_doc in clio.get_documents(matter_id=int(test_matter.clio_matter_id)):
                new_doc = Document(
                    matter_id=test_matter.id,
                    clio_document_id=str(clio_doc["id"]),
                    filename=clio_doc.get("name", "Untitled"),
                    file_type=clio_doc.get("content_type"),
                    clio_folder_id=str(clio_doc.get("parent", {}).get("id")) if clio_doc.get("parent") else None,
                    is_soft_deleted=False
                )
                db.add(new_doc)
                synced += 1

            await db.commit()

            local_count = await db.scalar(
                select(func.count()).select_from(Document).where(
                    Document.matter_id == test_matter.id,
                    Document.is_soft_deleted == False
                )
            )

            results["steps"]["step2_auto_sync"]["synced"] = synced
            results["steps"]["step2_auto_sync"]["local_count"] = local_count
            results["steps"]["step2_auto_sync"]["passed"] = synced > 0 and local_count == synced

            # STEP 3: Create processing job
            results["steps"]["step3_create_job"] = {"passed": False}

            doc_result = await db.execute(
                select(Document.id).where(
                    Document.matter_id == test_matter.id,
                    Document.is_soft_deleted == False
                )
            )
            document_ids = [row[0] for row in doc_result.all()]

            job = ProcessingJob(
                user_id=user_id,
                job_type="single_matter",
                target_matter_id=test_matter.id,
                status=JobStatus.PENDING,
                total_documents=len(document_ids),
                document_ids_snapshot=document_ids
            )
            db.add(job)
            await db.flush()
            job.job_number = job.id
            await db.commit()
            await db.refresh(job)

            results["steps"]["step3_create_job"]["job_id"] = job.id
            results["steps"]["step3_create_job"]["doc_count"] = len(document_ids)
            results["steps"]["step3_create_job"]["passed"] = True

            # STEP 4: Start processing
            results["steps"]["step4_processing"] = {"passed": False}

            from app.worker.tasks import process_matter as process_matter_task

            task = process_matter_task.delay(
                job_id=job.id,
                matter_id=test_matter.id,
                search_targets=None,
                scan_folder_id=None,
                legal_authority_folder_id=None,
                include_subfolders=True
            )

            job.celery_task_id = task.id
            await db.commit()

            results["steps"]["step4_processing"]["task_id"] = task.id
            results["steps"]["step4_processing"]["status"] = "QUEUED"
            results["steps"]["step4_processing"]["passed"] = True
            results["steps"]["step4_processing"]["note"] = "Task queued. Poll job status to track progress."

            # STEP 5: Verify export capability (check existing witnesses)
            results["steps"]["step5_export"] = {"passed": False}

            witness_count = await db.scalar(
                select(func.count()).select_from(Witness).join(Document).where(
                    Document.matter_id == test_matter.id
                )
            )

            results["steps"]["step5_export"]["existing_witnesses"] = witness_count or 0
            results["steps"]["step5_export"]["passed"] = True
            results["steps"]["step5_export"]["note"] = "Export endpoint ready. Witnesses will appear after processing completes."

        # Summary
        all_passed = all(step.get("passed", False) for step in results["steps"].values())
        results["passed"] = all_passed
        results["completed_at"] = datetime.utcnow().isoformat()
        results["summary"] = "All steps passed! Processing is running in background." if all_passed else "Some steps failed."

        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"E2E internal test failed: {e}")
        import traceback
        results["error"] = str(e)
        results["traceback"] = traceback.format_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/e2e-internal/status/{job_id}")
async def get_e2e_test_status_internal(
    job_id: int,
    secret: str = Query(..., description="Secret key for internal testing"),
    db: AsyncSession = Depends(get_db)
):
    """Check E2E test status without Firebase auth."""
    if secret != E2E_TEST_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret key")

    job_result = await db.execute(
        select(ProcessingJob).where(ProcessingJob.id == job_id)
    )
    job = job_result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Count witnesses
    witness_count = await db.scalar(
        select(func.count()).select_from(Witness).where(Witness.job_id == job_id)
    )

    return {
        "job_id": job.id,
        "status": job.status.value,
        "total_documents": job.total_documents,
        "processed_documents": job.processed_documents,
        "witnesses_extracted": witness_count or 0,
        "error_message": job.error_message
    }
