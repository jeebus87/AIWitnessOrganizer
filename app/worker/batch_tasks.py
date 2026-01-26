"""
Celery tasks for batch inference job polling and result processing.

These tasks run periodically to:
1. Poll pending batch jobs for completion
2. Process results when jobs complete
3. Update BatchJob status and notify users
"""

import asyncio
from datetime import datetime
from typing import Dict, Any

from celery import shared_task
from celery.utils.log import get_task_logger
from sqlalchemy import select, update

from app.worker.celery_app import celery_app
from app.worker.db import get_worker_session
from app.db.models import (
    BatchJob, BatchJobType, ProcessingJob, JobStatus
)
from app.services.batch_inference_service import get_batch_inference_service
from app.services.witness_batch_service import get_witness_batch_service

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
def poll_batch_jobs(self):
    """
    Poll all pending batch jobs and process completed ones.

    This task should be scheduled to run every 30-60 seconds via Celery Beat.
    """
    return run_async(_poll_batch_jobs_async())


async def _poll_batch_jobs_async():
    """Async implementation of batch job polling."""
    batch_service = get_batch_inference_service()

    async with get_worker_session() as session:
        # Get all pending batch jobs
        result = await session.execute(
            select(BatchJob).where(
                BatchJob.status.in_(["Submitted", "InProgress", "Validating"])
            )
        )
        pending_jobs = result.scalars().all()

        if not pending_jobs:
            logger.debug("No pending batch jobs to poll")
            return {"polled": 0, "completed": 0, "failed": 0}

        logger.info(f"Polling {len(pending_jobs)} pending batch jobs")

        completed = 0
        failed = 0

        for batch_job in pending_jobs:
            try:
                # Check job status with AWS
                status_info = batch_service.check_job_status(batch_job.aws_job_arn)
                aws_status = status_info.get("status", "Unknown")

                logger.debug(f"Batch job {batch_job.id} ({batch_job.aws_job_arn}): {aws_status}")

                # Update local status
                batch_job.status = aws_status

                if aws_status == "Completed":
                    # Download and store results
                    output_uri = status_info.get("output_uri") or batch_job.output_s3_uri
                    if output_uri:
                        try:
                            results = batch_service.download_and_parse_results(output_uri)
                            batch_job.results_json = results
                            batch_job.completed_at = datetime.utcnow()
                            batch_job.processed_records = len(results)
                            completed += 1

                            logger.info(
                                f"Batch job {batch_job.id} completed with {len(results)} results"
                            )

                            # Trigger result processing task
                            process_batch_results.delay(batch_job.id)

                        except Exception as e:
                            logger.error(f"Failed to download results for batch job {batch_job.id}: {e}")
                            batch_job.status = "Failed"
                            batch_job.error_message = f"Failed to download results: {e}"
                            failed += 1

                elif aws_status == "Failed":
                    batch_job.error_message = status_info.get("message", "Unknown error")
                    batch_job.completed_at = datetime.utcnow()
                    failed += 1

                    logger.error(
                        f"Batch job {batch_job.id} failed: {batch_job.error_message}"
                    )

                    # Update associated processing job status
                    if batch_job.processing_job_id:
                        await session.execute(
                            update(ProcessingJob)
                            .where(ProcessingJob.id == batch_job.processing_job_id)
                            .values(
                                status=JobStatus.FAILED,
                                error_message=f"Batch inference failed: {batch_job.error_message}",
                                completed_at=datetime.utcnow()
                            )
                        )

                elif aws_status == "Stopped":
                    batch_job.status = "Failed"
                    batch_job.error_message = "Job was stopped"
                    batch_job.completed_at = datetime.utcnow()
                    failed += 1

                # Update token counts if available
                if status_info.get("input_tokens"):
                    batch_job.processed_records = status_info.get("input_tokens", 0)

            except Exception as e:
                logger.error(f"Error polling batch job {batch_job.id}: {e}")

        await session.commit()

        return {
            "polled": len(pending_jobs),
            "completed": completed,
            "failed": failed
        }


@celery_app.task(bind=True, max_retries=3)
def process_batch_results(self, batch_job_id: int):
    """
    Process results from a completed batch job.

    Routes to appropriate handler based on job type.
    """
    return run_async(_process_batch_results_async(batch_job_id))


async def _process_batch_results_async(batch_job_id: int):
    """Async implementation of batch result processing."""
    async with get_worker_session() as session:
        # Get batch job
        result = await session.execute(
            select(BatchJob).where(BatchJob.id == batch_job_id)
        )
        batch_job = result.scalar_one_or_none()

        if not batch_job:
            logger.error(f"Batch job {batch_job_id} not found")
            return {"success": False, "error": "Batch job not found"}

        if not batch_job.results_json:
            logger.error(f"Batch job {batch_job_id} has no results")
            return {"success": False, "error": "No results to process"}

        logger.info(
            f"Processing results for batch job {batch_job_id} "
            f"(type: {batch_job.job_type})"
        )

        try:
            if batch_job.job_type == BatchJobType.WITNESS_EXTRACTION:
                return await _process_witness_extraction_results(session, batch_job)
            elif batch_job.job_type == BatchJobType.LEGAL_RESEARCH:
                return await _process_legal_research_results(session, batch_job)
            else:
                logger.warning(f"Unknown batch job type: {batch_job.job_type}")
                return {"success": False, "error": f"Unknown job type: {batch_job.job_type}"}

        except Exception as e:
            logger.error(f"Error processing batch results: {e}")
            batch_job.error_message = f"Result processing failed: {e}"
            await session.commit()
            return {"success": False, "error": str(e)}


async def _process_witness_extraction_results(session, batch_job: BatchJob) -> Dict[str, Any]:
    """Process witness extraction batch results."""
    witness_service = get_witness_batch_service()

    # Process and save witnesses
    saved_count = await witness_service.process_completed_batch(session, batch_job)

    # Update processing job status
    if batch_job.processing_job_id:
        result = await session.execute(
            select(ProcessingJob).where(ProcessingJob.id == batch_job.processing_job_id)
        )
        processing_job = result.scalar_one_or_none()

        if processing_job:
            processing_job.status = JobStatus.COMPLETED
            processing_job.completed_at = datetime.utcnow()
            await session.commit()

            logger.info(
                f"Processing job {processing_job.id} completed with {saved_count} witnesses"
            )

    return {"success": True, "witnesses_saved": saved_count}


async def _process_legal_research_results(session, batch_job: BatchJob) -> Dict[str, Any]:
    """Process legal research batch results."""
    from app.services.legal_research_service import get_legal_research_service

    legal_research_service = get_legal_research_service()

    # Process and save legal research results
    saved_count = await legal_research_service.process_completed_batch(session, batch_job)

    logger.info(f"Legal research batch job {batch_job.id} processed: {saved_count} results")

    return {"success": True, "results_saved": saved_count}


# Celery Beat schedule for batch job polling
celery_app.conf.beat_schedule = celery_app.conf.beat_schedule or {}
celery_app.conf.beat_schedule["poll-batch-jobs"] = {
    "task": "app.worker.batch_tasks.poll_batch_jobs",
    "schedule": 30.0,  # Every 30 seconds
    "options": {"queue": "default"}
}
