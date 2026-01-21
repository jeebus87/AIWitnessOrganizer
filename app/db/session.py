"""Database session and engine configuration"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import declarative_base

from app.core.config import settings


# Create async engine with connection pooling optimized for multi-tenant scalability
# pool_size: base number of persistent connections
# max_overflow: additional connections allowed when pool is full
# pool_recycle: recycle connections after 30 min to avoid stale connections
# pool_timeout: wait up to 30 sec for a connection before raising error
engine = create_async_engine(
    settings.database_url_async,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=40,
    pool_recycle=1800,
    pool_timeout=30,
)

# Create async session factory
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Base class for models
Base = declarative_base()


async def get_db() -> AsyncSession:
    """Dependency for getting database sessions.

    Auto-commits after the endpoint returns successfully.
    Rolls back on exception.
    """
    session = AsyncSessionLocal()
    try:
        yield session
        await session.commit()  # Auto-commit after successful endpoint
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def init_db():
    """Initialize database tables"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """Close database connections"""
    await engine.dispose()
