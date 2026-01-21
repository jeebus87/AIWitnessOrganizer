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

# Configure Celery for multi-tenant scalability
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

    # Worker settings for high concurrency
    worker_prefetch_multiplier=1,  # One task at a time per worker for fairness
    # Autoscaling: 8-100 workers based on queue depth (set via --autoscale=100,8 in Procfile)

    # Broker (Redis) settings for reliability
    broker_connection_retry_on_startup=True,
    broker_pool_limit=50,  # Redis connection pool limit

    # Retry settings
    task_default_retry_delay=60,  # 1 minute
    task_max_retries=3,

    # Enable task events for monitoring (optional, can disable if too noisy)
    worker_send_task_events=False,
    task_send_sent_event=False,
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
