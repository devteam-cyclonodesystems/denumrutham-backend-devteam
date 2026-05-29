import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import text
from app.core.exceptions import AppException

from app.api.api_v1.api import api_router
from app.api.api_v1.endpoints import health
from app.core.config import settings
from app.core.database import engine, AsyncSessionLocal
from app.core.logging_config import setup_logging
from app.core.response import error_response
from app.core.middleware import (
    RequestIdMiddleware,
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
    HTTPSRedirectHeadersMiddleware,
)
from app.core.integrity import validate_on_startup

from app.core.limiter import limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from prometheus_fastapi_instrumentator import Instrumentator
import urllib.parse
import os
from app.events import handlers  # Registers event handlers
from app.services.notification_listeners import register_notification_listeners  # Phase 3

# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------
logger = setup_logging()

# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    import os
    build_commit = os.getenv("RAILWAY_GIT_COMMIT_SHA") or os.getenv("COMMIT_SHA") or "4cf6efdfb0032b49eb12818c1db2dfec94cb1fec"
    logger.warning(
        "ARCHANA HOTFIX BUILD ACTIVE",
        extra={
            "build_commit": build_commit,
            "build_timestamp": "2026-05-29T18:25:44+05:30"
        }
    )
    logger.info("Starting TMS API v%s", settings.VERSION)
    
    # Phase 5: Runtime Schema Validation
    is_valid = await validate_on_startup()
    if not is_valid:
        logger.critical("APPLICATION STARTUP BLOCKED: Schema Integrity Failure.")
        
    # Seed global permissions catalog (Mandatory Change 1)
    try:
        from app.services.staff_service import StaffService
        async with AsyncSessionLocal() as db:
            await StaffService.seed_global_permissions(db)
            logger.info("Global permissions catalog seeded successfully.")
    except Exception as e:
        logger.error("Failed to seed global permissions on startup: %s", str(e))
    
    # Phase 3: Notification Listeners
    register_notification_listeners()
    
    # Archana Auto-Completion Scheduler
    import asyncio
    from app.services.archana_lifecycle_service import ArchanaLifecycleService
    from app.tasks.background_jobs import cleanup_expired_reservations
    
    async def archana_completion_loop():
        while True:
            try:
                async with AsyncSessionLocal() as db:
                    await ArchanaLifecycleService.process_auto_completions(db)
            except Exception as e:
                logger.error("Error in archana_completion_loop: %s", str(e))
            await asyncio.sleep(60) # Run every minute
            
    asyncio.create_task(archana_completion_loop())

    async def reservation_cleanup_loop():
        while True:
            try:
                await cleanup_expired_reservations()
            except Exception as e:
                logger.error("Error in reservation_cleanup_loop: %s", str(e))
            await asyncio.sleep(60) # Run every minute
            
    asyncio.create_task(reservation_cleanup_loop())
    
    logger.info("Database schema handled by Alembic migrations.")
    yield
    logger.info("Shutting down TMS API")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
    redirect_slashes=True,
)

@app.get("/health/live")
async def health_live():
    return {"status": "alive"}

@app.get("/api/v1/diag/ping")
async def diag_ping():
    return {"status": "pong", "message": "Backend is reachable and updated"}

# Attach limiter to app state
app.state.limiter = limiter
from slowapi import _rate_limit_exceeded_handler
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ---------------------------------------------------------------------------
# Static Files — serve uploaded media
# ---------------------------------------------------------------------------
os.makedirs("static/uploads", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ---------------------------------------------------------------------------
# Middleware stack (order matters: last added = first executed)
# ---------------------------------------------------------------------------

# 1. CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|.*\.vercel\.app|.*\.denumrutham\.com)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Process-Time-Ms"],
)

# 2. Security headers
app.add_middleware(SecurityHeadersMiddleware)

# 3. Request logging (with tenant/user context)
app.add_middleware(RequestLoggingMiddleware)

# 4. Request ID generation
app.add_middleware(RequestIdMiddleware)

# 5. HTTPS Redirect / Proxy-Awareness (Outer-most wrapper, executes first)
app.add_middleware(HTTPSRedirectHeadersMiddleware)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------
app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(api_router, prefix=settings.API_V1_STR)


# ---------------------------------------------------------------------------
# Prometheus Instrumentation
# ---------------------------------------------------------------------------
Instrumentator(
    excluded_handlers=[".*/metrics", ".*/health/live", ".*/health/ready"]
).instrument(app).expose(app)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", "-")
    
    # Map status codes to internal codes
    code_map = {
        401: "AUTH_EXPIRED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        400: "BAD_REQUEST",
        422: "VALIDATION_FAILED"
    }
    code = code_map.get(exc.status_code, "HTTP_ERROR")
    
    return error_response(
        message=str(exc.detail),
        code=code,
        status_code=exc.status_code,
        request_id=request_id
    )


# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", "-")
    logger.error(
        "Validation error on %s: %s",
        request.url.path,
        exc.errors(),
        extra={"request_id": request_id},
    )
    return error_response(
        message="Request validation failed",
        code="VALIDATION_ERROR",
        status_code=422,
        request_id=request_id
    )


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
    request_id = getattr(request.state, "request_id", "-")
    logger.error(
        "Database error on %s: %s",
        request.url.path,
        str(exc),
        exc_info=True,
        extra={"request_id": request_id},
    )
    return error_response(
        message="Internal database error",
        code="DATABASE_ERROR",
        status_code=500,
        request_id=request_id
    )


@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    request_id = getattr(request.state, "request_id", "-")
    logger.warning(
        "Application exception on %s: %s",
        request.url.path,
        exc.message,
        extra={"request_id": request_id},
    )
    # Use code if available (e.g. from ServiceException), else class name
    code = getattr(exc, "code", exc.__class__.__name__.upper())
    return error_response(
        message=exc.message,
        code=code,
        status_code=exc.status_code,
        request_id=request_id
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "-")
    logger.error(
        "Unhandled exception on %s: %s",
        request.url.path,
        str(exc),
        exc_info=True,
        extra={"request_id": request_id},
    )
    return error_response(
        message="Internal server error",
        code="INTERNAL_SERVER_ERROR",
        status_code=500,
        request_id=request_id
    )
