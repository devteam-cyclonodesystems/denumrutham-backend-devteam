import re
import os
import logging
import sqlalchemy as sa
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload, joinedload
from uuid import UUID
from typing import List, Optional
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageOps

from app.api.deps import get_db, get_current_user, get_current_user_optional
from app.schemas.domain import TokenData
from app.models.domain import (
    Temple, TempleWebsiteSettingsLive, TempleAdvertisement, PlatformAdvertisement,
    StateMaster, DistrictMaster, TempleSearchIndex
)
from app.modules.temple_management.models.temple_models import TempleImage, TempleProfile, TempleFestival, TempleFollower
from app.modules.inventory.schemas.store import StoreProductResponse, AuctionListingResponse
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
from app.modules.temple_management.services.status_engine import (
    IST,
    resolve_full_temple_status,
    resolve_current_or_next_activity,
    resolve_upcoming_festival
)

logger = logging.getLogger("tms.security")

router = APIRouter()
directory_router = APIRouter()
public_router = APIRouter()


def resolve_temple_image(temple: Temple) -> str:
    """
    Resolves the hero/primary image for a temple based on the priority:
    1. Published Hero Image (from live website settings snapshot)
    2. Hero Category Image (HERO_DESKTOP in temple.images)
    3. Directory Image (profile.image_url)
    4. Platform Default Image (/static/default-temple.jpg)
    """
    if temple.website_settings_live and temple.website_settings_live.settings_snapshot:
        logo_url = temple.website_settings_live.settings_snapshot.get("logo_url")
        if logo_url:
            return logo_url
            
    if temple.images:
        hero_desktop = next((img for img in temple.images if img.category == 'HERO_DESKTOP'), None)
        if hero_desktop:
            return hero_desktop.image_url

    if temple.profile and temple.profile.image_url:
        return temple.profile.image_url

    return "/static/default-temple.jpg"


def get_image_variants(image_url: str) -> dict:
    if not image_url:
        image_url = "/static/default-temple.jpg"
        
    if image_url.startswith("http://") or image_url.startswith("https://"):
        return {
            "thumbnail": image_url,
            "card": image_url,
            "hero": image_url
        }
    return {
        "thumbnail": f"/api/v1/public/images/transform?path={image_url}&variant=thumbnail",
        "card": f"/api/v1/public/images/transform?path={image_url}&variant=card",
        "hero": f"/api/v1/public/images/transform?path={image_url}&variant=hero"
    }


async def resolve_claim_status(db: AsyncSession, temple: Temple, claims_map: dict = None) -> str:
    """
    Resolves claim status based on verification levels:
    - Level 0: UNCLAIMED (if no PENDING claim request)
    - Level 1: CLAIM_PENDING (if PENDING claim request exists)
    - Level 2: CLAIMED
    - Level 3: OFFICIAL
    """
    if temple.verification_level == 3:
        return "OFFICIAL"
    if temple.management_mode in ("SELF_MANAGED", "GOVERNED"):
        return "CLAIMED"
    elif temple.verification_level == 2:
        return "CLAIMED"
        
    if claims_map is not None:
        if claims_map.get(temple.id):
            if temple.verification_level < 1:
                temple.verification_level = 1
            return "CLAIM_PENDING"
        if temple.verification_level == 1:
            return "CLAIM_PENDING"
        return "UNCLAIMED"
        
    from app.modules.governance.models.governance_models import TempleClaimRequest
    stmt = select(TempleClaimRequest).filter(
        TempleClaimRequest.temple_id == temple.id,
        TempleClaimRequest.status == "PENDING"
    )
    res = await db.execute(stmt)
    pending_claim = res.scalars().first()
    if pending_claim:
        if temple.verification_level < 1:
            temple.verification_level = 1
        return "CLAIM_PENDING"
        
    if temple.verification_level == 1:
        return "CLAIM_PENDING"
        
    return "UNCLAIMED"


@public_router.get("/images/transform", tags=["public-images"])
async def transform_image(
    path: str,
    variant: str = "card"
):
    """
    Transforms and resizes an image on the fly based on the variant requested,
    caching the result in the static/cache folder.
    Variants:
      - thumbnail: 150x150
      - card: 400x250
      - hero: 1200x500
    """
    sanitized_path = path.lstrip("/")
    if ".." in sanitized_path or sanitized_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid image path")

    if sanitized_path.startswith("http://") or sanitized_path.startswith("https://"):
        raise HTTPException(status_code=400, detail="Cannot transform external URLs")

    source_file = Path(sanitized_path)
    if not source_file.exists():
        source_file = Path("static/default-temple.jpg")
        if not source_file.exists():
            # Create a simple placeholder image dynamically
            try:
                sizes = {
                    "thumbnail": (150, 150),
                    "card": (400, 250),
                    "hero": (1200, 500)
                }
                target_size = sizes.get(variant, (400, 250))
                # Create directories
                os.makedirs("static", exist_ok=True)
                img = Image.new("RGB", target_size, color=(24, 18, 6))
                img.save("static/default-temple.jpg", format="JPEG")
                source_file = Path("static/default-temple.jpg")
            except Exception:
                raise HTTPException(status_code=404, detail="Image not found")

    sizes = {
        "thumbnail": (150, 150),
        "card": (400, 250),
        "hero": (1200, 500)
    }
    
    if variant not in sizes:
        variant = "card"
        
    target_size = sizes[variant]
    
    cache_dir = Path("static/cache") / variant
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    cached_file = cache_dir / source_file.name
    
    if cached_file.exists() and cached_file.stat().st_mtime >= source_file.stat().st_mtime:
        return FileResponse(str(cached_file))
        
    try:
        with Image.open(source_file) as img:
            resized_img = ImageOps.fit(img, target_size, Image.Resampling.LANCZOS)
            img_format = img.format if img.format else "JPEG"
            resized_img.save(cached_file, format=img_format, quality=85)
            
        return FileResponse(str(cached_file))
    except Exception as e:
        logger.error(f"Image transformation failed for {path} ({variant}): {str(e)}")
        return FileResponse(str(source_file))


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
        .filter(Temple.domain == slug, Temple.is_active == True, Temple.status.in_(["APPROVED", "MERGED"]))
    )
    temple = result.scalars().first()
    if not temple:
        raise HTTPException(status_code=404, detail="Temple not found")

    if temple.status == "MERGED" and temple.merged_temple_id:
        dest_res = await db.execute(select(Temple.domain).filter(Temple.id == temple.merged_temple_id))
        dest_domain = dest_res.scalars().first()
        if dest_domain:
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=str(request.url).replace(temple.domain, dest_domain, 1), status_code=301)

    if temple.management_mode != "DIRECTORY_ONLY" and not temple.website_settings_live:
        raise HTTPException(status_code=404, detail="Temple website is not published")


    # 3. Direct Mapping of Profile & Images
    profile_db = temple.profile
    
    # Fetch active deities from DeityMaster table
    from app.models.archana import DeityMaster, DeityStatus
    deity_stmt = select(DeityMaster.deity_name).filter(
        DeityMaster.tenant_id == temple.id,
        DeityMaster.status == DeityStatus.ACTIVE
    )
    deity_res = await db.execute(deity_stmt)
    active_deities = [row[0] for row in deity_res.all()]
    profile_deities = profile_db.deities if profile_db else []
    deities_list = active_deities if active_deities else profile_deities

    images = []
    if temple.images:
        for img in temple.images:
            if img.category in ("HERO_DESKTOP", "HERO_MOBILE") or getattr(img, 'is_visible', True) is not False:
                images.append(
                    TempleImageResponse(
                        id=img.id,
                        temple_id=img.temple_id,
                        image_url=img.image_url,
                        caption=img.caption or "",
                        category=img.category or "GALLERY",
                        is_visible=getattr(img, 'is_visible', True),
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
        deities=deities_list,
        facebook_url=profile_db.facebook_url if profile_db else "",
        instagram_url=profile_db.instagram_url if profile_db else "",
        youtube_url=profile_db.youtube_url if profile_db else "",
        twitter_url=profile_db.twitter_url if profile_db else "",
        website_url=profile_db.website_url if profile_db else "",
        festivals_description=profile_db.festivals_description if profile_db else "",
        images=images
    )

    # 4. Load settings from the live snapshot contract or construct default
    live = temple.website_settings_live
    if live:
        settings_snapshot = live.settings_snapshot
        published_at = live.published_at
        settings_id = live.id
    else:
        settings_snapshot = {
            "theme_name": "default",
            "primary_color": "#ff6600",
            "secondary_color": "#ffcc00",
            "logo_url": None,
            "hero_layout": "split",
            "section_order": ["hero", "about", "timings", "announcements", "activities", "gallery", "offerings", "location"],
            "enable_mantras": True,
            "enable_festivals": True,
            "enable_donations": True,
            "enable_hall_booking": True,
            "enable_store": True,
            "seo_keywords": None,
            "og_image_url": None,
            "hero_title": temple.name,
            "hero_subtitle": temple.location,
            "seo_description": temple.description,
            "notice_board_content": None,
            "location_settings": {
                "google_maps_url": getattr(profile_db, 'google_maps_url', None) if profile_db else None,
                "latitude": profile_db.latitude if profile_db else None,
                "longitude": profile_db.longitude if profile_db else None,
                "location_label": getattr(profile_db, 'map_display_label', None) if profile_db else "📍 Temple Location"
            } if profile_db else {},
            "timings_settings": [],
            "daily_activities_settings": []
        }
        published_at = temple.created_at
        settings_id = temple.id

    try:
        settings = TempleWebsiteSettingsResponse(
            id=settings_id,
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
            location_settings=settings_snapshot.get("location_settings"),
            timings_settings=settings_snapshot.get("timings_settings"),
            daily_activities_settings=settings_snapshot.get("daily_activities_settings"),
            created_at=published_at,
            updated_at=published_at
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
    state: Optional[str] = None,
    district: Optional[str] = None,
    page: int = 1,
    limit: int = 10,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve a list of all published temples.
    Supports state, district, search filters, alphabetical ordering, and pagination.
    """
    stmt = (
        select(Temple)
        .outerjoin(TempleWebsiteSettingsLive, Temple.id == TempleWebsiteSettingsLive.temple_id)
        .outerjoin(TempleProfile, Temple.id == TempleProfile.temple_id)
        .options(
            selectinload(Temple.profile),
            selectinload(Temple.website_settings_live),
            selectinload(Temple.images),
            selectinload(Temple.activities),
            selectinload(Temple.festivals)
        )
        .filter(
            Temple.is_active == True,
            Temple.status == "APPROVED",
            Temple.directory_status == "ACTIVE"
        )
        .filter(
            sa.or_(
                Temple.management_mode == "DIRECTORY_ONLY",
                TempleWebsiteSettingsLive.id != None
            )
        )
    )
    if search:
        from sqlalchemy import or_
        search_filter = or_(
            Temple.name.ilike(f"%{search}%"),
            TempleProfile.main_deity.ilike(f"%{search}%"),
            TempleProfile.district.ilike(f"%{search}%"),
            TempleProfile.state.ilike(f"%{search}%"),
            Temple.festivals.any(TempleFestival.name.ilike(f"%{search}%")),
            Temple.festivals.any(TempleFestival.description.ilike(f"%{search}%"))
        )
        stmt = stmt.filter(search_filter)

    if state:
        stmt = stmt.filter(TempleProfile.state.ilike(state))
    if district:
        stmt = stmt.filter(TempleProfile.district.ilike(district))

    # Order alphabetically by name
    stmt = stmt.order_by(Temple.name.asc())

    # Pagination
    offset = (page - 1) * limit
    stmt = stmt.limit(limit).offset(offset)

    result = await db.execute(stmt)
    temples = result.scalars().all()

    # Bulk fetch claims for these temples
    temple_ids = [t.id for t in temples if t.id]
    claims_map = {}
    if temple_ids:
        from app.modules.governance.models.governance_models import TempleClaimRequest
        claim_stmt = select(TempleClaimRequest.temple_id).filter(TempleClaimRequest.temple_id.in_(temple_ids), TempleClaimRequest.status == "PENDING")
        claim_res = await db.execute(claim_stmt)
        for row in claim_res.all():
            claims_map[row[0]] = True

    items = []
    for temple in temples:
        profile = temple.profile
        
        # 1. Resolve image and Pillow variants using helpers
        resolved_img = resolve_temple_image(temple)
        variants = get_image_variants(resolved_img)

        # 2. Resolve timings, activities, and festivals using the status engine
        timings_settings = None
        activities_settings = None
        if temple.website_settings_live and temple.website_settings_live.settings_snapshot:
            snap = temple.website_settings_live.settings_snapshot
            timings_settings = snap.get("timings_settings")
            activities_settings = snap.get("daily_activities_settings")

        ist_now = datetime.now(IST)
        today_date = ist_now.date()
        current_minutes = ist_now.hour * 60 + ist_now.minute

        legacy_op = profile.opening_time if profile else None
        legacy_cl = profile.closing_time if profile else None

        status_res = resolve_full_temple_status(
            timings_settings, legacy_op, legacy_cl, today_date, current_minutes
        )

        temple_status = f"{status_res['dot']} {status_res['status']}"
        
        is_open = status_res["status"] in ["Open", "Closing Soon"]
        activity_str = resolve_current_or_next_activity(
            activities_settings, today_date, current_minutes, is_open
        )
        if activity_str:
            current_activity = f"{temple_status} | {activity_str}"
        else:
            current_activity = status_res["label"]

        # 3. Resolve upcoming festival badge
        upcoming_festival = resolve_upcoming_festival(
            temple.festivals, today_date
        )

        # 4. Resolve claim status badge
        claim_badge = await resolve_claim_status(db, temple, claims_map=claims_map)

        # Build list of active activities
        activities_list = []
        if temple.activities:
            for act in temple.activities:
                if act.is_active:
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
            "image_url": resolved_img,
            "hero_image_url": resolved_img,
            "image_variants": variants,
            "slug": temple.domain,
            "opening_time": legacy_op,
            "closing_time": legacy_cl,
            "temple_status": temple_status,
            "current_activity": current_activity,
            "upcoming_festival": upcoming_festival,
            "claim_status": claim_badge,
            "management_mode": temple.management_mode,
            "verification_level": temple.verification_level,
            "is_featured": temple.is_featured,
            "activities": activities_list
        })
    return items


@directory_router.get(
    "/states",
    response_model=List[dict],
    tags=["public-directory"]
)
async def get_public_states_directory(
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve a list of active states and the count of published temples in each state.
    """
    from sqlalchemy import func
    from app.models.domain import StateMaster
    import sqlalchemy as sa
    
    stmt = (
        select(
            sa.func.coalesce(StateMaster.name, TempleProfile.state, Temple.state).label("state_name"),
            func.count(Temple.id).label("temple_count")
        )
        .select_from(Temple)
        .outerjoin(TempleProfile, Temple.id == TempleProfile.temple_id)
        .outerjoin(StateMaster, Temple.state_id == StateMaster.id)
        .join(TempleWebsiteSettingsLive, Temple.id == TempleWebsiteSettingsLive.temple_id)
        .filter(Temple.is_active == True, Temple.status == "APPROVED", Temple.directory_status == "ACTIVE")
        .group_by(sa.text("state_name"))
        .order_by(sa.text("state_name ASC"))
    )
    result = await db.execute(stmt)
    rows = result.all()
    return [{"state": r.state_name, "temple_count": r.temple_count} for r in rows if r.state_name and r.state_name.strip()]


@directory_router.get(
    "/states/{state}/districts",
    response_model=List[dict],
    tags=["public-directory"]
)
async def get_public_districts_directory(
    state: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve a list of districts and temple counts for a specific state.
    """
    from sqlalchemy import func
    from app.models.domain import StateMaster, DistrictMaster
    import sqlalchemy as sa
    
    stmt = (
        select(
            sa.func.coalesce(DistrictMaster.name, TempleProfile.district, Temple.district).label("district_name"),
            func.count(Temple.id).label("temple_count")
        )
        .select_from(Temple)
        .outerjoin(TempleProfile, Temple.id == TempleProfile.temple_id)
        .outerjoin(StateMaster, Temple.state_id == StateMaster.id)
        .outerjoin(DistrictMaster, Temple.district_id == DistrictMaster.id)
        .join(TempleWebsiteSettingsLive, Temple.id == TempleWebsiteSettingsLive.temple_id)
        .filter(
            Temple.is_active == True,
            Temple.status == "APPROVED",
            Temple.directory_status == "ACTIVE",
            sa.func.coalesce(StateMaster.name, TempleProfile.state, Temple.state).ilike(state)
        )
        .group_by(sa.text("district_name"))
        .order_by(sa.text("district_name ASC"))
    )
    result = await db.execute(stmt)
    rows = result.all()
    return [{"district": r.district_name, "temple_count": r.temple_count} for r in rows if r.district_name and r.district_name.strip()]


@router.get(
    "/{slug}/store/products",
    response_model=List[StoreProductResponse],
    tags=["public-store"]
)
async def list_public_store_products(
    slug: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve list of active, unarchived products for a temple by its slug (domain).
    Does NOT require authentication.
    """
    if not re.match(r"^[a-z0-9-]+$", slug):
        raise HTTPException(status_code=400, detail="Invalid temple slug format")
        
    result = await db.execute(
        select(Temple).filter(Temple.domain == slug, Temple.is_active == True, Temple.status.in_(["APPROVED", "MERGED"]))
    )
    temple = result.scalars().first()
    if not temple:
        raise HTTPException(status_code=404, detail="Temple not found")

    if temple.status == "MERGED" and temple.merged_temple_id:
        dest_res = await db.execute(select(Temple.domain).filter(Temple.id == temple.merged_temple_id))
        dest_domain = dest_res.scalars().first()
        if dest_domain:
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=str(request.url).replace(temple.domain, dest_domain, 1), status_code=301)
        
    from app.models.domain import StoreProduct
    prod_stmt = select(StoreProduct).filter(
        StoreProduct.temple_id == temple.id,
        StoreProduct.is_active == True,
        StoreProduct.is_archived == False,
        StoreProduct.category != "Auction"
    ).order_by(StoreProduct.name)
    
    prod_res = await db.execute(prod_stmt)
    return prod_res.scalars().all()


@router.get(
    "/{slug}/store/auctions",
    response_model=List[AuctionListingResponse],
    tags=["public-store"]
)
async def list_public_store_auctions(
    slug: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve list of active, unarchived auction listings for a temple by its slug (domain).
    Does NOT require authentication to view.
    """
    if not re.match(r"^[a-z0-9-]+$", slug):
        raise HTTPException(status_code=400, detail="Invalid temple slug format")
        
    result = await db.execute(
        select(Temple).filter(Temple.domain == slug, Temple.is_active == True, Temple.status.in_(["APPROVED", "MERGED"]))
    )
    temple = result.scalars().first()
    if not temple:
        raise HTTPException(status_code=404, detail="Temple not found")

    from app.modules.inventory.models.inventory_models import AuctionListing
    from sqlalchemy.orm import selectinload

    auc_stmt = select(AuctionListing).options(
        selectinload(AuctionListing.product), 
        selectinload(AuctionListing.bids)
    ).filter(
        AuctionListing.temple_id == temple.id,
        AuctionListing.is_active == True,
        AuctionListing.is_archived == False,
        AuctionListing.status.in_(["AVAILABLE", "RESERVED"])
    ).order_by(AuctionListing.created_at.desc())
    
    auc_res = await db.execute(auc_stmt)
    return auc_res.scalars().all()


@router.post(
    "/{slug}/store/auctions/{auction_id}/bid",
    tags=["public-store"]
)
async def place_public_auction_bid(
    slug: str,
    auction_id: UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Allows a logged-in devotee to place a bid on an active auction.
    This is concurrency-safe and locks stock reservations.
    """
    if not re.match(r"^[a-z0-9-]+$", slug):
        raise HTTPException(status_code=400, detail="Invalid temple slug format")
        
    result = await db.execute(
        select(Temple).filter(Temple.domain == slug, Temple.is_active == True, Temple.status.in_(["APPROVED", "MERGED"]))
    )
    temple = result.scalars().first()
    if not temple:
        raise HTTPException(status_code=404, detail="Temple not found")

    from app.modules.inventory.models.inventory_models import AuctionListing, StoreStock, StoreStockReservation, InventoryStockLedger, StoreProduct, AuctionBid
    from app.modules.inventory.models.inventory_models import InventoryMovementType
    from app.modules.auth.models.auth_models import User
    
    # 1. Load devotee user to get their name
    user_uuid = UUID(str(current_user.sub)) if current_user.sub else None
    if not user_uuid:
        raise HTTPException(status_code=401, detail="Authentication required")
        
    user_res = await db.execute(select(User).filter(User.id == user_uuid))
    db_user = user_res.scalars().first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
        
    bidder_name = db_user.name or db_user.email or "Devotee"
    bid_amount = float(payload.get("bid_amount", 0.0))

    # 2. Load Auction listing
    auc_res = await db.execute(
        select(AuctionListing).filter(AuctionListing.id == auction_id, AuctionListing.temple_id == temple.id)
    )
    auction = auc_res.scalars().first()
    if not auction:
        raise HTTPException(status_code=404, detail="Auction listing not found")
        
    if auction.status not in ["AVAILABLE", "RESERVED"]:
        raise HTTPException(status_code=400, detail="Auction is no longer active")
        
    if bid_amount <= auction.current_bid:
        raise HTTPException(status_code=400, detail=f"Bid must be higher than current bid: {auction.current_bid}")

    # 3. Concurrency-safe Stock check and Reservation
    from app.core.database.session import utcnow
    expires_at = utcnow() + timedelta(minutes=10)
    
    async with db.begin_nested():
        reservation = None
        if auction.status == "AVAILABLE":
            # Lock stock row
            stock_res = await db.execute(
                select(StoreStock)
                .filter(StoreStock.product_id == auction.product_id, StoreStock.temple_id == temple.id)
                .with_for_update()
            )
            stock = stock_res.scalars().first()
            if not stock or stock.quantity < auction.quantity:
                raise HTTPException(status_code=400, detail="Insufficient physical stock in warehouse to lock this auction bid")
                
            # Deduct stock and increment version
            before_stock = stock.quantity
            after_stock = before_stock - auction.quantity
            stock.quantity = after_stock
            stock.version_number += 1
            
            # Create StoreStockReservation
            reservation = StoreStockReservation(
                temple_id=temple.id,
                product_id=auction.product_id,
                quantity_reserved=auction.quantity,
                reservation_status="RESERVED",
                expires_at=expires_at,
                reference_type="AUCTION",
                reference_id=str(auction.id),
                location_id=stock.location_id
            )
            db.add(reservation)
            await db.flush()
            
            # Record reservation movement in Ledger
            prod_res = await db.execute(select(StoreProduct).filter(StoreProduct.id == auction.product_id))
            product = prod_res.scalars().first()
            
            ledger = InventoryStockLedger(
                temple_id=temple.id,
                domain_type="STORE",
                store_product_id=auction.product_id,
                kalavara_item_id=None,
                item_name=product.name if product else "Product",
                location_id=stock.location_id,
                movement_type=InventoryMovementType.AUCTION_RESERVATION,
                quantity_change=-auction.quantity,
                before_stock=before_stock,
                after_stock=after_stock,
                reference_type="AUCTION_RESERVATION",
                reference_id=str(reservation.id),
                performed_by=user_uuid,
                remarks=f"Auction bid placed by devotee {bidder_name}: Reservation locked for 10 minutes (Expires {expires_at.strftime('%H:%M:%S')})"
            )
            db.add(ledger)
        else:
            # Auction is already RESERVED, so stock is already locked and reserved.
            res_res = await db.execute(
                select(StoreStockReservation)
                .filter(
                    StoreStockReservation.reference_type == "AUCTION",
                    StoreStockReservation.reference_id == str(auction.id),
                    StoreStockReservation.reservation_status == "RESERVED"
                )
            )
            reservation = res_res.scalars().first()
            if not reservation:
                # Re-check stock and lock it
                stock_res = await db.execute(
                    select(StoreStock)
                    .filter(StoreStock.product_id == auction.product_id, StoreStock.temple_id == temple.id)
                    .with_for_update()
                )
                stock = stock_res.scalars().first()
                if not stock or stock.quantity < auction.quantity:
                    raise HTTPException(status_code=400, detail="Insufficient physical stock in warehouse to lock this auction bid")
                
                # Deduct stock and increment version
                before_stock = stock.quantity
                after_stock = before_stock - auction.quantity
                stock.quantity = after_stock
                stock.version_number += 1

                reservation = StoreStockReservation(
                    temple_id=temple.id,
                    product_id=auction.product_id,
                    quantity_reserved=auction.quantity,
                    reservation_status="RESERVED",
                    expires_at=expires_at,
                    reference_type="AUCTION",
                    reference_id=str(auction.id),
                    location_id=stock.location_id
                )
                db.add(reservation)
                await db.flush()

                # Record reservation movement in Ledger
                prod_res = await db.execute(select(StoreProduct).filter(StoreProduct.id == auction.product_id))
                product = prod_res.scalars().first()
                
                ledger = InventoryStockLedger(
                    temple_id=temple.id,
                    domain_type="STORE",
                    store_product_id=auction.product_id,
                    kalavara_item_id=None,
                    item_name=product.name if product else "Product",
                    location_id=stock.location_id,
                    movement_type=InventoryMovementType.AUCTION_RESERVATION,
                    quantity_change=-auction.quantity,
                    before_stock=before_stock,
                    after_stock=after_stock,
                    reference_type="AUCTION_RESERVATION",
                    reference_id=str(reservation.id),
                    performed_by=user_uuid,
                    remarks=f"Auction bid placed by devotee {bidder_name}: Reservation re-locked for 10 minutes (Expires {expires_at.strftime('%H:%M:%S')})"
                )
                db.add(ledger)
            else:
                reservation.expires_at = expires_at

        # Update Auction Status & Current Bid
        auction.current_bid = bid_amount
        auction.status = "RESERVED"
        
        # Create AuctionBid record
        bid_record = AuctionBid(
            temple_id=temple.id,
            auction_id=auction.id,
            bidder_name=bidder_name,
            bid_amount=bid_amount,
            created_at=utcnow()
        )
        db.add(bid_record)
        
    # Add Audit log
    from app.modules.audit.services.audit_service import AuditService
    await AuditService.log_action(
        db=db,
        temple_id=temple.id,
        user_id=user_uuid,
        role=current_user.role,
        module_name="STORE",
        action="AUCTION_BID_PLACED",
        action_type="CREATE",
        entity_id=str(bid_record.id),
        new_value={"bid_amount": float(bid_amount), "bidder_name": bidder_name},
        details=f"Devotee bid of Rs.{bid_amount} placed on auction '{auction.auction_code}' by {bidder_name}."
    )
        
    await db.commit()
    return {"status": "success", "current_bid": auction.current_bid, "reservation_id": reservation.id, "expires_at": expires_at}


@router.get(
    "/{slug}/halls",
    tags=["public-portal"]
)
async def list_public_temple_halls(
    slug: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve active, unarchived halls/venues for a temple by its slug.
    Does NOT require authentication.
    """
    if not re.match(r"^[a-z0-9-]+$", slug):
        raise HTTPException(status_code=400, detail="Invalid temple slug format")
        
    result = await db.execute(
        select(Temple).filter(Temple.domain == slug, Temple.is_active == True, Temple.status.in_(["APPROVED", "MERGED"]))
    )
    temple = result.scalars().first()
    if not temple:
        raise HTTPException(status_code=404, detail="Temple not found")

    from app.modules.bookings.models.booking_models import Hall
    hall_stmt = select(Hall).filter(
        Hall.temple_id == temple.id,
        Hall.is_active == True,
        Hall.status == "active"
    ).order_by(Hall.name)
    
    hall_res = await db.execute(hall_stmt)
    halls = hall_res.scalars().all()
    
    return [
        {
            "id": str(hall.id),
            "name": hall.name,
            "capacity": hall.capacity,
            "amenities": hall.amenities,
            "price_per_day": hall.price_per_day,
            "image_emoji": hall.image_emoji,
            "photos": hall.photos
        }
        for hall in halls
    ]


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
            joinedload(Temple.website_settings_live),
            selectinload(Temple.festivals),
            selectinload(Temple.key_personnels)
        )
        .filter(Temple.domain == slug, Temple.is_active == True, Temple.status.in_(["APPROVED", "MERGED"]))
    )
    temple = result.scalars().first()
    if not temple:
        raise HTTPException(status_code=404, detail="Temple not found")

    if temple.status == "MERGED" and temple.merged_temple_id:
        dest_res = await db.execute(select(Temple.domain).filter(Temple.id == temple.merged_temple_id))
        dest_domain = dest_res.scalars().first()
        if dest_domain:
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=str(request.url).replace(temple.domain, dest_domain, 1), status_code=301)

    # Resolve active website maturity stage
    from app.modules.temple_management.services.resolver import TempleWebsiteLifecycleResolver
    lifecycle_stage = TempleWebsiteLifecycleResolver.resolve_stage(temple)

    if temple.management_mode != "DIRECTORY_ONLY" and not temple.website_settings_live:
        raise HTTPException(status_code=404, detail="Temple website is not published")


    # 3. Direct Mapping of Profile & Images
    profile_db = temple.profile
    
    # Fetch active deities from DeityMaster table
    from app.models.archana import DeityMaster, DeityStatus
    deity_stmt = select(DeityMaster.deity_name).filter(
        DeityMaster.tenant_id == temple.id,
        DeityMaster.status == DeityStatus.ACTIVE
    )
    deity_res = await db.execute(deity_stmt)
    active_deities = [row[0] for row in deity_res.all()]
    profile_deities = profile_db.deities if profile_db else []
    deities_list = active_deities if active_deities else profile_deities

    images = []
    if temple.images:
        visible_images = TempleImage.filter_visible(temple.images)
        for img in visible_images:
            images.append({
                "id": str(img.id),
                "temple_id": str(img.temple_id),
                "image_url": img.image_url,
                "caption": img.caption or "",
                "category": img.category or "GALLERY",
                "is_visible": getattr(img, 'is_visible', True),
                "created_at": img.created_at.isoformat() if img.created_at else None
            })

    # Serialize active key personnel
    key_personnels = []
    if temple.key_personnels:
        active_kp = [kp for kp in temple.key_personnels if kp.is_active]
        active_kp = sorted(active_kp, key=lambda x: x.display_order)
        for kp in active_kp:
            key_personnels.append({
                "id": str(kp.id),
                "name": kp.name,
                "designation": kp.designation,
                "image_url": kp.image_url,
                "display_order": kp.display_order
            })

    profile = {
        "id": str(temple.id),
        "name": temple.name,
        "domain": temple.domain,
        "management_mode": temple.management_mode,
        "verification_level": temple.verification_level,
        "claim_status": await resolve_claim_status(db, temple),
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
        "deities": deities_list,
        "facebook_url": profile_db.facebook_url if profile_db else "",
        "instagram_url": profile_db.instagram_url if profile_db else "",
        "youtube_url": profile_db.youtube_url if profile_db else "",
        "twitter_url": profile_db.twitter_url if profile_db else "",
        "website_url": profile_db.website_url if profile_db else "",
        "festivals_description": profile_db.festivals_description if profile_db else "",
        "short_description": profile_db.short_description if profile_db else "",
        "meta_title": profile_db.meta_title if profile_db else "",
        "meta_description": profile_db.meta_description if profile_db else "",
        "published_at": profile_db.published_at.isoformat() if (profile_db and profile_db.published_at) else None,
        "published_by": str(profile_db.published_by) if (profile_db and profile_db.published_by) else None,
        "images": images,
        "key_personnels": key_personnels
    }

    # 4. Extract settings and featureVisibility from the live snapshot or use defaults
    live = temple.website_settings_live
    if live:
        settings_snapshot = live.settings_snapshot
        published_at = live.published_at.isoformat() if live.published_at else None
        settings_id = str(live.id)
    else:
        settings_snapshot = {
            "theme_name": "default",
            "primary_color": "#ff6600",
            "secondary_color": "#ffcc00",
            "logo_url": None,
            "hero_layout": "split",
            "section_order": ["hero", "about", "timings", "announcements", "activities", "gallery", "offerings", "location"],
            "enable_mantras": True,
            "enable_festivals": True,
            "enable_donations": True,
            "enable_hall_booking": True,
            "enable_store": True,
            "seo_keywords": None,
            "og_image_url": None,
            "hero_title": temple.name,
            "hero_subtitle": temple.location,
            "seo_description": temple.description,
            "notice_board_content": None,
            "location_settings": {
                "google_maps_url": getattr(profile_db, 'google_maps_url', None) if profile_db else None,
                "latitude": profile_db.latitude if profile_db else None,
                "longitude": profile_db.longitude if profile_db else None,
                "location_label": getattr(profile_db, 'map_display_label', None) if profile_db else "📍 Temple Location"
            } if profile_db else {},
            "timings_settings": [],
            "daily_activities_settings": []
        }
        published_at = temple.created_at.isoformat() if temple.created_at else None
        settings_id = str(temple.id)

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
        "enableAnnouncements": True,
        "showLeftSpotlight": True,
        "showRightSpotlight": True,
        "showSidebarRail": True
    }
    
    feature_visibility = dict(default_visibility)
    snapshot_visibility = settings_snapshot.get("featureVisibility")
    if snapshot_visibility:
        for k, v in snapshot_visibility.items():
            feature_visibility[k] = v

    if lifecycle_stage == "DIRECTORY_TEMPLATE":
        # Force disable transaction CTAs
        feature_visibility["enablePoojaBooking"] = False
        feature_visibility["enableOfferings"] = False
        feature_visibility["enableStore"] = False
        feature_visibility["enableHallBooking"] = False
        feature_visibility["enableFollow"] = True

    raw_section_order = settings_snapshot.get("section_order") or ["hero", "about", "timings", "gallery", "location"]
    section_order = list(raw_section_order)

    # ── Auto-inject missing enabled sections in deterministic priority order ──
    target_sections = ["hero", "about"]
    if feature_visibility.get("enableAnnouncements"):
        target_sections.append("announcements")
    if feature_visibility.get("enableActivities"):
        target_sections.append("activities")
    if settings_snapshot.get("enable_festivals") is not False:
        target_sections.append("festivals")
    if feature_visibility.get("enableGallery") is not False:
        target_sections.append("gallery")
    # Always include key_personnel section
    target_sections.append("key_personnel")
    if settings_snapshot.get("enable_mantras") is not False:
        target_sections.append("mantras")
    target_sections.append("contact")

    master_order = ["hero", "about", "announcements", "activities", "festivals", "gallery", "key_personnel", "mantras", "contact"]
    for sec in master_order:
        if sec in target_sections and sec not in section_order:
            inserted = False
            for target_sec in master_order[master_order.index(sec) + 1:]:
                if target_sec in section_order:
                    idx = section_order.index(target_sec)
                    section_order.insert(idx, sec)
                    inserted = True
                    break
            if not inserted:
                section_order.append(sec)
    if lifecycle_stage == "DIRECTORY_TEMPLATE":
        # Strip transactional sections
        for sec in ["offerings", "store", "hall_booking"]:
            if sec in section_order:
                section_order.remove(sec)
        # Strip timings if empty
        timings_settings = settings_snapshot.get("timings_settings")
        if not timings_settings and "timings" in section_order:
            section_order.remove("timings")

    settings = {
        "id": settings_id,
        "temple_id": str(temple.id),
        "theme_name": settings_snapshot.get("theme_name") or "default",
        "primary_color": settings_snapshot.get("primary_color") or "#ff6600",
        "secondary_color": settings_snapshot.get("secondary_color") or "#ffcc00",
        "logo_url": settings_snapshot.get("logo_url"),
        "hero_layout": settings_snapshot.get("hero_layout") or "split",
        "section_order": section_order,
        "enable_mantras": settings_snapshot.get("enable_mantras") if settings_snapshot.get("enable_mantras") is not None else True,
        "enable_festivals": settings_snapshot.get("enable_festivals") if settings_snapshot.get("enable_festivals") is not None else True,
        "enable_donations": settings_snapshot.get("enable_donations") if settings_snapshot.get("enable_donations") is not None else True,
        "enable_hall_booking": settings_snapshot.get("enable_hall_booking") if settings_snapshot.get("enable_hall_booking") is not None else True,
        "enable_store": settings_snapshot.get("enable_store") if settings_snapshot.get("enable_store") is not None else True,
        "feature_visibility": feature_visibility,
        "seo_keywords": settings_snapshot.get("seo_keywords"),
        "og_image_url": settings_snapshot.get("og_image_url"),
        "hero_title": settings_snapshot.get("hero_title"),
        "hero_subtitle": settings_snapshot.get("hero_subtitle"),
        "seo_description": settings_snapshot.get("seo_description"),
        "notice_board_content": settings_snapshot.get("notice_board_content"),
        "location_settings": settings_snapshot.get("location_settings"),
        "timings_settings": settings_snapshot.get("timings_settings"),
        "daily_activities_settings": settings_snapshot.get("daily_activities_settings"),
        "created_at": published_at,
        "updated_at": published_at
    }

    # Serialize active festivals
    festivals = []
    if temple.festivals:
        for f in temple.festivals:
            if f.is_active:
                festivals.append({
                    "id": str(f.id),
                    "temple_id": str(f.temple_id),
                    "name": f.name,
                    "description": f.description,
                    "start_date": f.start_date.isoformat(),
                    "end_date": f.end_date.isoformat(),
                    "priority": f.priority,
                    "banner_image": f.banner_image,
                    "catalogue_urls": f.catalogue_urls,
                    "is_active": f.is_active,
                    "created_at": f.created_at.isoformat() if f.created_at else None,
                    "updated_at": f.updated_at.isoformat() if f.updated_at else None
                })

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
                "expiry_date": ann.expiry_date.isoformat() if ann.expiry_date else None,
                "created_at": ann.created_at.isoformat() if ann.created_at else None
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
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    advertisements = []
    
    # Only fetch if ads are enabled
    if feature_visibility.get("enableTempleAds") or feature_visibility.get("enablePlatformAds"):
        # We query active temple ads
        temple_ads_stmt = select(TempleAdvertisement).filter(
            TempleAdvertisement.temple_id == temple.id,
            TempleAdvertisement.is_active == True,
            TempleAdvertisement.approval_status == "APPROVED",
            TempleAdvertisement.start_date <= now + timedelta(hours=14),
            TempleAdvertisement.end_date >= now - timedelta(hours=14)
        ).order_by(TempleAdvertisement.display_order.asc(), TempleAdvertisement.created_at.desc())
        
        temple_ads_res = await db.execute(temple_ads_stmt)
        temple_ads = temple_ads_res.scalars().all()
        
        # We query active platform ads
        platform_ads_stmt = select(PlatformAdvertisement).filter(
            PlatformAdvertisement.is_active == True,
            PlatformAdvertisement.approval_status == "PUBLISHED",
            PlatformAdvertisement.start_date <= now + timedelta(hours=14),
            PlatformAdvertisement.end_date >= now - timedelta(hours=14)
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
                    "media_type": ad.media_type,
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
                    "media_type": ad.media_type,
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
        publicActions=public_actions,
        festivals=festivals
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
        select(Temple).filter(Temple.domain == slug, Temple.is_active == True, Temple.status.in_(["APPROVED", "MERGED"]))
    )
    temple = result.scalars().first()
    if not temple:
        raise HTTPException(status_code=404, detail="Temple not found")

    if temple.status == "MERGED" and temple.merged_temple_id:
        dest_res = await db.execute(select(Temple.domain).filter(Temple.id == temple.merged_temple_id))
        dest_domain = dest_res.scalars().first()
        if dest_domain:
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=str(request.url).replace(temple.domain, dest_domain, 1), status_code=301)

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


@router.get(
    "/advertisements/active",
    response_model=List[dict],
    tags=["public-temple-portal"]
)
async def list_active_public_advertisements(
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve all active platform and temple advertisements.
    """
    from datetime import datetime, timezone, timedelta
    from app.modules.temple_management.models.temple_models import TempleAdvertisement, PlatformAdvertisement
    from sqlalchemy import select

    now = datetime.now(timezone.utc)
    advertisements = []

    # active platform ads
    platform_ads_stmt = select(PlatformAdvertisement).filter(
        PlatformAdvertisement.is_active == True,
        PlatformAdvertisement.approval_status == "PUBLISHED",
        PlatformAdvertisement.start_date <= now + timedelta(hours=14),
        PlatformAdvertisement.end_date >= now - timedelta(hours=14)
    ).order_by(PlatformAdvertisement.created_at.desc())
    platform_ads_res = await db.execute(platform_ads_stmt)
    platform_ads = platform_ads_res.scalars().all()

    for ad in platform_ads:
        advertisements.append({
            "id": str(ad.id),
            "advertisement_type": "PLATFORM",
            "placement": ad.placement,
            "media_urls": ad.media_urls,
            "media_type": ad.media_type,
            "target_url": ad.target_url,
            "start_date": ad.start_date.isoformat() if ad.start_date else None,
            "end_date": ad.end_date.isoformat() if ad.end_date else None,
            "display_order": 0
        })

    return advertisements


@public_router.get("/states", response_model=List[dict])
async def get_public_states(
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve active states from StateMaster and temple counts.
    """
    from sqlalchemy import func
    stmt = (
        select(StateMaster.id, StateMaster.name, StateMaster.slug, StateMaster.code, func.count(Temple.id).label("temple_count"))
        .outerjoin(Temple, (Temple.state_id == StateMaster.id) & 
                            (Temple.is_active == True) & 
                            (Temple.status == "APPROVED") & 
                            (Temple.directory_status == "ACTIVE"))
        .group_by(StateMaster.id, StateMaster.name, StateMaster.slug, StateMaster.code)
        .order_by(StateMaster.name.asc())
    )
    result = await db.execute(stmt)
    rows = result.all()
    return [
        {
            "id": str(r.id),
            "state": r.name,
            "slug": r.slug,
            "code": r.code,
            "temple_count": r.temple_count
        }
        for r in rows
    ]


@public_router.get("/states/{state_slug}/districts", response_model=List[dict])
async def get_public_districts(
    state_slug: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve districts and temple counts for a specific state slug.
    """
    from sqlalchemy import func
    state_stmt = select(StateMaster).filter(StateMaster.slug == state_slug.lower())
    state_res = await db.execute(state_stmt)
    state_obj = state_res.scalars().first()
    if not state_obj:
        raise HTTPException(status_code=404, detail="State not found")

    stmt = (
        select(DistrictMaster.id, DistrictMaster.name, DistrictMaster.slug, DistrictMaster.code, func.count(Temple.id).label("temple_count"))
        .filter(DistrictMaster.state_id == state_obj.id)
        .outerjoin(Temple, (Temple.district_id == DistrictMaster.id) & 
                            (Temple.is_active == True) & 
                            (Temple.status == "APPROVED") & 
                            (Temple.directory_status == "ACTIVE"))
        .group_by(DistrictMaster.id, DistrictMaster.name, DistrictMaster.slug, DistrictMaster.code)
        .order_by(DistrictMaster.name.asc())
    )
    result = await db.execute(stmt)
    rows = result.all()
    return [
        {
            "id": str(r.id),
            "district": r.name,
            "slug": r.slug,
            "code": r.code,
            "temple_count": r.temple_count
        }
        for r in rows
    ]


@public_router.get("/states/{state_slug}/districts/{district_slug}/temples", response_model=List[dict])
async def get_public_district_temples(
    state_slug: str,
    district_slug: str,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve temples within a specific state and district slug.
    """
    state_stmt = select(StateMaster).filter(StateMaster.slug == state_slug.lower())
    state_res = await db.execute(state_stmt)
    state_obj = state_res.scalars().first()
    if not state_obj:
        raise HTTPException(status_code=404, detail="State not found")

    dist_stmt = select(DistrictMaster).filter(DistrictMaster.state_id == state_obj.id, DistrictMaster.slug == district_slug.lower())
    dist_res = await db.execute(dist_stmt)
    dist_obj = dist_res.scalars().first()
    if not dist_obj:
        raise HTTPException(status_code=404, detail="District not found")

    stmt = (
        select(Temple)
        .filter(Temple.district_id == dist_obj.id, Temple.is_active == True, Temple.status == "APPROVED", Temple.directory_status == "ACTIVE")
        .options(
            selectinload(Temple.profile),
            selectinload(Temple.website_settings_live),
            selectinload(Temple.images),
            selectinload(Temple.activities),
            selectinload(Temple.festivals)
        )
        .order_by(Temple.name.asc())
    )
    
    offset = (page - 1) * limit
    stmt = stmt.limit(limit).offset(offset)
    
    result = await db.execute(stmt)
    temples = result.scalars().all()
    
    items = []
    for temple in temples:
        profile = temple.profile
        resolved_img = resolve_temple_image(temple)
        variants = get_image_variants(resolved_img)
        claim_badge = await resolve_claim_status(db, temple)
        
        items.append({
            "id": str(temple.id),
            "name": temple.name,
            "location": profile.location if profile else "",
            "district": dist_obj.name,
            "state": state_obj.name,
            "slug": temple.domain,
            "image_url": resolved_img,
            "hero_image_url": resolved_img,
            "image_variants": variants,
            "claim_status": claim_badge,
            "management_mode": temple.management_mode,
            "verification_level": temple.verification_level,
            "is_featured": temple.is_featured,
        })
    return items


@public_router.get("/search", response_model=List[dict])
async def search_public_temples(
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db)
):
    """
    Ranked temple search matching query across Temple Name, Alternative Names,
    District, State, Village, Deity, Keywords, and Festival Names.
    """
    clean_q = q.strip().lower()
    if not clean_q:
        return []

    from sqlalchemy import or_
    stmt = (
        select(Temple)
        .outerjoin(TempleSearchIndex, Temple.id == TempleSearchIndex.temple_id)
        .outerjoin(TempleProfile, Temple.id == TempleProfile.temple_id)
        .outerjoin(StateMaster, Temple.state_id == StateMaster.id)
        .outerjoin(DistrictMaster, Temple.district_id == DistrictMaster.id)
        .options(
            selectinload(Temple.profile),
            selectinload(Temple.website_settings_live),
            selectinload(Temple.images),
            selectinload(Temple.activities),
            selectinload(Temple.festivals),
            selectinload(Temple.search_index)
        )
        .filter(
            Temple.is_active == True,
            Temple.status == "APPROVED",
            Temple.directory_status == "ACTIVE"
        )
        .filter(
            or_(
                sa.func.lower(Temple.name).like(f"%{clean_q}%"),
                sa.func.lower(TempleProfile.main_deity).like(f"%{clean_q}%"),
                sa.func.lower(StateMaster.name).like(f"%{clean_q}%"),
                sa.func.lower(DistrictMaster.name).like(f"%{clean_q}%"),
                sa.func.lower(TempleSearchIndex.alternative_names).like(f"%{clean_q}%"),
                sa.func.lower(TempleSearchIndex.keywords).like(f"%{clean_q}%"),
                sa.func.lower(TempleSearchIndex.village).like(f"%{clean_q}%"),
                Temple.festivals.any(sa.func.lower(TempleFestival.name).like(f"%{clean_q}%"))
            )
        )
    )

    result = await db.execute(stmt)
    candidates = result.scalars().all()

    scored_items = []
    from app.modules.governance.models.operational_states import TempleOperationalState

    # Pre-fetch all StateMaster and DistrictMaster to avoid N+1 queries in the loop
    states_stmt = select(StateMaster)
    states_res = await db.execute(states_stmt)
    states_map = {s.id: s.name.strip() for s in states_res.scalars().all() if s.name}

    districts_stmt = select(DistrictMaster)
    districts_res = await db.execute(districts_stmt)
    districts_map = {d.id: d.name.strip() for d in districts_res.scalars().all() if d.name}

    for temple in candidates:
        profile = temple.profile
        search_idx = temple.search_index
        
        name = temple.name.strip().lower() if temple.name else ""
        alt_names = [n.strip().lower() for n in search_idx.alternative_names.split(",")] if (search_idx and search_idx.alternative_names) else []
        main_deity = profile.main_deity.strip().lower() if (profile and profile.main_deity) else ""
        deities = [d.strip().lower() for d in (profile.deities or [])] if (profile and profile.deities) else []
        
        state_name_raw = states_map.get(temple.state_id, "")
        district_name_raw = districts_map.get(temple.district_id, "")
        
        state_name = state_name_raw.lower()
        district_name = district_name_raw.lower()
        
        village = search_idx.village.strip().lower() if (search_idx and search_idx.village) else ""
        keywords = [k.strip().lower() for k in search_idx.keywords.split(",")] if (search_idx and search_idx.keywords) else []
        
        festival_names = [f.name.strip().lower() for f in temple.festivals if f.name] if temple.festivals else []

        base_score = 0
        
        # 1. Exact Match (Score = 100)
        if clean_q == name or clean_q in alt_names:
            base_score = max(base_score, 100)
        # 2. Temple Name Match (Score = 50)
        elif clean_q in name or any(clean_q in alt for alt in alt_names):
            base_score = max(base_score, 50)
        # 3. Deity Match (Score = 30)
        elif clean_q == main_deity or clean_q in main_deity or clean_q in deities or any(clean_q in d for d in deities):
            base_score = max(base_score, 30)
        # 4. District Match (Score = 20)
        elif clean_q == district_name or clean_q in district_name or clean_q == state_name or clean_q in state_name or clean_q == village or clean_q in village:
            base_score = max(base_score, 20)
        # 5. Keyword Match (Score = 10)
        elif clean_q in keywords or any(clean_q in k for k in keywords) or any(clean_q in f for f in festival_names):
            base_score = max(base_score, 10)

        bonus = 0
        if temple.operational_state == TempleOperationalState.ACTIVE:
            bonus += 15
        if temple.verification_level == 3:
            bonus += 10
        if temple.is_featured:
            bonus += 5

        total_score = base_score + bonus
        
        if base_score > 0:
            resolved_img = resolve_temple_image(temple)
            variants = get_image_variants(resolved_img)
            claim_badge = await resolve_claim_status(db, temple)
            
            scored_items.append({
                "temple": {
                    "id": str(temple.id),
                    "name": temple.name,
                    "location": profile.location if profile else "",
                    "district": district_name_raw,
                    "state": state_name_raw,
                    "slug": temple.domain,
                    "image_url": resolved_img,
                    "hero_image_url": resolved_img,
                    "image_variants": variants,
                    "claim_status": claim_badge,
                    "management_mode": temple.management_mode,
                    "verification_level": temple.verification_level,
                    "is_featured": temple.is_featured,
                },
                "score": total_score,
                "is_featured": temple.is_featured,
                "name_key": name
            })

    scored_items.sort(key=lambda x: (-x["score"], -int(x["is_featured"]), x["name_key"]))
    
    offset = (page - 1) * limit
    paginated_items = scored_items[offset:offset+limit]
    
    return [{**item["temple"], "search_score": item["score"]} for item in paginated_items]


@public_router.get("/featured-temples", response_model=List[dict])
async def get_public_featured_temples(
    category: str = Query("FEATURED"),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve up to 6 temples categorized by FEATURED, TRENDING, or RECENTLY_ADDED.
    """
    stmt = (
        select(Temple)
        .outerjoin(TempleWebsiteSettingsLive, Temple.id == TempleWebsiteSettingsLive.temple_id)
        .outerjoin(TempleProfile, Temple.id == TempleProfile.temple_id)
        .options(
            selectinload(Temple.profile),
            selectinload(Temple.website_settings_live),
            selectinload(Temple.images),
            selectinload(Temple.activities),
            selectinload(Temple.festivals)
        )
        .filter(Temple.is_active == True, Temple.status == "APPROVED", Temple.directory_status == "ACTIVE")
    )
    
    category = category.upper()
    if category == "FEATURED":
        stmt = stmt.filter(Temple.is_featured == True)
    elif category == "TRENDING":
        stmt = stmt.order_by(Temple.is_featured.desc(), Temple.created_at.desc())
    elif category == "RECENTLY_ADDED":
        stmt = stmt.order_by(Temple.created_at.desc())
    else:
        stmt = stmt.filter(Temple.is_featured == True)
        
    stmt = stmt.limit(6)
    result = await db.execute(stmt)
    temples = result.scalars().all()
    
    if category == "FEATURED" and len(temples) < 6:
        needed = 6 - len(temples)
        existing_ids = [t.id for t in temples]
        fill_stmt = (
            select(Temple)
            .filter(Temple.is_active == True, Temple.status == "APPROVED", Temple.directory_status == "ACTIVE")
            .filter(~Temple.id.in_(existing_ids) if existing_ids else True)
            .options(
                selectinload(Temple.profile),
                selectinload(Temple.website_settings_live),
                selectinload(Temple.images)
            )
            .limit(needed)
        )
        fill_res = await db.execute(fill_stmt)
        temples.extend(fill_res.scalars().all())
        
    items = []
    for temple in temples:
        profile = temple.profile
        resolved_img = resolve_temple_image(temple)
        variants = get_image_variants(resolved_img)
        claim_badge = await resolve_claim_status(db, temple)
        
        # Follower count query
        follower_stmt = select(sa.func.count(TempleFollower.id)).filter(TempleFollower.temple_id == temple.id)
        follower_res = await db.execute(follower_stmt)
        follower_count = follower_res.scalar() or 0

        items.append({
            "id": str(temple.id),
            "name": temple.name,
            "location": profile.location if profile else "",
            "district": profile.district if profile else "",
            "state": profile.state if profile else "",
            "slug": temple.domain,
            "image_url": resolved_img,
            "hero_image_url": resolved_img,
            "image_variants": variants,
            "claim_status": claim_badge,
            "management_mode": temple.management_mode,
            "verification_level": temple.verification_level,
            "is_featured": temple.is_featured,
            "follower_count": follower_count,
        })
    return items


@public_router.get("/upcoming-festivals", response_model=List[dict])
async def get_upcoming_festivals_endpoint(
    limit: int = Query(10, ge=1, le=150),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve upcoming festivals across all active temples.
    """
    from app.modules.temple_management.services.homepage_service import HomepageService
    return await HomepageService.get_upcoming_festivals(db, limit)


@public_router.get("/homepage", response_model=dict)
async def get_homepage_bootstrap_endpoint(
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve consolidated discovery data for the Google-style homepage.
    """
    from app.modules.temple_management.services.homepage_service import HomepageService
    return await HomepageService.get_homepage_data(db)


@public_router.get("/nearby-temples", response_model=List[dict])
async def get_nearby_temples(
    latitude: float = Query(...),
    longitude: float = Query(...),
    radius: float = Query(50.0, ge=0.0, le=250.0),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieve nearest temples within a specified radius (up to 250km) using Python-level Haversine filtering.
    """
    if not (-90.0 <= latitude <= 90.0):
        raise HTTPException(status_code=400, detail="Latitude must be between -90 and 90")
    if not (-180.0 <= longitude <= 180.0):
        raise HTTPException(status_code=400, detail="Longitude must be between -180 and 180")
        
    radius = min(radius, 250.0)

    stmt = (
        select(Temple)
        .join(TempleProfile, Temple.id == TempleProfile.temple_id)
        .options(
            selectinload(Temple.profile),
            selectinload(Temple.website_settings_live),
            selectinload(Temple.images)
        )
        .filter(
            Temple.is_active == True,
            Temple.status == "APPROVED",
            Temple.directory_status == "ACTIVE",
            TempleProfile.latitude != None,
            TempleProfile.longitude != None
        )
    )
    result = await db.execute(stmt)
    temples = result.scalars().all()

    import math
    def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    nearby = []
    for t in temples:
        profile = t.profile
        dist = haversine_distance(latitude, longitude, profile.latitude, profile.longitude)
        if dist <= radius:
            resolved_img = resolve_temple_image(t)
            thumbnail = get_image_variants(resolved_img).get("thumbnail", "/static/default-temple.jpg")
            nearby.append({
                "id": str(t.id),
                "name": t.name,
                "slug": t.domain,
                "state": profile.state or "",
                "district": profile.district or "",
                "thumbnail": thumbnail,
                "distance": round(dist, 2)
            })

    nearby.sort(key=lambda x: x["distance"])
    return nearby


@public_router.get("/recommendations/temples", response_model=List[dict])
async def get_recommended_temples(
    request: Request,
    latitude: Optional[float] = Query(None, alias="latitude"),
    longitude: Optional[float] = Query(None, alias="longitude"),
    state: Optional[str] = Query(None),
    district: Optional[str] = Query(None),
    limit: int = Query(6, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user_optional)
):
    """
    Returns rules-based explainable temple recommendations for devotee portal.
    Target response time: < 150ms.
    """
    user_id = UUID(current_user.sub) if current_user else None
    return await RecommendationService.get_temple_recommendations(
        db, user_id=user_id, lat=latitude, lon=longitude, state=state, district=district, limit=limit
    )


DEITY_REGISTRY = {
    "shiva": {
        "name": "Shiva",
        "description": "Lord Shiva, the Destroyer and Transformer within the Trimurti, represents the supreme consciousness. He is worshipped in forms such as Mahadeva, Nataraja, and Dakshinamurthy.",
        "related": ["Parvati", "Ganesha", "Murugan"]
    },
    "krishna": {
        "name": "Krishna",
        "description": "Lord Krishna, the eighth avatar of Lord Vishnu, is the deity of compassion, tenderness, and love. He is widely worshipped across India as Guruvayurappan, Dwarkadhish, and Jagannath.",
        "related": ["Vishnu", "Radha", "Balarama"]
    },
    "ayyappa": {
        "name": "Ayyappa",
        "description": "Lord Ayyappa is the deity of growth and youth, worshipped especially at Sabarimala. Born from the union of Shiva and Mohini (Vishnu), he embodies supreme celibacy and asceticism.",
        "related": ["Shiva", "Vishnu"]
    },
    "devi": {
        "name": "Devi",
        "description": "The divine feminine force, Adi Parashakti, is worshipped in multiple powerful forms including Durga, Kali, Lakshmi, Saraswati, and local temple bhagavathis.",
        "related": ["Shiva", "Parvati", "Lakshmi"]
    },
    "murugan": {
        "name": "Murugan",
        "description": "Lord Murugan (Kartikeya), the son of Shiva and Parvati, is the Hindu god of war, victory, and wisdom, highly revered across South India and the Tamil diaspora.",
        "related": ["Shiva", "Parvati", "Ganesha"]
    },
    "ganapathi": {
        "name": "Ganapathi",
        "description": "Lord Ganesha (Vinayaka), the elephant-headed deity, is the lord of obstacles, beginnings, and wisdom, worshipped before commencing any ritual or work.",
        "related": ["Shiva", "Parvati", "Murugan"]
    },
    "hanuman": {
        "name": "Hanuman",
        "description": "Lord Hanuman, the monkey deity, represents supreme devotion (bhakti), strength, and loyalty to Lord Rama. He is believed to be an avatar of Lord Shiva.",
        "related": ["Rama", "Sita"]
    }
}

@public_router.get("/deities", response_model=List[dict])
async def list_deities(db: AsyncSession = Depends(get_db)):
    """
    Returns list of stable deities with associated temple counts.
    """
    stmt = (
        select(TempleProfile.main_deity, sa.func.count(Temple.id))
        .join(Temple, Temple.id == TempleProfile.temple_id)
        .filter(Temple.is_active == True, Temple.status == "APPROVED", Temple.directory_status == "ACTIVE")
        .group_by(TempleProfile.main_deity)
    )
    res = await db.execute(stmt)
    counts = {row[0].strip().lower(): row[1] for row in res.all() if row[0]}
    
    result = []
    for slug, info in DEITY_REGISTRY.items():
        match_count = 0
        deity_name = info["name"].lower()
        for k, v in counts.items():
            if deity_name in k or k in deity_name:
                match_count += v
                
        result.append({
            "slug": slug,
            "name": info["name"],
            "description": info["description"],
            "temple_count": match_count
        })
    return result

@public_router.get("/deities/{deity_slug}", response_model=dict)
async def get_deity_details(deity_slug: str, db: AsyncSession = Depends(get_db)):
    """
    Returns detailed deity information, associated temples, and upcoming festivals.
    """
    slug = deity_slug.strip().lower()
    if slug not in DEITY_REGISTRY:
        raise HTTPException(status_code=404, detail="Deity not found")
        
    info = DEITY_REGISTRY[slug]
    deity_name_lower = info["name"].lower()
    
    stmt = (
        select(Temple)
        .join(TempleProfile, Temple.id == TempleProfile.temple_id)
        .options(
            selectinload(Temple.profile),
            selectinload(Temple.website_settings_live),
            selectinload(Temple.images)
        )
        .filter(
            Temple.is_active == True,
            Temple.status == "APPROVED",
            Temple.directory_status == "ACTIVE",
            sa.or_(
                sa.func.lower(TempleProfile.main_deity).like(f"%{deity_name_lower}%"),
                sa.func.lower(TempleProfile.deities).like(f"%{deity_name_lower}%")
            )
        )
        .limit(10)
    )
    res = await db.execute(stmt)
    temples = res.scalars().all()
    
    associated_temples = []
    temple_ids = []
    for t in temples:
        temple_ids.append(t.id)
        resolved_img = resolve_temple_image(t)
        variants = get_image_variants(resolved_img)
        claim_status = await resolve_claim_status(db, t)
        
        associated_temples.append({
            "id": str(t.id),
            "name": t.name,
            "slug": t.domain,
            "location": t.profile.location or "",
            "district": t.profile.district or "",
            "state": t.profile.state or "",
            "image_url": resolved_img,
            "image_variants": variants,
            "claim_status": claim_status,
            "management_mode": t.management_mode,
            "verification_level": t.verification_level
        })
        
    associated_festivals = []
    if temple_ids:
        today = datetime.now(timezone.utc).date()
        fest_stmt = (
            select(TempleFestival)
            .join(Temple, TempleFestival.temple_id == Temple.id)
            .options(joinedload(TempleFestival.temple))
            .filter(
                TempleFestival.is_active == True,
                TempleFestival.start_date >= today,
                TempleFestival.temple_id.in_(temple_ids)
            )
            .order_by(TempleFestival.start_date.asc())
            .limit(5)
        )
        fest_res = await db.execute(fest_stmt)
        for f in fest_res.scalars().all():
            associated_festivals.append({
                "id": str(f.id),
                "name": f.name,
                "description": f.description or "",
                "start_date": f.start_date.isoformat(),
                "end_date": f.end_date.isoformat(),
                "temple_name": f.temple.name if f.temple else "",
                "temple_slug": f.temple.domain if f.temple else ""
            })
            
    return {
        "slug": slug,
        "name": info["name"],
        "description": info["description"],
        "related_deities": info["related"],
        "temples": associated_temples,
        "festivals": associated_festivals
    }


@public_router.get("/search/suggest", response_model=List[dict])
async def search_suggestions(
    q: str = Query("", min_length=1),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns autocomplete suggestions categorized by type and ranked by prefix matching rules.
    """
    clean_q = q.strip().lower()
    if not clean_q:
        return []

    exact_temple_stmt = (
        select(Temple)
        .outerjoin(TempleProfile, Temple.id == TempleProfile.temple_id)
        .options(selectinload(Temple.profile))
        .filter(Temple.is_active == True, Temple.status == "APPROVED", Temple.directory_status == "ACTIVE")
        .filter(sa.func.lower(Temple.name) == clean_q)
        .limit(10)
    )
    exact_res = await db.execute(exact_temple_stmt)
    exact_temples = exact_res.scalars().all()

    prefix_temple_stmt = (
        select(Temple)
        .outerjoin(TempleProfile, Temple.id == TempleProfile.temple_id)
        .options(selectinload(Temple.profile))
        .filter(Temple.is_active == True, Temple.status == "APPROVED", Temple.directory_status == "ACTIVE")
        .filter(sa.func.lower(Temple.name).like(f"{clean_q}%"))
        .filter(sa.func.lower(Temple.name) != clean_q)
        .limit(10)
    )
    prefix_res = await db.execute(prefix_temple_stmt)
    prefix_temples = prefix_res.scalars().all()

    deity_stmt = (
        select(TempleProfile.main_deity)
        .join(Temple, TempleProfile.temple_id == Temple.id)
        .filter(Temple.is_active == True, Temple.status == "APPROVED", Temple.directory_status == "ACTIVE")
        .filter(sa.func.lower(TempleProfile.main_deity).like(f"%{clean_q}%"))
        .distinct()
        .limit(10)
    )
    deity_res = await db.execute(deity_stmt)
    deities = [row[0] for row in deity_res.all() if row[0]]

    festival_stmt = (
        select(TempleFestival)
        .join(Temple, TempleFestival.temple_id == Temple.id)
        .options(joinedload(TempleFestival.temple))
        .filter(TempleFestival.is_active == True)
        .filter(Temple.is_active == True, Temple.status == "APPROVED", Temple.directory_status == "ACTIVE")
        .filter(sa.func.lower(TempleFestival.name).like(f"%{clean_q}%"))
        .limit(10)
    )
    festival_res = await db.execute(festival_stmt)
    festivals = festival_res.scalars().all()

    state_stmt = (
        select(StateMaster.name)
        .filter(sa.func.lower(StateMaster.name).like(f"%{clean_q}%"))
        .distinct()
        .limit(10)
    )
    state_res = await db.execute(state_stmt)
    states = [row[0] for row in state_res.all() if row[0]]

    suggestions = []

    for t in exact_temples:
        suggestions.append({
            "type": "TEMPLE",
            "value": t.name,
            "metadata": {"slug": t.domain, "id": str(t.id), "state": t.profile.state if t.profile else ""}
        })

    for t in prefix_temples:
        if len(suggestions) >= 10:
            break
        suggestions.append({
            "type": "TEMPLE",
            "value": t.name,
            "metadata": {"slug": t.domain, "id": str(t.id), "state": t.profile.state if t.profile else ""}
        })

    for d in deities:
        if len(suggestions) >= 10:
            break
        suggestions.append({
            "type": "DEITY",
            "value": d.title(),
            "metadata": {}
        })

    for f in festivals:
        if len(suggestions) >= 10:
            break
        suggestions.append({
            "type": "FESTIVAL",
            "value": f.name,
            "metadata": {"temple_name": f.temple.name if f.temple else "", "temple_slug": f.temple.domain if f.temple else ""}
        })

    for s in states:
        if len(suggestions) >= 10:
            break
        suggestions.append({
            "type": "STATE",
            "value": s,
            "metadata": {}
        })

    return suggestions[:10]

