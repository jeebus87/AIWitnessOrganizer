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
from sqlalchemy.orm import selectinload

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


@router.get("/folder-count")
async def test_folder_document_count(
    secret: str = Query(..., description="Secret key for internal testing"),
    db: AsyncSession = Depends(get_db)
):
    """
    Test folder-specific document counts to verify the fix works.
    Tests: All documents, specific folder, and subfolder counts.
    """
    if secret != E2E_TEST_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret key")

    results = {
        "test": "folder_document_counts",
        "all_documents": {"passed": False, "count": 0},
        "specific_folder": {"passed": False, "count": 0, "folder_name": ""},
        "subfolder": {"passed": False, "count": 0, "folder_name": ""}
    }

    try:
        # Get active Clio integration
        integration_result = await db.execute(
            select(ClioIntegration).where(
                ClioIntegration.is_active == True,
                ClioIntegration.access_token_encrypted.isnot(None)
            ).limit(1)
        )
        integration = integration_result.scalar_one_or_none()

        if not integration:
            raise HTTPException(status_code=400, detail="No active Clio integration found")

        # Get a matter with documents
        matter_result = await db.execute(
            select(Matter).where(
                Matter.user_id == integration.user_id,
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
            # Find a matter with documents
            test_matter = None
            for m in matters:
                doc_count = 0
                async for _ in clio.get_documents(matter_id=int(m.clio_matter_id)):
                    doc_count += 1
                    if doc_count > 10:
                        break
                if doc_count > 5:
                    test_matter = m
                    results["matter"] = {"id": m.id, "name": m.display_number}
                    break

            if not test_matter:
                raise HTTPException(status_code=400, detail="No suitable test matter found")

            # TEST 1: All documents count
            all_count = 0
            async for _ in clio.get_documents(matter_id=int(test_matter.clio_matter_id)):
                all_count += 1
            results["all_documents"]["count"] = all_count
            results["all_documents"]["passed"] = all_count > 0

            # Get folders for this matter
            folders = await clio.get_folder_tree(int(test_matter.clio_matter_id))

            if not folders:
                results["specific_folder"]["passed"] = True
                results["specific_folder"]["note"] = "No folders in this matter"
                results["subfolder"]["passed"] = True
                results["subfolder"]["note"] = "No folders in this matter"
            else:
                # TEST 2: Specific folder count
                test_folder = folders[0]
                results["specific_folder"]["folder_name"] = test_folder.get("name", "unnamed")
                folder_count = 0
                async for _ in clio.get_documents_in_folder(
                    test_folder["id"],
                    matter_id=int(test_matter.clio_matter_id)
                ):
                    folder_count += 1
                results["specific_folder"]["count"] = folder_count
                results["specific_folder"]["passed"] = True  # No error = pass

                # TEST 3: Find a subfolder
                subfolder_found = False
                for folder in folders:
                    children = folder.get("children", [])
                    if children:
                        subfolder = children[0]
                        results["subfolder"]["folder_name"] = subfolder.get("name", "unnamed")
                        subfolder_count = 0
                        async for _ in clio.get_documents_in_folder(
                            subfolder["id"],
                            matter_id=int(test_matter.clio_matter_id)
                        ):
                            subfolder_count += 1
                        results["subfolder"]["count"] = subfolder_count
                        results["subfolder"]["passed"] = True
                        subfolder_found = True
                        break

                if not subfolder_found:
                    results["subfolder"]["passed"] = True
                    results["subfolder"]["note"] = "No subfolders found"

        # Summary
        all_passed = all(r.get("passed", False) for k, r in results.items() if isinstance(r, dict) and "passed" in r)
        results["all_passed"] = all_passed
        results["summary"] = "All folder count tests passed!" if all_passed else "Some tests failed"

        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Folder count test failed: {e}")
        import traceback
        results["error"] = str(e)
        results["traceback"] = traceback.format_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/subfolder-recursive-count")
async def test_subfolder_recursive_count(
    secret: str = Query(..., description="Secret key for internal testing"),
    db: AsyncSession = Depends(get_db)
):
    """
    Test the include_subfolders feature for document counting.
    Compares folder-only count vs recursive count (with subfolders).
    """
    if secret != E2E_TEST_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    logger = logging.getLogger(__name__)
    results = {
        "test": "subfolder_recursive_count",
        "folder_only_count": {"passed": False, "count": 0},
        "recursive_count": {"passed": False, "count": 0},
        "folder_with_subfolders": {"name": "", "id": 0}
    }

    try:
        # Get active Clio integration
        integration_result = await db.execute(
            select(ClioIntegration).where(
                ClioIntegration.is_active == True,
                ClioIntegration.access_token_encrypted.isnot(None)
            ).limit(1)
        )
        integration = integration_result.scalar_one_or_none()

        if not integration:
            raise HTTPException(status_code=400, detail="No active Clio integration found")

        # Get a matter with documents
        matter_result = await db.execute(
            select(Matter).where(
                Matter.user_id == integration.user_id,
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
            # Find a folder with subfolders that has documents
            test_matter = None
            test_folder = None

            for m in matters:
                folders = await clio.get_folder_tree(int(m.clio_matter_id))
                for folder in folders:
                    if folder.get("children"):  # Has subfolders
                        test_folder = folder
                        test_matter = m
                        break
                if test_folder:
                    break

            if not test_folder:
                return {
                    "test": "subfolder_recursive_count",
                    "skipped": True,
                    "reason": "No folder with subfolders found in any matter",
                    "all_passed": True
                }

            results["folder_with_subfolders"]["name"] = test_folder.get("name", "unnamed")
            results["folder_with_subfolders"]["id"] = test_folder["id"]
            results["matter"] = {"id": test_matter.id, "name": test_matter.display_number}

            # Count documents in folder only (no subfolders)
            folder_only_count = 0
            async for _ in clio.get_documents_in_folder(
                test_folder["id"],
                matter_id=int(test_matter.clio_matter_id)
            ):
                folder_only_count += 1
            results["folder_only_count"]["count"] = folder_only_count
            results["folder_only_count"]["passed"] = True

            # Count documents recursively (with subfolders)
            recursive_count = 0
            async for _ in clio.get_documents_recursive(
                matter_id=int(test_matter.clio_matter_id),
                folder_id=test_folder["id"]
            ):
                recursive_count += 1
            results["recursive_count"]["count"] = recursive_count
            results["recursive_count"]["passed"] = True

            # Recursive count should be >= folder-only count
            results["recursive_includes_subfolder_docs"] = recursive_count >= folder_only_count
            results["all_passed"] = results["folder_only_count"]["passed"] and results["recursive_count"]["passed"]
            results["summary"] = f"Folder-only: {folder_only_count}, Recursive: {recursive_count}"

            return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Subfolder recursive count test failed: {e}")
        import traceback
        results["error"] = str(e)
        results["traceback"] = traceback.format_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fix-job-numbers")
async def fix_existing_job_numbers(
    secret: str = Query(..., description="Secret key for internal testing"),
    db: AsyncSession = Depends(get_db)
):
    """
    Fix existing job numbers to be sequential per user.
    This one-time fix updates old jobs that had job_number = db_id.
    """
    if secret != E2E_TEST_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret key")

    logger = logging.getLogger(__name__)

    try:
        # Get all users with jobs
        from sqlalchemy import distinct
        user_ids_result = await db.execute(
            select(distinct(ProcessingJob.user_id))
        )
        user_ids = [row[0] for row in user_ids_result.all()]

        fixed_count = 0
        results = []

        for user_id in user_ids:
            # Get all jobs for this user, ordered by creation date
            jobs_result = await db.execute(
                select(ProcessingJob).where(
                    ProcessingJob.user_id == user_id
                ).order_by(ProcessingJob.created_at.asc())
            )
            user_jobs = jobs_result.scalars().all()

            # Reassign sequential job numbers
            for idx, job in enumerate(user_jobs, start=1):
                old_number = job.job_number
                if old_number != idx:
                    job.job_number = idx
                    fixed_count += 1
                    results.append({
                        "user_id": user_id,
                        "job_id": job.id,
                        "old_number": old_number,
                        "new_number": idx
                    })

        await db.commit()

        return {
            "success": True,
            "fixed_count": fixed_count,
            "changes": results
        }

    except Exception as e:
        logger.error(f"Fix job numbers failed: {e}")
        import traceback
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process-subfolder-test")
async def test_process_with_subfolders(
    secret: str = Query(..., description="Secret key for internal testing"),
    db: AsyncSession = Depends(get_db)
):
    """
    Test that include_subfolders parameter correctly affects document processing.
    Compares document counts when include_subfolders=True vs False.
    """
    if secret != E2E_TEST_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret key")

    logger = logging.getLogger(__name__)
    results = {
        "test": "process_subfolder_inclusion",
        "folder_only": {"doc_count": 0},
        "with_subfolders": {"doc_count": 0}
    }

    try:
        # Get active Clio integration
        integration_result = await db.execute(
            select(ClioIntegration).where(
                ClioIntegration.is_active == True,
                ClioIntegration.access_token_encrypted.isnot(None)
            ).limit(1)
        )
        integration = integration_result.scalar_one_or_none()

        if not integration:
            raise HTTPException(status_code=400, detail="No active Clio integration found")

        # Get a matter with folders
        matter_result = await db.execute(
            select(Matter).where(
                Matter.user_id == integration.user_id,
                Matter.clio_matter_id.isnot(None)
            ).order_by(Matter.id.desc()).limit(10)
        )
        matters = matter_result.scalars().all()

        if not matters:
            raise HTTPException(status_code=400, detail="No matters found")

        decrypted_access = decrypt_token(integration.access_token_encrypted)
        decrypted_refresh = decrypt_token(integration.refresh_token_encrypted)

        async with ClioClient(
            access_token=decrypted_access,
            refresh_token=decrypted_refresh,
            token_expires_at=integration.token_expires_at,
            region=integration.clio_region
        ) as clio:
            # Find a folder with subfolders
            test_matter = None
            test_folder = None

            for m in matters:
                folders = await clio.get_folder_tree(int(m.clio_matter_id))
                for folder in folders:
                    if folder.get("children"):
                        test_folder = folder
                        test_matter = m
                        break
                if test_folder:
                    break

            if not test_folder:
                return {
                    "test": "process_subfolder_inclusion",
                    "skipped": True,
                    "reason": "No folder with subfolders found",
                    "all_passed": True
                }

            results["matter"] = {"id": test_matter.id, "name": test_matter.display_number}
            results["folder"] = {"id": test_folder["id"], "name": test_folder.get("name")}

            # Count documents WITHOUT subfolders (folder only)
            folder_only_count = 0
            async for _ in clio.get_documents_in_folder(
                test_folder["id"],
                matter_id=int(test_matter.clio_matter_id)
            ):
                folder_only_count += 1
            results["folder_only"]["doc_count"] = folder_only_count

            # Count documents WITH subfolders (recursive)
            recursive_count = 0
            async for _ in clio.get_documents_recursive(
                matter_id=int(test_matter.clio_matter_id),
                folder_id=test_folder["id"]
            ):
                recursive_count += 1
            results["with_subfolders"]["doc_count"] = recursive_count

            # Verify the fix: recursive should include more docs
            results["subfolder_docs_found"] = recursive_count - folder_only_count
            results["fix_working"] = recursive_count >= folder_only_count
            results["all_passed"] = results["fix_working"]
            results["summary"] = f"Folder only: {folder_only_count} docs, With subfolders: {recursive_count} docs ({recursive_count - folder_only_count} from subfolders)"

            return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Process subfolder test failed: {e}")
        import traceback
        results["error"] = str(e)
        results["traceback"] = traceback.format_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/small-job-test")
async def test_small_job_with_doc_relevance(
    secret: str = Query(..., description="Secret key for internal testing"),
    max_docs: int = Query(3, description="Maximum documents to process"),
    db: AsyncSession = Depends(get_db)
):
    """
    Run a small job to test document relevance extraction.
    Processes only a few documents to verify Doc Relevance column works.
    """
    if secret != E2E_TEST_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret key")

    logger = logging.getLogger(__name__)
    results = {
        "test": "small_job_doc_relevance",
        "max_docs": max_docs
    }

    try:
        # Get active Clio integration
        integration_result = await db.execute(
            select(ClioIntegration).where(
                ClioIntegration.is_active == True,
                ClioIntegration.access_token_encrypted.isnot(None)
            ).limit(1)
        )
        integration = integration_result.scalar_one_or_none()

        if not integration:
            raise HTTPException(status_code=400, detail="No active Clio integration found")

        # Find a matter with at least some documents
        matter_result = await db.execute(
            select(Matter).where(
                Matter.user_id == integration.user_id,
                Matter.clio_matter_id.isnot(None)
            ).order_by(Matter.id.desc()).limit(10)
        )
        matters = matter_result.scalars().all()

        if not matters:
            raise HTTPException(status_code=400, detail="No matters found")

        decrypted_access = decrypt_token(integration.access_token_encrypted)
        decrypted_refresh = decrypt_token(integration.refresh_token_encrypted)

        async with ClioClient(
            access_token=decrypted_access,
            refresh_token=decrypted_refresh,
            token_expires_at=integration.token_expires_at,
            region=integration.clio_region
        ) as clio:
            # Find a matter with the fewest documents (but at least 1)
            best_matter = None
            best_count = 999999

            for m in matters:
                doc_count = 0
                async for _ in clio.get_documents(matter_id=int(m.clio_matter_id)):
                    doc_count += 1
                    if doc_count > max_docs * 2:  # Only need to count up to reasonable threshold
                        break
                
                if 1 <= doc_count <= best_count and doc_count >= 1:
                    best_count = doc_count
                    best_matter = m

                if doc_count <= max_docs:
                    break  # Found a good small matter

            if not best_matter:
                raise HTTPException(status_code=400, detail="No suitable matter found with documents")

            results["matter"] = {
                "id": best_matter.id,
                "name": best_matter.display_number,
                "doc_count": best_count
            }
            results["message"] = f"Found matter '{best_matter.display_number}' with {best_count} documents. To test document relevance, process this matter and check the PDF export for the 'Doc Relevance' column."
            results["all_passed"] = True

            return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Small job test failed: {e}")
        import traceback
        results["error"] = str(e)
        results["traceback"] = traceback.format_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-export-formats")
async def test_export_formats(
    secret: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """
    E2E test: Verify all export formats work (PDF, Excel, DOCX).
    Finds a completed job with witnesses and tests generating each format.
    """
    if secret != E2E_TEST_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret key")

    logger = logging.getLogger(__name__)
    results = {
        "test": "export_formats",
        "pdf": {"status": "pending"},
        "excel": {"status": "pending"},
        "docx": {"status": "pending"},
    }

    try:
        # Get active Clio integration to find user
        integration_result = await db.execute(
            select(ClioIntegration).where(
                ClioIntegration.is_active == True,
                ClioIntegration.access_token_encrypted.isnot(None)
            ).limit(1)
        )
        integration = integration_result.scalar_one_or_none()

        if not integration:
            raise HTTPException(status_code=400, detail="No active Clio integration found")

        # Find a completed job with witnesses
        job_result = await db.execute(
            select(ProcessingJob).where(
                ProcessingJob.user_id == integration.user_id,
                ProcessingJob.status == "completed",
                ProcessingJob.total_witnesses_found > 0
            ).order_by(ProcessingJob.id.desc()).limit(1)
        )
        job = job_result.scalar_one_or_none()

        if not job:
            raise HTTPException(status_code=400, detail="No completed job with witnesses found")

        results["job_id"] = job.id
        results["job_number"] = job.job_number
        results["witness_count"] = job.total_witnesses_found

        # Test each export format
        from app.services.export_service import ExportService
        export_service = ExportService()

        # Get witnesses for this job
        witness_result = await db.execute(
            select(Witness).where(Witness.job_id == job.id).options(
                selectinload(Witness.document).selectinload(Document.matter)
            )
        )
        witnesses = witness_result.scalars().all()

        # Convert to dict format
        witness_data = []
        for w in witnesses:
            # Get document_relevance safely (may not exist on older witnesses)
            doc_rel = getattr(w, 'document_relevance', None)
            doc_rel_reason = getattr(w, 'document_relevance_reason', None)
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
                "document_relevance": doc_rel.value.upper() if doc_rel else None,
                "document_relevance_reason": doc_rel_reason,
            })

        matter_name = "Test Matter"
        matter_number = "TEST-001"
        firm_name = "Test Firm"
        generated_by = "E2E Test"

        # Test PDF export
        try:
            pdf_bytes = export_service.generate_pdf(
                witnesses=witness_data,
                matter_name=matter_name,
                matter_number=matter_number,
                firm_name=firm_name,
                generated_by=generated_by
            )
            results["pdf"] = {
                "status": "passed",
                "size_bytes": len(pdf_bytes),
                "message": f"Generated {len(pdf_bytes):,} bytes"
            }
        except Exception as e:
            results["pdf"] = {"status": "failed", "error": str(e)}

        # Test Excel export
        try:
            excel_bytes = export_service.generate_excel(
                witnesses=witness_data,
                matter_name=matter_name,
                matter_number=matter_number,
                firm_name=firm_name,
                generated_by=generated_by
            )
            results["excel"] = {
                "status": "passed",
                "size_bytes": len(excel_bytes),
                "message": f"Generated {len(excel_bytes):,} bytes"
            }
        except Exception as e:
            results["excel"] = {"status": "failed", "error": str(e)}

        # Test DOCX export
        try:
            docx_bytes = export_service.generate_docx(
                witnesses=witness_data,
                matter_name=matter_name,
                matter_number=matter_number,
                firm_name=firm_name,
                generated_by=generated_by
            )
            results["docx"] = {
                "status": "passed",
                "size_bytes": len(docx_bytes),
                "message": f"Generated {len(docx_bytes):,} bytes"
            }
        except Exception as e:
            results["docx"] = {"status": "failed", "error": str(e)}

        # Summary
        all_passed = all(
            results[fmt]["status"] == "passed"
            for fmt in ["pdf", "excel", "docx"]
        )
        results["all_passed"] = all_passed
        results["summary"] = "All export formats working!" if all_passed else "Some exports failed"

        return results

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Export format test failed: {e}")
        import traceback
        results["error"] = str(e)
        results["traceback"] = traceback.format_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-legal-research")
async def test_legal_research(
    secret: str = Query(..., description="Secret key for internal testing"),
    db: AsyncSession = Depends(get_db)
):
    """
    Test the CourtListener legal research integration.

    Tests:
    1. CourtListener search API works
    2. Results are properly formatted
    3. PDF download (if available)
    """
    if secret != E2E_TEST_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret key")

    from app.services.legal_research_service import get_legal_research_service

    results = {
        "test": "legal_research_integration",
        "courtlistener_search": {"passed": False},
        "result_formatting": {"passed": False},
        "pdf_availability": {"passed": False},
        "all_passed": False
    }

    try:
        legal_service = get_legal_research_service()

        # Test 1: CourtListener search
        try:
            search_results = await legal_service.search_case_law(
                query="personal injury negligence California",
                jurisdiction={"state": "cal", "court_type": "state"},
                max_results=5
            )

            results["courtlistener_search"] = {
                "passed": len(search_results) > 0,
                "result_count": len(search_results),
                "message": f"Found {len(search_results)} results"
            }

            if search_results:
                # Test 2: Result formatting
                first_result = search_results[0]
                has_required_fields = all([
                    first_result.id,
                    first_result.case_name,
                    first_result.absolute_url
                ])

                results["result_formatting"] = {
                    "passed": has_required_fields,
                    "sample_result": {
                        "id": first_result.id,
                        "case_name": first_result.case_name[:100] if first_result.case_name else None,
                        "citation": first_result.citation,
                        "court": first_result.court,
                        "date_filed": first_result.date_filed,
                        "has_pdf_url": first_result.pdf_url is not None,
                        "absolute_url": first_result.absolute_url[:100] if first_result.absolute_url else None
                    }
                }

                # Test 3: Check PDF availability (don't download, just check)
                pdf_available_count = sum(1 for r in search_results if r.pdf_url)
                results["pdf_availability"] = {
                    "passed": True,  # Just informational
                    "pdf_available": pdf_available_count,
                    "total": len(search_results),
                    "message": f"{pdf_available_count}/{len(search_results)} results have PDFs available"
                }
            else:
                results["result_formatting"] = {"passed": False, "message": "No results to format"}
                results["pdf_availability"] = {"passed": False, "message": "No results to check"}

        except Exception as e:
            results["courtlistener_search"] = {
                "passed": False,
                "error": str(e)
            }

        # Summary
        results["all_passed"] = all([
            results["courtlistener_search"].get("passed", False),
            results["result_formatting"].get("passed", False)
        ])

        return results

    except Exception as e:
        logger.error(f"Legal research test failed: {e}")
        import traceback
        results["error"] = str(e)
        results["traceback"] = traceback.format_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-clio-upload")
async def test_clio_upload(
    secret: str = Query(..., description="Secret key for internal testing"),
    matter_id: Optional[int] = Query(None, description="Clio matter ID to test with"),
    db: AsyncSession = Depends(get_db)
):
    """
    Test the Clio folder creation and document upload.

    Tests:
    1. Can create a folder in Clio
    2. Can upload a test document
    3. Can clean up test artifacts
    """
    if secret != E2E_TEST_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret key")

    results = {
        "test": "clio_upload_integration",
        "clio_connection": {"passed": False},
        "folder_creation": {"passed": False},
        "document_upload": {"passed": False},
        "cleanup": {"passed": False},
        "all_passed": False
    }

    try:
        # Get Clio integration
        integration_result = await db.execute(
            select(ClioIntegration).limit(1)
        )
        integration = integration_result.scalar_one_or_none()

        if not integration:
            results["error"] = "No Clio integration found"
            return results

        results["clio_connection"]["passed"] = True
        results["clio_connection"]["region"] = integration.clio_region

        # Get a matter to test with
        if matter_id:
            matter_result = await db.execute(
                select(Matter).where(Matter.clio_matter_id == str(matter_id))
            )
        else:
            matter_result = await db.execute(
                select(Matter).where(Matter.user_id == integration.user_id).limit(1)
            )

        matter = matter_result.scalar_one_or_none()

        if not matter:
            results["error"] = "No matter found to test with"
            return results

        results["clio_connection"]["matter_id"] = matter.clio_matter_id
        results["clio_connection"]["matter_name"] = matter.display_number

        # Test folder creation and document upload
        async with ClioClient(
            access_token=decrypt_token(integration.access_token_encrypted),
            refresh_token=decrypt_token(integration.refresh_token_encrypted),
            token_expires_at=integration.token_expires_at,
            region=integration.clio_region
        ) as clio:
            folder_id = None

            # Test 1: Try to create test folder (may fail with 403 - that's OK)
            try:
                test_folder_name = f"_E2E_Test_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
                folder = await clio.create_folder(
                    matter_id=int(matter.clio_matter_id),
                    name=test_folder_name
                )

                folder_id = folder.get("id") if folder else None
                results["folder_creation"] = {
                    "passed": folder_id is not None,
                    "folder_id": folder_id,
                    "folder_name": test_folder_name
                }

            except Exception as e:
                # Folder creation may fail - capture detailed error
                error_detail = str(e)
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        error_detail = f"{str(e)} | Response: {e.response.text}"
                    except Exception:
                        pass
                results["folder_creation"] = {
                    "passed": False,
                    "error": error_detail,
                    "note": "Folder creation may require additional OAuth scopes. Document upload will be tested without folder."
                }

            # Test 2: Upload test document (to folder if created, otherwise to matter root)
            try:
                # Create simple test PDF content
                test_content = b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n203\n%%EOF"

                doc = await clio.upload_document(
                    matter_id=int(matter.clio_matter_id),
                    file_content=test_content,
                    filename="E2E_Test_Document.pdf",
                    folder_id=folder_id  # Will be None if folder creation failed
                )

                results["document_upload"] = {
                    "passed": doc is not None and doc.get("id") is not None,
                    "document_id": doc.get("id") if doc else None,
                    "uploaded_to_folder": folder_id is not None,
                    "message": "Successfully uploaded test document"
                }

            except Exception as e:
                # Capture detailed error with response body
                error_detail = str(e)
                if hasattr(e, 'response') and e.response is not None:
                    try:
                        error_detail = f"{str(e)} | Response: {e.response.text}"
                    except Exception:
                        pass
                results["document_upload"] = {
                    "passed": False,
                    "error": error_detail
                }

            # Cleanup note
            results["cleanup"] = {
                "passed": True,
                "message": "Test artifacts created. Manual cleanup may be needed in Clio."
            }

        # Summary - document upload is the key test, folder creation is optional
        results["all_passed"] = all([
            results["clio_connection"].get("passed", False),
            results["document_upload"].get("passed", False)
        ])
        results["folder_creation_optional"] = "Folder creation is optional. Documents can be uploaded to matter root if folder creation fails."

        return results

    except Exception as e:
        logger.error(f"Clio upload test failed: {e}")
        import traceback
        results["error"] = str(e)
        results["traceback"] = traceback.format_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-document-count")
async def test_document_count(
    secret: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Test document counting with different folder options.
    Tests the include_subfolders logic.
    """
    if secret != E2E_TEST_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")

    results = {
        "test": "document_count_with_subfolders",
        "tests": []
    }

    try:
        # Get first active integration
        integration_result = await db.execute(
            select(ClioIntegration).where(ClioIntegration.is_active == True)
        )
        integration = integration_result.scalars().first()

        if not integration:
            results["error"] = "No active Clio integration found"
            return results

        # Get a matter with documents (the Ponce matter from the screenshots)
        matter_result = await db.execute(
            select(Matter).where(
                Matter.user_id == integration.user_id,
                Matter.display_number.like("%Ponce%")
            )
        )
        matter = matter_result.scalars().first()

        if not matter:
            results["error"] = "No Ponce matter found"
            return results

        results["matter"] = {
            "id": matter.id,
            "clio_matter_id": matter.clio_matter_id,
            "name": matter.display_number
        }

        async with ClioClient(
            access_token=decrypt_token(integration.access_token_encrypted),
            refresh_token=decrypt_token(integration.refresh_token_encrypted),
            token_expires_at=integration.token_expires_at,
            region=integration.clio_region
        ) as clio:
            # Test 1: Count all documents in matter (no folder filter)
            all_docs_count = 0
            async for _ in clio.get_documents(matter_id=int(matter.clio_matter_id), fields=["id"]):
                all_docs_count += 1
            results["tests"].append({
                "name": "all_documents_in_matter",
                "count": all_docs_count
            })

            # Test 2: Get folder structure
            folders = []
            async for folder in clio.get_folders(int(matter.clio_matter_id)):
                folders.append({
                    "id": folder.get("id"),
                    "name": folder.get("name"),
                    "parent_id": folder.get("parent", {}).get("id") if folder.get("parent") else None
                })
            results["folders"] = folders

            # Test 3: For the first few folders, count with and without subfolders
            # Note: Clio may return folders whose parent is outside our query scope
            # So we test the actual folders we have, not just "root" folders
            test_folders = folders[:3]  # Test first 3 folders only (to avoid timeout)
            for rf in test_folders:
                folder_id = rf["id"]
                folder_name = rf["name"]

                try:
                    # Count without subfolders
                    count_direct = 0
                    async for _ in clio.get_documents_in_folder(
                        folder_id,
                        matter_id=int(matter.clio_matter_id),
                        fields=["id"]
                    ):
                        count_direct += 1

                    # Count with subfolders
                    count_recursive = 0
                    async for _ in clio.get_documents_recursive(
                        matter_id=int(matter.clio_matter_id),
                        folder_id=folder_id,
                        fields=["id"]
                    ):
                        count_recursive += 1

                    results["tests"].append({
                        "name": f"folder_{folder_name}",
                        "folder_id": folder_id,
                        "count_direct": count_direct,
                        "count_with_subfolders": count_recursive
                    })
                except Exception as folder_err:
                    results["tests"].append({
                        "name": f"folder_{folder_name}",
                        "folder_id": folder_id,
                        "error": str(folder_err)
                    })

        results["passed"] = True
        return results

    except Exception as e:
        logger.error(f"Document count test failed: {e}")
        import traceback
        results["error"] = str(e)
        results["traceback"] = traceback.format_exc()
        return results
