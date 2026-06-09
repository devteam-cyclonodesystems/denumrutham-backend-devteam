"""
Analytics Service — Centralized log service for devotee portal and advertisement tracking.
"""
import logging
from uuid import UUID
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from fastapi import HTTPException

from app.models.domain import (
    AdvertisementAnalytics,
    PlatformAdvertisement,
    TempleAdvertisement,
    PortalAnalyticsEvent,
    PortalAnalyticsEventType,
)

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Telemetry capture and Campaign Health Reporting engine."""

    @staticmethod
    async def log_advertisement_event(
        db: AsyncSession,
        advertisement_id: UUID,
        advertisement_type: str,
        event_type: str,
        visitor_hash: str,
        session_id: Optional[str] = None,
    ) -> bool:
        """
        Record ad impression/click events with 1-hour deduplication rules.
        Returns True if event is recorded, False if discarded as duplicate.
        """
        # 1. Event Validation
        if event_type not in ("IMPRESSION", "CLICK"):
            raise ValueError(f"Invalid advertisement event_type: {event_type}")
        if advertisement_type not in ("PLATFORM", "TEMPLE"):
            raise ValueError(f"Invalid advertisement_type: {advertisement_type}")

        # 2. Deduplication check (IMPRESSION only)
        if event_type == "IMPRESSION":
            one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
            
            stmt = select(AdvertisementAnalytics).filter(
                AdvertisementAnalytics.event_type == "IMPRESSION",
                AdvertisementAnalytics.visitor_hash == visitor_hash,
                AdvertisementAnalytics.created_at >= one_hour_ago
            )
            if session_id:
                stmt = stmt.filter(AdvertisementAnalytics.session_id == session_id)

            if advertisement_type == "PLATFORM":
                stmt = stmt.filter(AdvertisementAnalytics.platform_advertisement_id == advertisement_id)
            else:
                stmt = stmt.filter(AdvertisementAnalytics.temple_advertisement_id == advertisement_id)

            res = await db.execute(stmt)
            if res.scalars().first():
                logger.info(
                    "Deduplicated impression for ad %s, visitor %s",
                    advertisement_id,
                    visitor_hash,
                )
                return False  # Discard duplicate impression

        # 3. Persistence
        ad_id_key = (
            "platform_advertisement_id"
            if advertisement_type == "PLATFORM"
            else "temple_advertisement_id"
        )
        params = {
            "advertisement_type": advertisement_type,
            ad_id_key: advertisement_id,
            "event_type": event_type,
            "visitor_hash": visitor_hash,
            "session_id": session_id,
        }

        analytics_record = AdvertisementAnalytics(**params)
        db.add(analytics_record)
        await db.commit()
        logger.info(
            "Logged ad event: ad_id=%s, type=%s, event=%s",
            advertisement_id,
            advertisement_type,
            event_type,
        )
        
        # Trigger background ad revenue calculation and cap checks
        import asyncio
        asyncio.create_task(_bg_recalculate_revenue_and_check_caps(advertisement_id, advertisement_type))
        
        return True


async def _bg_recalculate_revenue_and_check_caps(campaign_id: UUID, campaign_type: str):
    from app.core.database.database import AsyncSessionLocal
    from app.modules.temple_management.models.temple_models import PlatformAdvertisement, TempleAdvertisement, CampaignRevenueMetrics
    from app.models.domain import AdvertisementAnalytics
    from sqlalchemy import select, func
    from datetime import datetime, timezone
    import uuid
    
    try:
        async with AsyncSessionLocal() as db:
            async with db.begin():
                # 1. Fetch Campaign
                if campaign_type == "PLATFORM":
                    stmt = select(PlatformAdvertisement).filter(PlatformAdvertisement.id == campaign_id)
                else:
                    stmt = select(TempleAdvertisement).filter(TempleAdvertisement.id == campaign_id)
                    
                res = await db.execute(stmt)
                camp = res.scalar_one_or_none()
                if not camp:
                    return
                    
                # 2. Calculate Impressions & Clicks
                if campaign_type == "PLATFORM":
                    imp_q = select(func.count(AdvertisementAnalytics.id)).filter(
                        AdvertisementAnalytics.platform_advertisement_id == campaign_id,
                        AdvertisementAnalytics.event_type == "IMPRESSION"
                    )
                    clk_q = select(func.count(AdvertisementAnalytics.id)).filter(
                        AdvertisementAnalytics.platform_advertisement_id == campaign_id,
                        AdvertisementAnalytics.event_type == "CLICK"
                    )
                else:
                    imp_q = select(func.count(AdvertisementAnalytics.id)).filter(
                        AdvertisementAnalytics.temple_advertisement_id == campaign_id,
                        AdvertisementAnalytics.event_type == "IMPRESSION"
                    )
                    clk_q = select(func.count(AdvertisementAnalytics.id)).filter(
                        AdvertisementAnalytics.temple_advertisement_id == campaign_id,
                        AdvertisementAnalytics.event_type == "CLICK"
                    )
                    
                imp_res = await db.execute(imp_q)
                impressions = imp_res.scalar() or 0
                
                clk_res = await db.execute(clk_q)
                clicks = clk_res.scalar() or 0
                
                # 3. Calculate Revenue
                cpm_rate = camp.cpm_rate or 0.0
                cpc_rate = camp.cpc_rate or 0.0
                revenue = (cpm_rate * impressions / 1000.0) + (cpc_rate * clicks)
                
                # 4. Update CampaignRevenueMetrics
                metrics_stmt = select(CampaignRevenueMetrics).filter(
                    CampaignRevenueMetrics.campaign_id == campaign_id
                )
                metrics_res = await db.execute(metrics_stmt)
                metrics = metrics_res.scalar_one_or_none()
                
                if not metrics:
                    metrics = CampaignRevenueMetrics(
                        id=uuid.uuid4(),
                        campaign_id=campaign_id,
                        campaign_type=campaign_type,
                        total_impressions=impressions,
                        total_clicks=clicks,
                        estimated_revenue=revenue,
                        last_calculated_at=datetime.now(timezone.utc)
                    )
                    db.add(metrics)
                else:
                    metrics.total_impressions = impressions
                    metrics.total_clicks = clicks
                    metrics.estimated_revenue = revenue
                    metrics.last_calculated_at = datetime.now(timezone.utc)
                    
                # 5. Check Caps and transition APPROVED -> EXPIRED
                cap_reached = False
                if camp.impression_cap and impressions >= camp.impression_cap:
                    cap_reached = True
                if camp.click_cap and clicks >= camp.click_cap:
                    cap_reached = True
                    
                if cap_reached and camp.approval_status == "APPROVED":
                    camp.approval_status = "EXPIRED"
                    logger.info("Campaign %s reached cap and transitioned to EXPIRED", campaign_id)
                    
    except Exception as e:
        logger.error("Error in background ad revenue and cap calculations: %s", e)


    @staticmethod
    async def log_portal_event(
        db: AsyncSession,
        temple_id: Optional[UUID],
        event_name: str,
        visitor_hash: str,
        session_id: Optional[str] = None,
        user_id: Optional[UUID] = None,
        event_metadata: Optional[Dict[str, Any]] = None,
    ) -> PortalAnalyticsEvent:
        """Centralized logging for standard devotee portal events."""
        # 1. Event Validation
        try:
            PortalAnalyticsEventType(event_name)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid analytics event name: '{event_name}'"
            )

        # 2. Persistence and Enrichment
        event = PortalAnalyticsEvent(
            temple_id=temple_id,
            event_name=event_name,
            visitor_hash=visitor_hash,
            session_id=session_id,
            user_id=user_id,
            event_metadata=event_metadata or {},
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        logger.info("Logged portal event: name=%s, temple=%s", event_name, temple_id)
        return event

    @staticmethod
    async def get_campaign_health_report(
        db: AsyncSession, temple_id: Optional[UUID] = None
    ) -> List[Dict[str, Any]]:
        """Pre-aggregate campaign health metrics for admins."""
        now = datetime.now(timezone.utc)
        report = []

        if temple_id:
            # Query temple specific advertisements
            stmt = select(TempleAdvertisement).filter(TempleAdvertisement.temple_id == temple_id)
            res = await db.execute(stmt)
            campaigns = res.scalars().all()
        else:
            # Query platform advertisements
            stmt = select(PlatformAdvertisement)
            res = await db.execute(stmt)
            campaigns = res.scalars().all()

        # Gather metrics for each campaign
        for camp in campaigns:
            # Calculate impressions
            imp_stmt = select(func.count(AdvertisementAnalytics.id)).filter(
                AdvertisementAnalytics.event_type == "IMPRESSION"
            )
            if temple_id:
                imp_stmt = imp_stmt.filter(AdvertisementAnalytics.temple_advertisement_id == camp.id)
            else:
                imp_stmt = imp_stmt.filter(AdvertisementAnalytics.platform_advertisement_id == camp.id)
            
            imp_res = await db.execute(imp_stmt)
            impressions = imp_res.scalar() or 0

            # Calculate clicks
            clk_stmt = select(func.count(AdvertisementAnalytics.id)).filter(
                AdvertisementAnalytics.event_type == "CLICK"
            )
            if temple_id:
                clk_stmt = clk_stmt.filter(AdvertisementAnalytics.temple_advertisement_id == camp.id)
            else:
                clk_stmt = clk_stmt.filter(AdvertisementAnalytics.platform_advertisement_id == camp.id)
            
            clk_res = await db.execute(clk_stmt)
            clicks = clk_res.scalar() or 0

            # CTR Calculation
            ctr = (clicks / impressions * 100.0) if impressions > 0 else 0.0

            # Duration Remaining Calculation
            time_remaining = camp.end_date - now
            duration_remaining_days = max(0, time_remaining.days)

            # Active checks
            is_active_campaign = camp.is_active and (camp.start_date <= now <= camp.end_date)

            report.append({
                "campaign_id": camp.id,
                "placement": camp.placement,
                "media_type": camp.media_type,
                "target_url": camp.target_url,
                "impressions": impressions,
                "clicks": clicks,
                "ctr": round(ctr, 2),
                "is_active": is_active_campaign,
                "duration_remaining_days": duration_remaining_days,
                "top_performing": ctr > 5.0, # Top performing if Click-Through Rate is above 5%
            })

        return report
