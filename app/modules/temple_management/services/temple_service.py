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
        query = select(Temple).outerjoin(TempleProfile, Temple.id == TempleProfile.temple_id).filter(
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
            profile_result = await db.execute(
                select(TempleProfile).filter(TempleProfile.temple_id == temple.id)
            )
            profile = profile_result.scalars().first()

            items.append({
                "id": temple.id,
                "name": temple.name,
                "location": profile.location if profile else "",
                "district": profile.district if profile else "",
                "state": profile.state if profile else "",
                "image_url": profile.image_url if profile else "",
            })

        return items, total

    @staticmethod
    async def get_temple(db: AsyncSession, temple_id: str):
        try:
            tid = UUID(temple_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid temple ID")

        result = await db.execute(select(Temple).filter(
            Temple.id == tid,
            Temple.is_active == True,
            Temple.status.in_(["APPROVED", "ACTIVE", "active", "PENDING", "pending"])
        ))
        temple = result.scalars().first()
        if not temple:
            raise HTTPException(status_code=404, detail="Temple not found")

        profile_result = await db.execute(
            select(TempleProfile).filter(TempleProfile.temple_id == tid)
        )
        profile = profile_result.scalars().first()

        images_result = await db.execute(
            select(TempleImage).filter(TempleImage.temple_id == tid)
        )
        images = images_result.scalars().all()

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
            "images": [{"id": img.id, "image_url": img.image_url, "caption": img.caption or ""} for img in images],
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
        return result.scalars().all()
