
from fastapi import APIRouter, Depends, HTTPException
from app.api.deps import get_current_superadmin
from app.core.integrity import DeploymentIntegrityService
from app.schemas.domain import TokenData

router = APIRouter()

@router.get("/integrity")
async def get_system_integrity(
    current_user: TokenData = Depends(get_current_superadmin)
):
    """
    Phase 1: Deployment Drift Detection.
    Returns the comprehensive integrity status of the system.
    """
    return await DeploymentIntegrityService.get_integrity_status()

@router.get("/version")
async def get_system_version():
    """
    Phase 4: Container Integrity System.
    Exposes versioning metadata without requiring full admin auth (public health check).
    """
    return DeploymentIntegrityService.get_build_info()

@router.get("/outbox/metrics")
async def get_outbox_metrics(
    current_user: TokenData = Depends(get_current_superadmin)
):
    """
    Returns the real-time processing metrics of the background activity log outbox worker.
    """
    from app.modules.audit.services.activity_log_processor import OutboxMetrics
    from datetime import datetime, timezone
    
    # Calculate if worker is alive (heartbeat within last 2 minutes)
    is_alive = False
    if OutboxMetrics.last_heartbeat:
        now = datetime.now(timezone.utc)
        diff = (now - OutboxMetrics.last_heartbeat).total_seconds()
        is_alive = diff < 120

    return {
        "worker_running": OutboxMetrics.worker_running,
        "worker_alive": is_alive,
        "queue_depth": OutboxMetrics.queue_depth,
        "oldest_pending_event_age_seconds": OutboxMetrics.oldest_pending_event_age_seconds,
        "total_processed": OutboxMetrics.total_processed,
        "total_failed": OutboxMetrics.total_failed,
        "total_retries": OutboxMetrics.total_retries,
        "last_heartbeat": OutboxMetrics.last_heartbeat.isoformat() if OutboxMetrics.last_heartbeat else None
    }
