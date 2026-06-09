"""
Telemetry & Reporting Endpoints.
"""
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional
from pydantic import BaseModel

from app.api.deps import get_db, get_current_temple_manager, get_current_superadmin, get_current_temple_id
from app.core.database import AsyncSessionLocal
from app.schemas.domain import TokenData
from app.modules.analytics.services.analytics_service import AnalyticsService

public_router = APIRouter()
manager_router = APIRouter()
superadmin_router = APIRouter()


class AdEventPayload(BaseModel):
    advertisement_id: UUID
    advertisement_type: str  # 'PLATFORM' or 'TEMPLE'
    event_type: str  # 'IMPRESSION' or 'CLICK'
    visitor_hash: str
    session_id: Optional[str] = None


class PortalEventPayload(BaseModel):
    temple_id: Optional[UUID] = None
    event_name: str
    visitor_hash: str
    session_id: Optional[str] = None
    user_id: Optional[UUID] = None
    event_metadata: Optional[dict] = None


# Async background task handlers to keep API non-blocking
async def record_ad_event_bg(payload: AdEventPayload):
    async with AsyncSessionLocal() as db:
        try:
            await AnalyticsService.log_advertisement_event(
                db=db,
                advertisement_id=payload.advertisement_id,
                advertisement_type=payload.advertisement_type,
                event_type=payload.event_type,
                visitor_hash=payload.visitor_hash,
                session_id=payload.session_id,
            )
        except Exception:
            # Suppress database write issues in fire-and-forget logs
            pass


async def record_portal_event_bg(payload: PortalEventPayload):
    async with AsyncSessionLocal() as db:
        try:
            await AnalyticsService.log_portal_event(
                db=db,
                temple_id=payload.temple_id,
                event_name=payload.event_name,
                visitor_hash=payload.visitor_hash,
                session_id=payload.session_id,
                user_id=payload.user_id,
                event_metadata=payload.event_metadata,
            )
        except Exception:
            pass


@public_router.post("/advertisements/events")
async def log_ad_event(payload: AdEventPayload, background_tasks: BackgroundTasks):
    """Log ad impression/click event asynchronously (SLA: < 50ms)."""
    background_tasks.add_task(record_ad_event_bg, payload)
    return {"status": "enqueued"}


@public_router.post("/analytics/events")
async def log_portal_event(payload: PortalEventPayload, background_tasks: BackgroundTasks):
    """Log standard devotee portal event asynchronously (SLA: < 50ms)."""
    from app.models.domain import PortalAnalyticsEventType
    try:
        PortalAnalyticsEventType(payload.event_name)
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail=f"Invalid analytics event name: '{payload.event_name}'"
        )
    background_tasks.add_task(record_portal_event_bg, payload)
    return {"status": "enqueued"}


@manager_router.get("/advertisements/reports")
async def get_manager_ad_report(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_temple_manager),
    temple_id_str: str = Depends(get_current_temple_id)
):
    """Get pre-aggregated campaign health metrics for Temple Managers."""
    temple_id = UUID(temple_id_str)
    return await AnalyticsService.get_campaign_health_report(db=db, temple_id=temple_id)


@superadmin_router.get("/advertisements/reports")
async def get_superadmin_ad_report(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin)
):
    """Get platform campaign health metrics for Super Admins."""
    return await AnalyticsService.get_campaign_health_report(db=db, temple_id=None)
