"""
Advertisement Service — handles platform and temple campaigns logic.
"""
import logging
from uuid import UUID
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException

from app.models.domain import PlatformAdvertisement, TempleAdvertisement
from app.modules.temple_management.schemas.advertisement import (
    PlatformAdvertisementCreate,
    PlatformAdvertisementUpdate,
    TempleAdvertisementCreate,
    TempleAdvertisementUpdate,
)

logger = logging.getLogger(__name__)


class AdvertisementService:
    """Operations for Platform-wide and Temple-specific advertisements."""

    # ═══════════════════════════════════════════════════════════════════════
    # PLATFORM ADVERTISEMENTS (SUPER ADMIN)
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    async def create_platform_ad(
        db: AsyncSession, payload: PlatformAdvertisementCreate
    ) -> PlatformAdvertisement:
        """Create a new platform-wide advertisement."""
        ad = PlatformAdvertisement(
            placement=payload.placement,
            media_urls=payload.media_urls,
            media_type=payload.media_type,
            target_url=payload.target_url,
            start_date=payload.start_date,
            end_date=payload.end_date,
            is_active=payload.is_active,
            priority=payload.priority or "MEDIUM",
            cpm_rate=payload.cpm_rate or 0.0,
            cpc_rate=payload.cpc_rate or 0.0,
            impression_cap=payload.impression_cap,
            click_cap=payload.click_cap,
            billing_contact=payload.billing_contact,
            approval_status=payload.approval_status or "PENDING"
        )
        db.add(ad)
        await db.commit()
        await db.refresh(ad)
        logger.info("Created platform ad campaign %s (placement: %s)", ad.id, ad.placement)
        return ad

    @staticmethod
    async def list_platform_ads(db: AsyncSession) -> List[PlatformAdvertisement]:
        """List all platform-wide advertisements."""
        stmt = select(PlatformAdvertisement).order_by(PlatformAdvertisement.created_at.desc())
        res = await db.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def get_platform_ad(db: AsyncSession, ad_id: UUID) -> PlatformAdvertisement:
        """Retrieve a specific platform-wide advertisement."""
        stmt = select(PlatformAdvertisement).filter(PlatformAdvertisement.id == ad_id)
        res = await db.execute(stmt)
        ad = res.scalars().first()
        if not ad:
            raise HTTPException(status_code=404, detail="Platform advertisement not found")
        return ad

    @staticmethod
    async def update_platform_ad(
        db: AsyncSession, ad_id: UUID, payload: PlatformAdvertisementUpdate
    ) -> PlatformAdvertisement:
        """Update a platform-wide advertisement."""
        ad = await AdvertisementService.get_platform_ad(db, ad_id)

        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(ad, key, value)

        await db.commit()
        await db.refresh(ad)
        logger.info("Updated platform ad campaign %s", ad_id)
        return ad

    @staticmethod
    async def delete_platform_ad(db: AsyncSession, ad_id: UUID) -> dict:
        """Delete a platform-wide advertisement."""
        ad = await AdvertisementService.get_platform_ad(db, ad_id)
        await db.delete(ad)
        await db.commit()
        logger.info("Deleted platform ad campaign %s", ad_id)
        return {"message": "Platform advertisement deleted successfully"}

    # ═══════════════════════════════════════════════════════════════════════
    # TEMPLE ADVERTISEMENTS (TEMPLE MANAGER)
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    async def create_temple_ad(
        db: AsyncSession, temple_id: UUID, payload: TempleAdvertisementCreate
    ) -> TempleAdvertisement:
        """Create a new temple-specific advertisement."""
        ad = TempleAdvertisement(
            temple_id=temple_id,
            placement=payload.placement,
            media_urls=payload.media_urls,
            media_type=payload.media_type,
            target_url=payload.target_url,
            start_date=payload.start_date,
            end_date=payload.end_date,
            display_order=payload.display_order,
            is_active=payload.is_active,
        )
        db.add(ad)
        await db.commit()
        await db.refresh(ad)
        logger.info("Created temple ad campaign %s for temple %s", ad.id, temple_id)
        return ad

    @staticmethod
    async def list_temple_ads(db: AsyncSession, temple_id: UUID) -> List[TempleAdvertisement]:
        """List all advertisements for a specific temple."""
        stmt = (
            select(TempleAdvertisement)
            .filter(TempleAdvertisement.temple_id == temple_id)
            .order_by(TempleAdvertisement.display_order.asc(), TempleAdvertisement.created_at.desc())
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def get_temple_ad(
        db: AsyncSession, temple_id: UUID, ad_id: UUID
    ) -> TempleAdvertisement:
        """Retrieve a specific temple-specific advertisement."""
        stmt = select(TempleAdvertisement).filter(
            TempleAdvertisement.id == ad_id, TempleAdvertisement.temple_id == temple_id
        )
        res = await db.execute(stmt)
        ad = res.scalars().first()
        if not ad:
            raise HTTPException(status_code=404, detail="Temple advertisement not found")
        return ad

    @staticmethod
    async def update_temple_ad(
        db: AsyncSession, temple_id: UUID, ad_id: UUID, payload: TempleAdvertisementUpdate
    ) -> TempleAdvertisement:
        """Update a temple-specific advertisement."""
        ad = await AdvertisementService.get_temple_ad(db, temple_id, ad_id)

        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(ad, key, value)

        await db.commit()
        await db.refresh(ad)
        logger.info("Updated temple ad campaign %s for temple %s", ad_id, temple_id)
        return ad

    @staticmethod
    async def delete_temple_ad(db: AsyncSession, temple_id: UUID, ad_id: UUID) -> dict:
        """Delete a temple-specific advertisement."""
        ad = await AdvertisementService.get_temple_ad(db, temple_id, ad_id)
        await db.delete(ad)
        await db.commit()
        logger.info("Deleted temple ad campaign %s for temple %s", ad_id, temple_id)
        return {"message": "Temple advertisement deleted successfully"}
