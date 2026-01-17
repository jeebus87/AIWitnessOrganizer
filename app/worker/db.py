"""Worker-specific database session without connection pool issues.

This module creates a fresh database engine for each worker task to avoid
asyncio event loop conflicts that occur when Celery tasks create new loops
but the connection pool still has connections from a previous loop.
"""
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.config import settings


@asynccontextmanager
async def get_worker_session():
    """Create a fresh database session for worker tasks.

    This creates a new engine and session for each task, avoiding the
    "Future attached to different loop" error that occurs with pooled connections.
    """
    # Create a fresh engine without connection pooling
    engine = create_async_engine(
        settings.database_url_async,
        echo=False,
        pool_pre_ping=False,  # Disable pre-ping to avoid event loop issues
        poolclass=None,  # Disable connection pooling entirely
    )

    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    session = session_factory()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()
