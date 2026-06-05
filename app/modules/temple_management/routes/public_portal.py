import re
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from uuid import UUID
from typing import List

from app.api.deps import get_db
from app.models.domain import Temple
from app.core.limiter import limiter
from app.modules.temple_management.services.digital_experience_service import DigitalExperienceService
from app.modules.temple_management.schemas.digital_experience import (
    TempleWebsiteSettingsResponse,
    TempleAnnouncementResponse,
    TempleActivityResponse,
    TempleImageResponse,
)
from app.schemas.devotee_portal import TempleProfileResponse
from pydantic import BaseModel

logger = logging.getLogger("tms.security")

router = APIRouter()


class PublicPortalResponse(BaseModel):
    profile: TempleProfileResponse
    settings: TempleWebsiteSettingsResponse
    announcements: List[TempleAnnouncementResponse]
    activities: List[TempleActivityResponse]


@router.get(
    "/{slug}/portal",
    response_model=PublicPortalResponse,
    tags=["public-temple-portal"]
)
@limiter.limit("30/minute")
async def get_public_temple_portal(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve consolidated public data for a temple by its slug (domain).
    Includes profile, website settings, active announcements, and active activities.
    """
    # 1. Strict Slug Regex Validation
    if not re.match(r"^[a-z0-9-]+$", slug):
        logger.warning(
            "Access attempt with invalid slug format rejected.",
            extra={"operation": "PUBLIC_PORTAL_SLUG_VALIDATION", "status": "FAILURE", "slug": slug}
        )
        raise HTTPException(status_code=400, detail="Invalid temple slug format")

    # 2. Optimized fetch of temple with profile, images, and website_settings preloaded
    result = await db.execute(
        select(Temple)
        .options(
            selectinload(Temple.profile),
            selectinload(Temple.images),
            selectinload(Temple.website_settings)
        )
        .filter(Temple.domain == slug, Temple.is_active == True)
    )
    temple = result.scalars().first()
    if not temple:
        raise HTTPException(status_code=404, detail="Temple not found")

    # 3. Direct Mapping of Profile & Images
    profile_db = temple.profile
    images = []
    if temple.images:
        for img in temple.images:
            images.append(
                TempleImageResponse(
                    id=img.id,
                    image_url=img.image_url,
                    caption=img.caption or "",
                    category=img.category or "GALLERY"
                )
            )

    profile = TempleProfileResponse(
        id=temple.id,
        name=temple.name,
        domain=temple.domain,
        description=profile_db.description if profile_db else "",
        history=profile_db.history if profile_db else "",
        location=profile_db.location if profile_db else "",
        district=profile_db.district if profile_db else "",
        state=profile_db.state if profile_db else "",
        country=profile_db.country if profile_db else "India",
        contact_number=profile_db.contact_number if profile_db else "",
        email=profile_db.email if profile_db else "",
        opening_time=profile_db.opening_time if profile_db else "06:00",
        closing_time=profile_db.closing_time if profile_db else "20:00",
        live_stream_url=profile_db.live_stream_url if profile_db else "",
        latitude=profile_db.latitude if profile_db else None,
        longitude=profile_db.longitude if profile_db else None,
        upi_id=profile_db.upi_id if profile_db else "",
        image_url=profile_db.image_url if profile_db else "",
        main_deity=profile_db.main_deity if profile_db else "",
        deities=profile_db.deities if profile_db else [],
        facebook_url=profile_db.facebook_url if profile_db else "",
        instagram_url=profile_db.instagram_url if profile_db else "",
        youtube_url=profile_db.youtube_url if profile_db else "",
        twitter_url=profile_db.twitter_url if profile_db else "",
        website_url=profile_db.website_url if profile_db else "",
        festivals_description=profile_db.festivals_description if profile_db else "",
        images=images
    )

    # 4. Get/Load website settings without redundant queries
    settings = temple.website_settings
    if not settings:
        settings = await DigitalExperienceService.get_or_create_settings(db, temple.id)

    # 5. Fetch announcements & activities (indexes are queried, optimized via composite keys)
    announcements = await DigitalExperienceService.list_announcements(
        db, temple.id, include_inactive=False
    )

    # 6. Fetch active activities
    activities = await DigitalExperienceService.list_activities(
        db, temple.id, include_inactive=False
    )

    return PublicPortalResponse(
        profile=profile,
        settings=settings,
        announcements=announcements,
        activities=activities
    )
