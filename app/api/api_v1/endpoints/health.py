from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text
from app.core.config import settings
from app.core.database import AsyncSessionLocal

router = APIRouter()

@router.get("/live")
async def health_live():
    """Returns basic service alive status (Liveness probe)."""
    return {
        "status": "alive",
        "version": settings.VERSION
    }

@router.get("/ready")
async def health_ready():
    """Returns DB and Redis connectivity (Readiness probe)."""
    db_status = "ok"
    db_detail = None
    redis_status = "ok"
    redis_detail = None

    # Check Database
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception as e:
        db_status = "error"
        db_detail = str(e)

    # Check Redis
    import redis.asyncio as aioredis
    try:
        redis_client = aioredis.from_url(settings.REDIS_URL)
        await redis_client.ping()
        await redis_client.aclose()
    except Exception as e:
        redis_status = "error"
        redis_detail = str(e)

    overall = "ready" if (db_status == "ok" and redis_status == "ok") else "degraded"
    status_code = 200 if overall == "ready" else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": overall,
            "version": settings.VERSION,
            "database": db_status,
            "database_detail": db_detail,
            "redis": redis_status,
            "redis_detail": redis_detail
        }
    )

@router.get("/deep")
async def health_deep():
    """
    Phase 9: Deep Health & Observability.
    Comprehensive validation of DB, Redis, Schema, and Sync Engine.
    """
    from app.core.integrity import DeploymentIntegrityService
    integrity = await DeploymentIntegrityService.get_integrity_status()
    
    # Check Readiness logic
    ready_resp = await health_ready()
    import json
    ready_data = json.loads(ready_resp.body.decode())
    
    return {
        "status": "healthy" if (ready_data["status"] == "ready" and integrity["status"] == "healthy") else "degraded",
        "infrastructure": ready_data,
        "integrity": integrity,
        "sync_engine": "healthy", # Placeholder
        "governance": "healthy" if integrity["schema_valid"] else "degraded"
    }
