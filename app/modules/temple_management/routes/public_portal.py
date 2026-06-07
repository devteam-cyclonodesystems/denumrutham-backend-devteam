import re
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from uuid import UUID
from typing import List, Optional

from app.api.deps import get_db
from app.models.domain import Temple, TempleWebsiteSettingsLive
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

    # 2. Optimized fetch of temple with profile, images, and live website settings preloaded
    result = await db.execute(
        select(Temple)
        .options(
            selectinload(Temple.profile),
            selectinload(Temple.images),
            selectinload(Temple.website_settings_live)
        )
        .filter(Temple.domain == slug, Temple.is_active == True, Temple.status == "APPROVED")
    )
    temple = result.scalars().first()
    if not temple:
        raise HTTPException(status_code=404, detail="Temple not found")

    # 3. Raise 404 if website is not published
    if not temple.website_settings_live:
        raise HTTPException(status_code=404, detail="Temple website is not published")

    # 4. Direct Mapping of Profile & Images
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

    # 5. Load settings from the live snapshot contract
    live = temple.website_settings_live
    settings_snapshot = live.settings_snapshot
    try:
        settings = TempleWebsiteSettingsResponse(
            id=live.id,
            temple_id=temple.id,
            theme_name=settings_snapshot.get("theme_name") or "default",
            primary_color=settings_snapshot.get("primary_color") or "#ff6600",
            secondary_color=settings_snapshot.get("secondary_color") or "#ffcc00",
            logo_url=settings_snapshot.get("logo_url"),
            hero_layout=settings_snapshot.get("hero_layout") or "split",
            section_order=settings_snapshot.get("section_order") or ["hero", "about", "deities", "announcements", "activities", "gallery", "offerings", "location"],
            enable_mantras=settings_snapshot.get("enable_mantras") if settings_snapshot.get("enable_mantras") is not None else True,
            enable_festivals=settings_snapshot.get("enable_festivals") if settings_snapshot.get("enable_festivals") is not None else True,
            enable_donations=settings_snapshot.get("enable_donations") if settings_snapshot.get("enable_donations") is not None else True,
            enable_hall_booking=settings_snapshot.get("enable_hall_booking") if settings_snapshot.get("enable_hall_booking") is not None else True,
            enable_store=settings_snapshot.get("enable_store") if settings_snapshot.get("enable_store") is not None else True,
            seo_keywords=settings_snapshot.get("seo_keywords"),
            og_image_url=settings_snapshot.get("og_image_url"),
            hero_title=settings_snapshot.get("hero_title"),
            hero_subtitle=settings_snapshot.get("hero_subtitle"),
            seo_description=settings_snapshot.get("seo_description"),
            notice_board_content=settings_snapshot.get("notice_board_content"),
            created_at=live.published_at,
            updated_at=live.published_at
        )
    except Exception as e:
        logger.error(f"Failed to validate live snapshot for temple {temple.id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Invalid website settings snapshot configuration")

    # 6. Fetch announcements & activities
    announcements = await DigitalExperienceService.list_announcements(
        db, temple.id, include_inactive=False
    )

    # 7. Fetch active activities
    activities = await DigitalExperienceService.list_activities(
        db, temple.id, include_inactive=False
    )

    return PublicPortalResponse(
        profile=profile,
        settings=settings,
        announcements=announcements,
        activities=activities
    )


@router.get(
    "",
    response_model=List[dict],
    tags=["public-temple-portal"]
)
async def list_public_temples(
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve a list of all published temples.
    Uses JOIN with TempleWebsiteSettingsLive and preloads profiles/snapshots to prevent N+1 queries.
    """
    stmt = (
        select(Temple)
        .join(TempleWebsiteSettingsLive, Temple.id == TempleWebsiteSettingsLive.temple_id)
        .options(
            selectinload(Temple.profile),
            selectinload(Temple.website_settings_live)
        )
        .filter(Temple.is_active == True, Temple.status == "APPROVED")
    )
    if search:
        stmt = stmt.filter(Temple.name.ilike(f"%{search}%"))

    result = await db.execute(stmt)
    temples = result.scalars().all()

    items = []
    for temple in temples:
        profile = temple.profile
        
        # Fallback image resolution: profile image -> snapshot og_image_url -> snapshot logo_url -> None
        image_url = None
        if profile and profile.image_url:
            image_url = profile.image_url
        elif temple.website_settings_live and temple.website_settings_live.settings_snapshot:
            snap = temple.website_settings_live.settings_snapshot
            image_url = snap.get("og_image_url") or snap.get("logo_url")

        items.append({
            "id": str(temple.id),
            "name": temple.name,
            "location": profile.location if profile else "",
            "district": profile.district if profile else "",
            "state": profile.state if profile else "",
            "image_url": image_url or "",
            "slug": temple.domain
        })
    return items
