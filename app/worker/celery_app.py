"""Celery application configuration"""
from celery import Celery

from app.core.config import settings


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
    worker_prefetch_multiplier=1,  # One task at a time
    worker_concurrency=4,  # 4 concurrent workers

    # Retry settings
    task_default_retry_delay=60,  # 1 minute
    task_max_retries=3,

    # Beat schedule (if needed for periodic tasks)
    beat_schedule={},
)
