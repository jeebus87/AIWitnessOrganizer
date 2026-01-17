"""Main FastAPI application"""
import subprocess
from contextlib import asynccontextmanager
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog

from app.core.config import settings
from app.db.session import init_db, close_db
from app.api.v1.routes import auth, witnesses, jobs, matters, billing


# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    # Startup
    logger.info("Starting AI Witness Finder API", environment=settings.environment)

    # Run database migrations
    logger.info("Running database migrations...")
    try:
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0:
            logger.info("Database migrations completed successfully")
        else:
            logger.error("Database migration failed", stderr=result.stderr, stdout=result.stdout)
    except Exception as e:
        logger.error("Failed to run database migrations", error=str(e))

    # Initialize database
    await init_db()
    logger.info("Database initialized")

    yield

    # Shutdown
    logger.info("Shutting down AI Witness Finder API")
    await close_db()


# Create FastAPI app
app = FastAPI(
    title="AI Witness Finder API",
    description="""
    Automated Legal Witness Extraction System.

    This API provides endpoints for:
    - Clio OAuth integration
    - Document processing and witness extraction
    - Background job management
    - PDF/Excel export generation
    """,
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)


# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next: Callable) -> Response:
    """Log all incoming requests"""
    logger.info(
        "Incoming request",
        method=request.method,
        url=str(request.url),
        client_ip=request.client.host if request.client else None
    )

    response = await call_next(request)

    logger.info(
        "Request completed",
        method=request.method,
        url=str(request.url),
        status_code=response.status_code
    )

    return response


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions"""
    logger.exception(
        "Unhandled exception",
        method=request.method,
        url=str(request.url),
        error=str(exc)
    )

    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal error occurred",
            "error": str(exc) if settings.debug else "Internal server error"
        }
    )


# Health check endpoint
@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint for load balancers and monitoring"""
    return {
        "status": "healthy",
        "version": "0.1.0",
        "environment": settings.environment
    }


# Root endpoint
@app.get("/", tags=["Root"])
async def root():
    """API root endpoint"""
    return {
        "name": "AI Witness Finder API",
        "version": "0.1.0",
        "docs": "/docs" if settings.debug else "Documentation disabled in production"
    }


# Include API routers
app.include_router(auth.router, prefix="/api/v1")
app.include_router(matters.router, prefix="/api/v1")
app.include_router(witnesses.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(billing.router, prefix="/api/v1")


# Startup message
@app.on_event("startup")
async def startup_message():
    """Log startup information"""
    logger.info(
        "API server started",
        app_name=settings.app_name,
        environment=settings.environment,
        debug=settings.debug
    )
