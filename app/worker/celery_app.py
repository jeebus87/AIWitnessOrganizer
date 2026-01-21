"""Celery application configuration"""
from celery import Celery
from celery.signals import worker_ready
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# Create Celery app
celery_app = Celery(
    "aiwitnessfinder",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.worker.tasks"
    ]
)

# Configure Celery
celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Timezone
    timezone="UTC",
    enable_utc=True,

    # Task settings
    task_track_started=True,
    task_time_limit=14400,  # 4 hours max per task
    task_soft_time_limit=10800,  # Soft limit at 3 hours
    task_acks_late=True,  # Acknowledge after completion
    task_reject_on_worker_lost=True,

    # Result settings
    result_expires=86400,  # 24 hours

    # Worker settings
    worker_prefetch_multiplier=1,  # One task at a time per worker
    # Autoscaling: 8-100 workers based on queue depth (set via --autoscale=100,8 in Procfile)

    # Retry settings
    task_default_retry_delay=60,  # 1 minute
    task_max_retries=3,

    # Beat schedule for automatic job recovery
    # Runs every 60 seconds to check for and finalize stuck jobs
    beat_schedule={
        "auto-recover-stuck-jobs": {
            "task": "app.worker.tasks.recover_stuck_jobs",
            "schedule": 60.0,  # Every 60 seconds
        },
    },
)


@worker_ready.connect
def on_worker_ready(sender, **kwargs):
    """
    Called when the worker is ready to accept tasks.
    Checks for stuck jobs and resumes them.
    """
    logger.info("Worker ready - checking for stuck jobs to resume...")

    # Import here to avoid circular imports
    from app.worker.tasks import recover_stuck_jobs

    # Delay slightly to ensure worker is fully initialized
    recover_stuck_jobs.apply_async(countdown=5)
