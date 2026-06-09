import re
import logging
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from uuid import UUID
from typing import List, Optional
from datetime import datetime, timezone

from app.api.deps import get_db
from app.models.domain import Temple, TempleWebsiteSettingsLive, TempleAdvertisement, PlatformAdvertisement
from app.core.limiter import limiter
from app.modules.temple_management.services.recommendation_service import RecommendationService
from app.modules.temple_management.schemas.recommendation import PublicResolverPayload, PublicRecommendationResponse
from app.modules.temple_management.services.digital_experience_service import DigitalExperienceService
from app.modules.temple_management.schemas.digital_experience import (
    TempleWebsiteSettingsResponse,
    TempleAnnouncementResponse,
    TempleActivityResponse,
    TempleImageResponse,
    PublicBootstrapResponse,
    PublicActionSchema,
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
                    temple_id=img.temple_id,
                    image_url=img.image_url,
                    caption=img.caption or "",
                    category=img.category or "GALLERY",
                    created_at=img.created_at
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
    from datetime import timedelta, timezone, time
    IST = timezone(timedelta(hours=5, minutes=30))

    stmt = (
        select(Temple)
        .join(TempleWebsiteSettingsLive, Temple.id == TempleWebsiteSettingsLive.temple_id)
        .options(
            selectinload(Temple.profile),
            selectinload(Temple.website_settings_live),
            selectinload(Temple.images),
            selectinload(Temple.activities)
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
        
        # 1. Resolve hero image: HERO_DESKTOP image -> profile.image_url -> snapshot og_image -> None
        hero_image_url = None
        if temple.images:
            hero_desktop = next((img for img in temple.images if img.category == 'HERO_DESKTOP'), None)
            if hero_desktop:
                hero_image_url = hero_desktop.image_url

        if not hero_image_url and profile and profile.image_url:
            hero_image_url = profile.image_url

        if not hero_image_url and temple.website_settings_live and temple.website_settings_live.settings_snapshot:
            snap = temple.website_settings_live.settings_snapshot
            hero_image_url = snap.get("og_image_url") or snap.get("logo_url")

        # Fallback image resolution for backward compatibility
        image_url = hero_image_url

        # 2. Compute temple status based on IST
        opening_time = profile.opening_time if profile else None
        closing_time = profile.closing_time if profile else None
        
        temple_status = "Closed"
        if opening_time and closing_time:
            try:
                ist_now = datetime.now(IST)
                current_minutes = ist_now.hour * 60 + ist_now.minute
                
                def parse_to_minutes(t_str):
                    t_str = t_str.strip().upper()
                    am_pm_match = re.match(r"^(\d{1,2}):(\d{2})\s*(AM|PM)$", t_str)
                    if am_pm_match:
                        hours = int(am_pm_match.group(1))
                        minutes = int(am_pm_match.group(2))
                        period = am_pm_match.group(3)
                        if period == 'PM' and hours != 12:
                            hours += 12
                        if period == 'AM' and hours == 12:
                            hours = 0
                        return hours * 60 + minutes
                    match24 = re.match(r"^(\d{1,2}):(\d{2})", t_str)
                    if match24:
                        hours = int(match24.group(1))
                        minutes = int(match24.group(2))
                        return hours * 60 + minutes
                    return None

                open_mins = parse_to_minutes(opening_time)
                close_mins = parse_to_minutes(closing_time)
                if open_mins is not None and close_mins is not None:
                    if 0 < (open_mins - current_minutes) <= 30:
                        temple_status = "Opening Soon"
                    elif open_mins <= current_minutes < close_mins:
                        if (close_mins - current_minutes) <= 30:
                            temple_status = "Closing Soon"
                        else:
                            temple_status = "Open"
                    else:
                        temple_status = "Closed"
            except Exception:
                pass

        # 3. Resolve current activity
        current_activity = None
        active_acts = [a for a in temple.activities if a.is_active] if temple.activities else []
        ist_now = datetime.now(IST)
        today_date = ist_now.date()
        
        active_today = next((a for a in active_acts if a.status.value == "ACTIVE" and a.activity_date == today_date), None)
        if active_today:
            current_activity = f"{active_today.title} in Progress"
        else:
            upcoming_today = [a for a in active_acts if a.status.value == "UPCOMING" and a.activity_date == today_date]
            if upcoming_today:
                upcoming_today.sort(key=lambda x: x.start_time if x.start_time else time.min)
                next_act = upcoming_today[0]
                if next_act.start_time:
                    hr = next_act.start_time.hour
                    mn = next_act.start_time.minute
                    period = "PM" if hr >= 12 else "AM"
                    disphr = 12 if hr == 0 else (hr - 12 if hr > 12 else hr)
                    current_activity = f"{next_act.title} at {disphr}:{mn:02d} {period}"
                else:
                    current_activity = next_act.title

        # Serialize activities for client-side festival and upcoming badge processing
        activities_list = []
        for act in active_acts:
            activities_list.append({
                "id": str(act.id),
                "title": act.title,
                "activity_date": act.activity_date.isoformat(),
                "start_time": act.start_time.isoformat() if act.start_time else None,
                "end_time": act.end_time.isoformat() if act.end_time else None,
                "status": act.status.value,
                "is_active": act.is_active
            })

        items.append({
            "id": str(temple.id),
            "name": temple.name,
            "location": profile.location if profile else "",
            "district": profile.district if profile else "",
            "state": profile.state if profile else "",
            "image_url": image_url or "",
            "hero_image_url": hero_image_url or "",
            "slug": temple.domain,
            "opening_time": opening_time,
            "closing_time": closing_time,
            "temple_status": temple_status,
            "current_activity": current_activity,
            "activities": activities_list
        })
    return items


@router.get(
    "/{slug}/bootstrap",
    response_model=PublicBootstrapResponse,
    tags=["public-temple-portal"]
)
@limiter.limit("60/minute")
async def get_public_temple_bootstrap(
    slug: str,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve aggregated public configuration/bootstrap data for a temple by its slug (domain).
    """
    # 1. Strict Slug Regex Validation
    if not re.match(r"^[a-z0-9-]+$", slug):
        logger.warning(
            "Access attempt with invalid slug format rejected for bootstrap.",
            extra={"operation": "PUBLIC_BOOTSTRAP_SLUG_VALIDATION", "status": "FAILURE", "slug": slug}
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
            images.append({
                "id": str(img.id),
                "temple_id": str(img.temple_id),
                "image_url": img.image_url,
                "caption": img.caption or "",
                "category": img.category or "GALLERY",
                "created_at": img.created_at.isoformat() if img.created_at else None
            })

    profile = {
        "id": str(temple.id),
        "name": temple.name,
        "domain": temple.domain,
        "description": profile_db.description if profile_db else "",
        "history": profile_db.history if profile_db else "",
        "location": profile_db.location if profile_db else "",
        "district": profile_db.district if profile_db else "",
        "state": profile_db.state if profile_db else "",
        "country": profile_db.country if profile_db else "India",
        "contact_number": profile_db.contact_number if profile_db else "",
        "email": profile_db.email if profile_db else "",
        "opening_time": profile_db.opening_time if profile_db else "06:00",
        "closing_time": profile_db.closing_time if profile_db else "20:00",
        "live_stream_url": profile_db.live_stream_url if profile_db else "",
        "latitude": profile_db.latitude if profile_db else None,
        "longitude": profile_db.longitude if profile_db else None,
        "upi_id": profile_db.upi_id if profile_db else "",
        "image_url": profile_db.image_url if profile_db else "",
        "main_deity": profile_db.main_deity if profile_db else "",
        "deities": profile_db.deities if profile_db else [],
        "facebook_url": profile_db.facebook_url if profile_db else "",
        "instagram_url": profile_db.instagram_url if profile_db else "",
        "youtube_url": profile_db.youtube_url if profile_db else "",
        "twitter_url": profile_db.twitter_url if profile_db else "",
        "website_url": profile_db.website_url if profile_db else "",
        "festivals_description": profile_db.festivals_description if profile_db else "",
        "images": images
    }

    # 5. Extract settings and featureVisibility from the live snapshot
    live = temple.website_settings_live
    settings_snapshot = live.settings_snapshot
    
    # Feature toggle fallback strategy
    default_visibility = {
        "enablePoojaBooking": True,
        "enableOfferings": True,
        "enableStore": True,
        "enableHallBooking": True,
        "enableFollow": True,
        "enableTempleAds": True,
        "enablePlatformAds": True,
        "enableGallery": True,
        "enableActivities": True,
        "enableNoticeBoard": True,
        "enableAnnouncements": True
    }
    
    feature_visibility = dict(default_visibility)
    snapshot_visibility = settings_snapshot.get("featureVisibility")
    if snapshot_visibility:
        for k, v in snapshot_visibility.items():
            feature_visibility[k] = v

    settings = {
        "id": str(live.id),
        "temple_id": str(temple.id),
        "theme_name": settings_snapshot.get("theme_name") or "default",
        "primary_color": settings_snapshot.get("primary_color") or "#ff6600",
        "secondary_color": settings_snapshot.get("secondary_color") or "#ffcc00",
        "logo_url": settings_snapshot.get("logo_url"),
        "hero_layout": settings_snapshot.get("hero_layout") or "split",
        "section_order": settings_snapshot.get("section_order") or ["hero", "about", "deities", "announcements", "activities", "gallery", "offerings", "location"],
        "enable_mantras": settings_snapshot.get("enable_mantras") if settings_snapshot.get("enable_mantras") is not None else True,
        "enable_festivals": settings_snapshot.get("enable_festivals") if settings_snapshot.get("enable_festivals") is not None else True,
        "enable_donations": settings_snapshot.get("enable_donations") if settings_snapshot.get("enable_donations") is not None else True,
        "enable_hall_booking": settings_snapshot.get("enable_hall_booking") if settings_snapshot.get("enable_hall_booking") is not None else True,
        "enable_store": settings_snapshot.get("enable_store") if settings_snapshot.get("enable_store") is not None else True,
        "seo_keywords": settings_snapshot.get("seo_keywords"),
        "og_image_url": settings_snapshot.get("og_image_url"),
        "hero_title": settings_snapshot.get("hero_title"),
        "hero_subtitle": settings_snapshot.get("hero_subtitle"),
        "seo_description": settings_snapshot.get("seo_description"),
        "notice_board_content": settings_snapshot.get("notice_board_content"),
        "created_at": live.published_at.isoformat() if live.published_at else None,
        "updated_at": live.published_at.isoformat() if live.published_at else None
    }

    # 6. Fetch announcements & activities
    announcements_db = await DigitalExperienceService.list_announcements(
        db, temple.id, include_inactive=False
    )
    announcements = []
    if feature_visibility.get("enableAnnouncements"):
        for ann in announcements_db:
            announcements.append({
                "id": str(ann.id),
                "temple_id": str(ann.temple_id),
                "title": ann.title,
                "content": ann.content,
                "is_active": ann.is_active,
                "is_pinned": ann.is_pinned,
                "priority": ann.priority,
                "display_order": ann.display_order,
                "start_date": ann.start_date.isoformat() if ann.start_date else None,
                "expiry_date": ann.expiry_date.isoformat() if ann.expiry_date else None
            })

    # Fetch active activities
    activities_db = await DigitalExperienceService.list_activities(
        db, temple.id, include_inactive=False
    )
    activities = []
    if feature_visibility.get("enableActivities"):
        for act in activities_db:
            activities.append({
                "id": str(act.id),
                "temple_id": str(act.temple_id),
                "title": act.title,
                "description": act.description,
                "activity_date": act.activity_date.isoformat() if act.activity_date else None,
                "start_time": act.start_time.isoformat() if act.start_time else None,
                "end_time": act.end_time.isoformat() if act.end_time else None,
                "location": act.location,
                "is_active": act.is_active,
                "status": act.status,
                "livestream_url": act.livestream_url
            })

    # 7. Fetch active advertisements
    now = datetime.now(timezone.utc)
    advertisements = []
    
    # Only fetch if ads are enabled
    if feature_visibility.get("enableTempleAds") or feature_visibility.get("enablePlatformAds"):
        # We query active temple ads
        temple_ads_stmt = select(TempleAdvertisement).filter(
            TempleAdvertisement.temple_id == temple.id,
            TempleAdvertisement.is_active == True,
            TempleAdvertisement.start_date <= now,
            TempleAdvertisement.end_date >= now
        ).order_by(TempleAdvertisement.display_order.asc(), TempleAdvertisement.created_at.desc())
        
        temple_ads_res = await db.execute(temple_ads_stmt)
        temple_ads = temple_ads_res.scalars().all()
        
        # We query active platform ads
        platform_ads_stmt = select(PlatformAdvertisement).filter(
            PlatformAdvertisement.is_active == True,
            PlatformAdvertisement.start_date <= now,
            PlatformAdvertisement.end_date >= now
        ).order_by(PlatformAdvertisement.created_at.desc())
        
        platform_ads_res = await db.execute(platform_ads_stmt)
        platform_ads = platform_ads_res.scalars().all()
        
        if feature_visibility.get("enableTempleAds"):
            for ad in temple_ads:
                advertisements.append({
                    "id": str(ad.id),
                    "advertisement_type": "TEMPLE",
                    "placement": ad.placement,
                    "media_urls": ad.media_urls,
                    "target_url": ad.target_url,
                    "start_date": ad.start_date.isoformat() if ad.start_date else None,
                    "end_date": ad.end_date.isoformat() if ad.end_date else None,
                    "display_order": ad.display_order
                })
                
        if feature_visibility.get("enablePlatformAds"):
            for ad in platform_ads:
                advertisements.append({
                    "id": str(ad.id),
                    "advertisement_type": "PLATFORM",
                    "placement": ad.placement,
                    "media_urls": ad.media_urls,
                    "target_url": ad.target_url,
                    "start_date": ad.start_date.isoformat() if ad.start_date else None,
                    "end_date": ad.end_date.isoformat() if ad.end_date else None,
                    "display_order": 0
                })

    # 8. Dynamic actions mapping
    public_actions = []
    if feature_visibility.get("enablePoojaBooking"):
        public_actions.append(
            PublicActionSchema(
                name="Book Pooja",
                toggle="enablePoojaBooking",
                api=f"/api/v1/temples/{temple.id}/services"
            )
        )
    if feature_visibility.get("enableOfferings"):
        public_actions.append(
            PublicActionSchema(
                name="Submit Offering",
                toggle="enableOfferings",
                api="/api/v1/store/guest-booking"
            )
        )

    return PublicBootstrapResponse(
        version="2.0",
        generatedAt=datetime.now(timezone.utc),
        profile=profile,
        settings=settings,
        featureVisibility=feature_visibility,
        announcements=announcements,
        activities=activities,
        advertisements=advertisements,
        publicActions=public_actions
    )


@router.get(
    "/{slug}/recommendations",
    response_model=PublicResolverPayload,
    tags=["public-temple-portal"]
)
@limiter.limit("60/minute")
async def get_public_recommendations(
    slug: str,
    request: Request,
    service_id: Optional[UUID] = None,
    product_id: Optional[UUID] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Resolve active recommendations for a service or product.
    Target resolution: < 200ms
    """
    # 1. Slug Regex Validation
    if not re.match(r"^[a-z0-9-]+$", slug):
        raise HTTPException(status_code=400, detail="Invalid temple slug format")

    if not service_id and not product_id:
        raise HTTPException(status_code=400, detail="Either service_id or product_id must be provided")

    # 2. Fetch temple by slug
    result = await db.execute(
        select(Temple).filter(Temple.domain == slug, Temple.is_active == True, Temple.status == "APPROVED")
    )
    temple = result.scalars().first()
    if not temple:
        raise HTTPException(status_code=404, detail="Temple not found")

    # 3. Resolve
    recs = await RecommendationService.resolve_recommendations(
        db=db, temple_id=temple.id, service_id=service_id, product_id=product_id
    )

    # 4. Map to response structure
    mapped_recs = []
    for r in recs:
        rec_type = "SERVICE" if r.recommended_service_id else "PRODUCT"
        mapped_recs.append(
            PublicRecommendationResponse(
                id=r.id,
                recommendation_type=rec_type,
                display_order=r.display_order,
                service=r.recommended_service,
                product=r.recommended_product
            )
        )

    source_type = "SERVICE" if service_id else "PRODUCT"
    source_id = service_id if service_id else product_id

    return PublicResolverPayload(
        source_type=source_type,
        source_id=source_id,
        recommendations=mapped_recs
    )


# =============================================================================
# SPRINT 4 PUBLIC ADDITIONS — GLOBAL SETTINGS, OFFERINGS, & GUEST CHECKOUT
# =============================================================================

class PublicOfferingCreate(BaseModel):
    donor_name: str
    donor_email: Optional[str] = None
    donor_phone: Optional[str] = None
    donor_address: Optional[str] = None
    amount: float
    offering_type: str  # GENERAL, VAZHIPADU, DONATION, ANNADANAM
    notification_mode: Optional[str] = "EMAIL"
    notification_destination: Optional[str] = None
    offering_metadata: Optional[dict] = None


class GuestCheckoutItem(BaseModel):
    product_id: UUID
    quantity: float
    unit_price: float


class GuestCheckoutRequest(BaseModel):
    guest_name: str
    guest_phone: str
    guest_email: Optional[str] = None
    items: List[GuestCheckoutItem]


@router.get(
    "/global-settings/{key}",
    tags=["public-global-settings"]
)
async def get_public_global_setting(
    key: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Publicly get live global settings with caching.
    """
    from app.core.cache import GlobalConfigurationCache
    from app.modules.governance.models.governance_models import PlatformGlobalSetting
    
    if key not in ["global_website_builder_live", "global_website_builder_history"]:
        raise HTTPException(status_code=400, detail="Invalid global settings key requested")
        
    # Attempt to retrieve from cache
    cached_val = GlobalConfigurationCache.get(key)
    if cached_val is not None:
        return {"key": key, "value": cached_val}
        
    # Fetch from database
    result = await db.execute(
        select(PlatformGlobalSetting).filter(PlatformGlobalSetting.key == key)
    )
    setting = result.scalar_one_or_none()
    val = setting.value if setting else {}
    
    # Store in cache
    GlobalConfigurationCache.set(key, val)
    return {"key": key, "value": val}


@router.post(
    "/{slug}/offerings",
    status_code=201,
    tags=["public-offerings"]
)
async def public_create_offering(
    slug: str,
    body: PublicOfferingCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    Stages a public devotee offering and initiates payment with UPI QR code link.
    """
    from app.models.domain import Temple
    from app.modules.temple_management.models.offering import Offering
    from app.core.payments.providers import UPIQRAdapter
    from sqlalchemy import func
    
    # Fetch temple by slug
    temple_stmt = select(Temple).filter(Temple.domain == slug)
    temple_res = await db.execute(temple_stmt)
    temple = temple_res.scalar_one_or_none()
    if not temple:
        raise HTTPException(status_code=404, detail="Temple not found")
        
    if body.offering_type not in ("GENERAL", "VAZHIPADU", "DONATION", "ANNADANAM"):
        raise HTTPException(status_code=400, detail="Invalid offering type")
        
    # Generate offering number
    year = datetime.now(timezone.utc).year
    count_result = await db.execute(
        select(func.count(Offering.id)).filter(
            Offering.temple_id == temple.id,
            func.extract("year", Offering.created_at) == year,
        )
    )
    seq = (count_result.scalar() or 0) + 1
    offering_number = f"OFF-{year}-{seq:06d}"
    
    # Create offering record (staged in CREATED status)
    offering = Offering(
        temple_id=temple.id,
        offering_number=offering_number,
        donor_name=body.donor_name,
        donor_email=body.donor_email,
        donor_phone=body.donor_phone,
        donor_address=body.donor_address,
        offering_type=body.offering_type,
        notification_mode=body.notification_mode,
        notification_destination=body.notification_destination,
        offering_metadata=body.offering_metadata or {},
        total_amount=body.amount,
        paid_amount=0.0,
        balance_amount=body.amount,
        payment_status="CREATED",
        booking_mode="Online",
        offering_status="CONFIRMED"
    )
    db.add(offering)
    await db.flush()
    
    # Create Payment record
    from app.models.domain import Payment
    from app.modules.billing.models.billing_models import PaymentStatus
    
    payment = Payment(
        temple_id=temple.id,
        reference_id=offering.id,
        amount=body.amount,
        provider_ref="mock_gateway_ref",
        status=PaymentStatus.PENDING
    )
    db.add(payment)
    await db.flush()
    
    # Call UPI QR adapter to get the payment deep link reference
    adapter = UPIQRAdapter()
    payment_res = await adapter.create_payment(amount=body.amount, reference_id=offering.id)
    
    await db.commit()
    
    return {
        "status": "success",
        "offering_id": str(offering.id),
        "offering_number": offering_number,
        "payment": payment_res
    }


@router.post(
    "/{slug}/store/guest-checkout",
    status_code=201,
    tags=["public-store"]
)
async def guest_checkout(
    slug: str,
    body: GuestCheckoutRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Guest checkout for store items, locking stock row with with_for_update() to prevent double-selling.
    """
    from app.models.domain import Temple, Payment
    from app.modules.inventory.models.inventory_models import StoreSalesOrder, StoreSalesOrderItem, StoreStock, InventoryStockLedger, InventoryMovementType
    from app.models.domain import StoreProduct
    from app.modules.billing.models.billing_models import PaymentStatus
    from sqlalchemy import func
    import uuid
    
    # Fetch temple by slug
    temple_stmt = select(Temple).filter(Temple.domain == slug)
    temple_res = await db.execute(temple_stmt)
    temple = temple_res.scalar_one_or_none()
    if not temple:
        raise HTTPException(status_code=404, detail="Temple not found")
        
    if not body.items:
        raise HTTPException(status_code=400, detail="Cart items cannot be empty")
        
    store_total = sum(i.unit_price * i.quantity for i in body.items)
    checkout_id = uuid.uuid4()
    
    # Generate sequential order number
    year = datetime.now(timezone.utc).year
    count_result = await db.execute(
        select(func.count(StoreSalesOrder.id)).filter(
            StoreSalesOrder.temple_id == temple.id,
        )
    )
    seq = (count_result.scalar() or 0) + 1
    order_number = f"ORD-{year}-{seq:06d}"
    
    # Create StoreSalesOrder
    order = StoreSalesOrder(
        id=checkout_id,
        temple_id=temple.id,
        order_number=order_number,
        customer_name=body.guest_name,
        customer_phone=body.guest_phone,
        total_amount=store_total,
        payment_mode="UPI",
        status="Completed",
        payment_status="PENDING",
        idempotency_key=str(checkout_id)
    )
    db.add(order)
    await db.flush()
    
    # Deduct stock and log movements
    for item in body.items:
        # Lock stock row using with_for_update()
        stock_stmt = select(StoreStock).filter(
            StoreStock.product_id == item.product_id,
            StoreStock.temple_id == temple.id
        ).with_for_update()
        stock_res = await db.execute(stock_stmt)
        stock = stock_res.scalar_one_or_none()
        
        if not stock or stock.quantity < item.quantity:
            prod_stmt = select(StoreProduct).filter(StoreProduct.id == item.product_id)
            prod_res = await db.execute(prod_stmt)
            prod = prod_res.scalar_one_or_none()
            prod_name = prod.name if prod else str(item.product_id)
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for product '{prod_name}'. Requested: {item.quantity}, Available: {stock.quantity if stock else 0.0}"
            )
            
        before_qty = stock.quantity
        after_qty = before_qty - item.quantity
        stock.quantity = after_qty
        
        # Fetch product name
        prod_stmt = select(StoreProduct).filter(StoreProduct.id == item.product_id)
        prod_res = await db.execute(prod_stmt)
        prod = prod_res.scalar_one_or_none()
        prod_name = prod.name if prod else "Store Product"
        
        ledger = InventoryStockLedger(
            temple_id=temple.id,
            domain_type="STORE",
            store_product_id=item.product_id,
            item_name=prod_name,
            location_id=stock.location_id,
            movement_type=InventoryMovementType.SALE,
            quantity_change=-float(item.quantity),
            before_stock=before_qty,
            after_stock=after_qty,
            reference_type="SALE",
            reference_id=str(order.id),
            remarks=f"Guest checkout sale for order {order_number}"
        )
        db.add(ledger)
        
        # Create order item
        order_item = StoreSalesOrderItem(
            order_id=order.id,
            product_id=item.product_id,
            quantity=float(item.quantity),
            unit_price=item.unit_price,
            total_price=item.unit_price * item.quantity
        )
        db.add(order_item)
        
    # Create Payment record
    payment = Payment(
        temple_id=temple.id,
        reference_id=checkout_id,
        amount=store_total,
        provider_ref="mock_gateway_ref",
        status=PaymentStatus.PENDING
    )
    db.add(payment)
    
    await db.commit()
    
    return {
        "message": "Guest checkout successful, payment pending",
        "order_id": str(order.id),
        "order_number": order_number,
        "payment_id": str(payment.id),
        "total_amount": round(store_total, 2),
        "items_count": len(body.items)
    }
