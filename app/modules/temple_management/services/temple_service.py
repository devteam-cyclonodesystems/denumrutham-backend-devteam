"""Temple Service — Public temple listing and profile retrieval."""
from uuid import UUID
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from fastapi import HTTPException

from app.models.domain import Temple, TempleProfile, TempleImage, TempleService as TempleServiceModel


class TempleService:

    @staticmethod
    async def list_temples(db: AsyncSession, skip: int = 0, limit: int = 50, search: Optional[str] = None):
        from sqlalchemy.orm import selectinload
        query = select(Temple).options(selectinload(Temple.profile)).filter(
            Temple.is_active == True,
            Temple.status.in_(["APPROVED", "ACTIVE", "active"])
        )

        if search:
            query = query.filter(Temple.name.ilike(f"%{search}%"))

        count_q = select(func.count()).select_from(Temple).filter(
            Temple.is_active == True,
            Temple.status.in_(["APPROVED", "ACTIVE", "active"])
        )
        if search:
            count_q = count_q.filter(Temple.name.ilike(f"%{search}%"))
        total_result = await db.execute(count_q)
        total = total_result.scalar() or 0

        query = query.offset(skip).limit(limit)
        result = await db.execute(query)
        temples_raw = result.scalars().all()

        items = []
        for temple in temples_raw:
            profile = temple.profile

            items.append({
                "id": temple.id,
                "name": temple.name,
                "domain": temple.domain,
                "location": profile.location if profile else "",
                "district": profile.district if profile else "",
                "state": profile.state if profile else "",
                "image_url": profile.image_url if profile else "",
            })

        return items, total

    @staticmethod
    async def get_temple(db: AsyncSession, temple_id: str):
        from sqlalchemy.orm import selectinload
        try:
            tid = UUID(temple_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid temple ID")

        result = await db.execute(
            select(Temple)
            .options(
                selectinload(Temple.profile),
                selectinload(Temple.images)
            )
            .filter(
                Temple.id == tid,
                Temple.is_active == True,
                Temple.status.in_(["APPROVED", "ACTIVE", "active", "PENDING", "pending"])
            )
        )
        temple = result.scalars().first()
        if not temple:
            raise HTTPException(status_code=404, detail="Temple not found")

        profile = temple.profile
        images = temple.images or []

        # Fetch active deities from DeityMaster table
        from app.models.archana import DeityMaster, DeityStatus
        deity_stmt = select(DeityMaster.deity_name).filter(
            DeityMaster.tenant_id == tid,
            DeityMaster.status == DeityStatus.ACTIVE
        )
        deity_res = await db.execute(deity_stmt)
        active_deities = [row[0] for row in deity_res.all()]

        profile_deities = profile.deities if profile else []
        deities_list = active_deities if active_deities else profile_deities

        return {
            "id": temple.id,
            "name": temple.name,
            "domain": temple.domain,
            "description": profile.description if profile else "",
            "history": profile.history if profile else "",
            "location": profile.location if profile else "",
            "district": profile.district if profile else "",
            "state": profile.state if profile else "",
            "country": profile.country if profile else "India",
            "contact_number": profile.contact_number if profile else "",
            "email": profile.email if profile else "",
            "opening_time": profile.opening_time if profile else "06:00",
            "closing_time": profile.closing_time if profile else "20:00",
            "live_stream_url": profile.live_stream_url if profile else "",
            "latitude": profile.latitude if profile else None,
            "longitude": profile.longitude if profile else None,
            "upi_id": profile.upi_id if profile else "",
            "image_url": profile.image_url if profile else "",
            "main_deity": profile.main_deity if profile else "",
            "deities": deities_list,
            "facebook_url": profile.facebook_url if profile else "",
            "instagram_url": profile.instagram_url if profile else "",
            "youtube_url": profile.youtube_url if profile else "",
            "twitter_url": profile.twitter_url if profile else "",
            "website_url": profile.website_url if profile else "",
            "festivals_description": profile.festivals_description if profile else "",
            "images": [{"id": img.id, "image_url": img.image_url, "caption": img.caption or "", "category": img.category, "is_visible": getattr(img, 'is_visible', True)} for img in TempleImage.filter_visible(images)],
        }

    @staticmethod
    async def get_temple_services(db: AsyncSession, temple_id: str):
        try:
            tid = UUID(temple_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid temple ID")

        result = await db.execute(
            select(TempleServiceModel).filter(
                TempleServiceModel.temple_id == tid,
                TempleServiceModel.active == True
            )
        )
        services = result.scalars().all()
        if not services:
            from app.models.archana import ArchanaCatalog
            from app.modules.bookings.models.archana import CatalogStatus
            from app.modules.bookings.models.booking_models import ServiceType
            
            catalog_result = await db.execute(
                select(ArchanaCatalog).filter(
                    ArchanaCatalog.temple_id == tid,
                    ArchanaCatalog.is_active == True,
                    ArchanaCatalog.status == CatalogStatus.APPROVED
                )
            )
            catalog_items = catalog_result.scalars().all()
            fallback_services = []
            for item in catalog_items:
                srv = TempleServiceModel(
                    id=item.id,
                    temple_id=item.temple_id,
                    service_name=item.name,
                    service_type=ServiceType.ARCHANA,
                    price=item.price,
                    description=item.description or item.remarks or "",
                    active=item.is_active
                )
                fallback_services.append(srv)
            return fallback_services
        return services

