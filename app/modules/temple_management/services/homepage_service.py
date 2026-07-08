import json
import logging
import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import (
    Temple, TempleWebsiteSettingsLive, StateMaster, DistrictMaster, TempleClaimRequest, PlatformGlobalSetting
)
from app.modules.temple_management.models.temple_models import (
    TempleImage, TempleProfile, TempleFestival, TempleFollower, PortalAnalyticsEvent
)
from app.services.broadcast_service import BroadcastService

logger = logging.getLogger("tms.homepage")

class HomepageService:
    _redis_unavailable_until = 0.0
    @staticmethod
    def resolve_temple_image(temple: Temple) -> str:
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

    @staticmethod
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

    @classmethod
    async def resolve_claim_status(cls, db: AsyncSession, temple: Temple, claims_map: Dict[UUID, bool] = None) -> str:
        if temple.verification_level == 3:
            return "OFFICIAL"
        if temple.management_mode in ("SELF_MANAGED", "GOVERNED"):
            return "CLAIMED"
        if temple.verification_level == 2:
            return "CLAIMED"
            
        if claims_map is not None:
            if claims_map.get(temple.id):
                return "CLAIM_PENDING"
            return "UNCLAIMED"
            
        stmt = (
            select(TempleClaimRequest)
            .filter(TempleClaimRequest.temple_id == temple.id, TempleClaimRequest.status == "PENDING")
        )
        res = await db.execute(stmt)
        if res.scalars().first():
            return "CLAIM_PENDING"
        return "UNCLAIMED"

    @classmethod
    async def get_temples_by_category(
        cls, 
        db: AsyncSession, 
        category: str, 
        limit: int = 6,
        followers_map: Dict[UUID, int] = None,
        trending_scores: Dict[UUID, float] = None,
        claims_map: Dict[UUID, bool] = None
    ) -> List[Dict[str, Any]]:
        # Avoid N+1 queries by fetching active followers and claims in bulk if possible,
        # but let's first load base temples query.
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
            if trending_scores:
                sorted_trending_ids = [k for k, v in sorted(trending_scores.items(), key=lambda item: item[1], reverse=True)[:limit]]
                if sorted_trending_ids:
                    stmt = stmt.filter(Temple.id.in_(sorted_trending_ids))
                else:
                    stmt = stmt.limit(limit)
            else:
                stmt = stmt.limit(limit)
        elif category == "RECENTLY_ADDED":
            stmt = stmt.order_by(Temple.created_at.desc())
        else:
            stmt = stmt.filter(Temple.is_featured == True)
            
        if category != "TRENDING":
            stmt = stmt.limit(limit)
            
        result = await db.execute(stmt)
        temples = result.scalars().all()
        
        # If FEATURED has less than limit, fill the slots
        if category == "FEATURED" and len(temples) < limit:
            needed = limit - len(temples)
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

        # Build items list
        items = []
        for temple in temples:
            profile = temple.profile
            resolved_img = cls.resolve_temple_image(temple)
            variants = cls.get_image_variants(resolved_img)
            claim_badge = await cls.resolve_claim_status(db, temple, claims_map=claims_map)
            
            # Resolve follower count from pre-fetched map or fallback
            follower_count = 0
            if followers_map is not None:
                follower_count = followers_map.get(temple.id, 0)
            else:
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
                "created_at": temple.created_at.date().isoformat() if temple.created_at else "",
                "trending_score": trending_scores.get(temple.id, 0.0) if trending_scores else 0.0
            })

        # Custom sorting for trending category
        if category == "TRENDING":
            items.sort(key=lambda x: x["trending_score"], reverse=True)
            items = items[:limit]
            
        return items

    @classmethod
    async def get_upcoming_festivals(cls, db: AsyncSession, limit: int = 10, followers_map: Dict[UUID, int] = None) -> List[Dict[str, Any]]:
        today = datetime.now(timezone.utc).date()
        thirty_days_later = today + timedelta(days=30)
        
        # Featured Festivals logic: starts within next 30 days, active temple
        stmt = (
            select(TempleFestival)
            .join(Temple, TempleFestival.temple_id == Temple.id)
            .options(joinedload(TempleFestival.temple))
            .filter(
                TempleFestival.is_active == True,
                TempleFestival.start_date >= today,
                TempleFestival.start_date <= thirty_days_later,
                Temple.is_active == True,
                Temple.status == "APPROVED",
                Temple.directory_status == "ACTIVE"
            )
            .order_by(TempleFestival.priority.desc(), TempleFestival.start_date.asc())
            .limit(100) # Prevents fetching thousands of records before Python-level sorting
        )
        result = await db.execute(stmt)
        festivals = result.scalars().all()
        
        # Map festivals with temple follower count for secondary ranking weight if needed,
        # and calculate countdown in days.
        items = []
        for f in festivals:
            days_left = (f.start_date - today).days
            follower_count = 0
            if followers_map and f.temple_id in followers_map:
                follower_count = followers_map[f.temple_id]
            
            items.append({
                "id": str(f.id),
                "temple_id": str(f.temple_id),
                "temple_name": f.temple.name if f.temple else "",
                "temple_slug": f.temple.domain if f.temple else "",
                "name": f.name,
                "description": f.description or "",
                "start_date": f.start_date.isoformat(),
                "end_date": f.end_date.isoformat(),
                "banner_image": f.banner_image or "",
                "days_left": days_left,
                "priority": f.priority,
                "follower_count": follower_count
            })
            
        # Secondary sort by temple popularity (follower count) for same-priority festivals
        items.sort(key=lambda x: (-x["priority"], x["days_left"], -x["follower_count"]))
        return items[:limit]

    @classmethod
    async def get_states_directory(cls, db: AsyncSession) -> List[Dict[str, Any]]:
        from app.models.domain import StateMaster
        
        stmt = (
            select(
                sa.func.coalesce(StateMaster.name, TempleProfile.state, Temple.state).label("state_name"),
                sa.func.count(Temple.id).label("temple_count")
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

    @classmethod
    async def calculate_trending_scores(cls, db: AsyncSession, followers_map: Dict[UUID, int]) -> Dict[UUID, float]:
        """
        Rank trending temples over the last 24 hours using normalized signals.
        Score = 40% Views + 30% Searches + 20% Followers + 10% Activities
        """
        one_day_ago = datetime.now(timezone.utc) - timedelta(days=1)
        
        # 1. Bulk query view and search events in the last 24 hours
        event_stmt = (
            select(
                PortalAnalyticsEvent.temple_id,
                PortalAnalyticsEvent.event_name,
                sa.func.count(PortalAnalyticsEvent.id).label("count")
            )
            .filter(PortalAnalyticsEvent.created_at >= one_day_ago)
            .group_by(PortalAnalyticsEvent.temple_id, PortalAnalyticsEvent.event_name)
        )
        event_res = await db.execute(event_stmt)
        
        views_map = {}
        searches_map = {}
        activity_map = {}
        
        for row in event_res.all():
            tid, ename, cnt = row.temple_id, row.event_name, row.count
            if not tid:
                continue
            if ename == "TEMPLE_VIEW":
                views_map[tid] = cnt
            elif ename == "TEMPLE_CARD_CLICK":
                searches_map[tid] = cnt
            else:
                activity_map[tid] = activity_map.get(tid, 0) + cnt
                
        # 2. Get list of all active temple IDs
        temple_stmt = select(Temple.id).filter(Temple.is_active == True, Temple.status == "APPROVED", Temple.directory_status == "ACTIVE")
        temple_res = await db.execute(temple_stmt)
        temple_ids = [row[0] for row in temple_res.all()]
        
        if not temple_ids:
            return {}
            
        # 3. Calculate max metrics for normalization
        max_views = max(views_map.values()) if views_map else 1
        max_searches = max(searches_map.values()) if searches_map else 1
        max_followers = max(followers_map.values()) if followers_map else 1
        max_activity = max(activity_map.values()) if activity_map else 1
        
        if max_views == 0: max_views = 1
        if max_searches == 0: max_searches = 1
        if max_followers == 0: max_followers = 1
        if max_activity == 0: max_activity = 1
        
        # 4. Score temples
        trending_scores = {}
        for tid in temple_ids:
            # Normalized signals (0-1 range)
            norm_views = views_map.get(tid, 0) / max_views
            norm_searches = searches_map.get(tid, 0) / max_searches
            norm_followers = followers_map.get(tid, 0) / max_followers
            norm_activity = activity_map.get(tid, 0) / max_activity
            
            # Weighted trending score calculation
            score = (0.4 * norm_views) + (0.3 * norm_searches) + (0.2 * norm_followers) + (0.1 * norm_activity)
            trending_scores[tid] = round(score, 4)
            
        return trending_scores

    @classmethod
    async def get_temple_spotlight(cls, db: AsyncSession, followers_map: Dict[UUID, int], trending_scores: Dict[UUID, float], claims_map: Dict[UUID, bool] = None) -> Optional[Dict[str, Any]]:
        """
        Highlight one temple according to the priority rules:
        1. Governance Configured Spotlight (from PlatformGlobalSetting "temple_spotlight_config")
        2. Featured Official Temple (is_featured = True, verification_level = 3)
        3. Highest Engagement Temple (highest follower count / trending score)
        4. Fallback Featured Temple
        """
        # Rule 1: Governance Configured Spotlight
        spotlight_stmt = select(PlatformGlobalSetting).filter(PlatformGlobalSetting.key == "temple_spotlight_config")
        spotlight_res = await db.execute(spotlight_stmt)
        spotlight_obj = spotlight_res.scalar_one_or_none()
        
        spotlight_id = None
        if spotlight_obj and spotlight_obj.value and isinstance(spotlight_obj.value, dict):
            spotlight_id_str = spotlight_obj.value.get("temple_id")
            if spotlight_id_str:
                try:
                    spotlight_id = UUID(spotlight_id_str)
                except ValueError:
                    pass
                    
        # Helper to retrieve detailed spotlight profile
        async def fetch_spotlight_details(temple_id: UUID) -> Optional[Dict[str, Any]]:
            stmt = (
                select(Temple)
                .outerjoin(TempleWebsiteSettingsLive, Temple.id == TempleWebsiteSettingsLive.temple_id)
                .outerjoin(TempleProfile, Temple.id == TempleProfile.temple_id)
                .options(
                    selectinload(Temple.profile),
                    selectinload(Temple.website_settings_live),
                    selectinload(Temple.images)
                )
                .filter(Temple.id == temple_id, Temple.is_active == True, Temple.status == "APPROVED", Temple.directory_status == "ACTIVE")
            )
            res = await db.execute(stmt)
            t = res.scalar_one_or_none()
            if not t:
                return None
            profile = t.profile
            resolved_img = cls.resolve_temple_image(t)
            variants = cls.get_image_variants(resolved_img)
            claim_badge = await cls.resolve_claim_status(db, t, claims_map=claims_map)
            
            return {
                "id": str(t.id),
                "name": t.name,
                "location": profile.location if profile else "",
                "district": profile.district if profile else "",
                "state": profile.state if profile else "",
                "slug": t.domain,
                "image_url": resolved_img,
                "hero_image_url": resolved_img,
                "image_variants": variants,
                "claim_status": claim_badge,
                "management_mode": t.management_mode,
                "verification_level": t.verification_level,
                "is_featured": t.is_featured,
                "follower_count": followers_map.get(t.id, 0),
                "description": profile.description if (profile and profile.description) else f"Experience the divine history and sacred offerings of {t.name}."
            }

        # Attempt to load configured temple
        if spotlight_id:
            spotlight_data = await fetch_spotlight_details(spotlight_id)
            if spotlight_data:
                return spotlight_data

        # Rule 2: Featured Official Temple (is_featured = True, verification_level = 3)
        featured_official_stmt = (
            select(Temple.id)
            .filter(Temple.is_active == True, Temple.status == "APPROVED", Temple.directory_status == "ACTIVE")
            .filter(Temple.is_featured == True, Temple.verification_level == 3)
            .limit(1)
        )
        res = await db.execute(featured_official_stmt)
        row = res.first()
        if row:
            spotlight_data = await fetch_spotlight_details(row[0])
            if spotlight_data:
                return spotlight_data

        # Rule 3: Highest Engagement Temple (highest trending score)
        if trending_scores:
            sorted_by_trending = sorted(trending_scores.items(), key=lambda x: x[1], reverse=True)
            if sorted_by_trending:
                best_id = sorted_by_trending[0][0]
                spotlight_data = await fetch_spotlight_details(best_id)
                if spotlight_data:
                    return spotlight_data

        # Rule 4: Fallback Featured Temple (is_featured = True)
        fallback_featured_stmt = (
            select(Temple.id)
            .filter(Temple.is_active == True, Temple.status == "APPROVED", Temple.directory_status == "ACTIVE")
            .filter(Temple.is_featured == True)
            .limit(1)
        )
        res = await db.execute(fallback_featured_stmt)
        row = res.first()
        if row:
            spotlight_data = await fetch_spotlight_details(row[0])
            if spotlight_data:
                return spotlight_data

        # Absolute Fallback: any active temple
        absolute_fallback_stmt = (
            select(Temple.id)
            .filter(Temple.is_active == True, Temple.status == "APPROVED", Temple.directory_status == "ACTIVE")
            .limit(1)
        )
        res = await db.execute(absolute_fallback_stmt)
        row = res.first()
        if row:
            return await fetch_spotlight_details(row[0])

        return None

    @classmethod
    async def get_homepage_data(cls, db: AsyncSession) -> Dict[str, Any]:
        cache_key = "homepage_bootstrap"
        redis = None
        now_ts = time.time()
        
        if now_ts > cls._redis_unavailable_until:
            try:
                redis = await BroadcastService.get_redis()
                if redis:
                    cached_data = await asyncio.wait_for(redis.get(cache_key), timeout=0.1)
                    if cached_data:
                        logger.info("Homepage data cache hit")
                        return json.loads(cached_data)
            except Exception as e:
                logger.warning(f"Failed to access Redis cache, disabling for 60s: {e}")
                cls._redis_unavailable_until = now_ts + 60.0
                redis = None

        # Cache miss or Redis unavailable, query DB in bulk
        logger.info("Homepage data cache miss - querying database")
        
        # 1. Bulk fetch follower counts to avoid N+1 queries
        follower_stmt = (
            select(TempleFollower.temple_id, sa.func.count(TempleFollower.id).label("count"))
            .filter(TempleFollower.is_active == True)
            .group_by(TempleFollower.temple_id)
        )
        follower_res = await db.execute(follower_stmt)
        followers_map = {row.temple_id: row.count for row in follower_res.all() if row.temple_id}
        
        # 1.5 Bulk fetch pending claims to avoid N+1
        claim_stmt = select(TempleClaimRequest.temple_id).filter(TempleClaimRequest.status == "PENDING")
        claim_res = await db.execute(claim_stmt)
        claims_map = {row[0]: True for row in claim_res.all() if row[0]}
        
        # 2. Calculate trending scores
        trending_scores = await cls.calculate_trending_scores(db, followers_map)
        
        popular_searches = ["Sabarimala", "Guruvayur", "Tirupati", "Meenakshi", "Kedarnath", "Puri Jagannath"]
        
        featured = await cls.get_temples_by_category(db, "FEATURED", limit=6, followers_map=followers_map, claims_map=claims_map)
        trending = await cls.get_temples_by_category(db, "TRENDING", limit=6, followers_map=followers_map, trending_scores=trending_scores, claims_map=claims_map)
        recently_added = await cls.get_temples_by_category(db, "RECENTLY_ADDED", limit=12, followers_map=followers_map, claims_map=claims_map)
        upcoming_festivals = await cls.get_upcoming_festivals(db, limit=10, followers_map=followers_map)
        states = await cls.get_states_directory(db)
        spotlight = await cls.get_temple_spotlight(db, followers_map=followers_map, trending_scores=trending_scores, claims_map=claims_map)
        
        # Fetch curated homepage layout with fallback protection
        layout_list = None
        try:
            layout_stmt = select(PlatformGlobalSetting).filter(PlatformGlobalSetting.key == "homepage_layout_live")
            layout_res = await db.execute(layout_stmt)
            layout_setting = layout_res.scalar_one_or_none()
            if layout_setting and layout_setting.value:
                if isinstance(layout_setting.value, dict):
                    layout_list = layout_setting.value.get("layout")
                elif isinstance(layout_setting.value, list):
                    layout_list = layout_setting.value
        except Exception as e:
            logger.warning(f"Failed to fetch homepage layout from database: {e}")
            
        if not layout_list or not isinstance(layout_list, list) or len(layout_list) == 0:
            layout_list = [
                {"key": "hero", "is_visible": True, "display_order": 0, "config": {}},
                {"key": "spotlight", "is_visible": True, "display_order": 1, "config": {}},
                {"key": "nearby", "is_visible": True, "display_order": 2, "config": {}},
                {"key": "featured", "is_visible": True, "display_order": 3, "config": {}},
                {"key": "trending", "is_visible": True, "display_order": 4, "config": {}},
                {"key": "festivals", "is_visible": True, "display_order": 5, "config": {}},
                {"key": "claim_cta", "is_visible": True, "display_order": 6, "config": {}},
                {"key": "recently_added", "is_visible": True, "display_order": 7, "config": {}},
                {"key": "directory", "is_visible": True, "display_order": 8, "config": {}}
            ]

        # Fetch and resolve homepage carousel slides
        carousel_slides = []
        try:
            carousel_stmt = select(PlatformGlobalSetting).filter(PlatformGlobalSetting.key == "homepage_carousel_live")
            carousel_res = await db.execute(carousel_stmt)
            carousel_setting = carousel_res.scalar_one_or_none()
            if carousel_setting and carousel_setting.value:
                if isinstance(carousel_setting.value, dict):
                    carousel_slides = carousel_setting.value.get("slides", [])
                elif isinstance(carousel_setting.value, list):
                    carousel_slides = carousel_setting.value
        except Exception as e:
            logger.warning(f"Failed to fetch homepage carousel from database: {e}")

        resolved_slides = []
        if carousel_slides:
            from uuid import uuid4
            # Gather references
            temple_ids = set()
            festival_ids = set()
            for slide in carousel_slides:
                if not isinstance(slide, dict):
                    continue
                stype = slide.get("type")
                if stype == "FEATURED_TEMPLE" and slide.get("temple_id"):
                    try:
                        temple_ids.add(UUID(str(slide["temple_id"])))
                    except ValueError:
                        pass
                elif stype == "FESTIVAL" and slide.get("festival_id"):
                    try:
                        festival_ids.add(UUID(str(slide["festival_id"])))
                    except ValueError:
                        pass

            # Bulk fetch temples
            temples_map = {}
            if temple_ids:
                t_stmt = (
                    select(Temple)
                    .outerjoin(TempleWebsiteSettingsLive, Temple.id == TempleWebsiteSettingsLive.temple_id)
                    .outerjoin(TempleProfile, Temple.id == TempleProfile.temple_id)
                    .options(
                        selectinload(Temple.profile),
                        selectinload(Temple.website_settings_live),
                        selectinload(Temple.images)
                    )
                    .filter(Temple.id.in_(temple_ids), Temple.is_active == True, Temple.status == "APPROVED")
                )
                t_res = await db.execute(t_stmt)
                for t in t_res.scalars().all():
                    temples_map[t.id] = t

            # Bulk fetch festivals
            festivals_map = {}
            if festival_ids:
                f_stmt = (
                    select(TempleFestival)
                    .join(Temple, TempleFestival.temple_id == Temple.id)
                    .options(joinedload(TempleFestival.temple))
                    .filter(TempleFestival.id.in_(festival_ids), TempleFestival.is_active == True)
                )
                f_res = await db.execute(f_stmt)
                for f in f_res.scalars().all():
                    festivals_map[f.id] = f

            # Resolve slide by slide
            for slide in carousel_slides:
                if not isinstance(slide, dict):
                    continue
                stype = slide.get("type")
                resolved_slide = {
                    "id": slide.get("id") or str(uuid4()),
                    "type": stype,
                    "is_active": slide.get("is_active", True)
                }

                if not resolved_slide["is_active"]:
                    continue

                if stype == "FEATURED_TEMPLE":
                    try:
                        tid = UUID(str(slide.get("temple_id")))
                    except (ValueError, TypeError):
                        continue
                    temple = temples_map.get(tid)
                    if not temple:
                        continue

                    profile = temple.profile
                    resolved_img = cls.resolve_temple_image(temple)
                    if not resolved_img:
                        resolved_img = "/static/default-temple.jpg"

                    location_str = ""
                    if profile:
                        parts = [p for p in [profile.district, profile.state] if p]
                        location_str = ", ".join(parts)

                    resolved_slide.update({
                        "temple_id": str(temple.id),
                        "title": temple.name,
                        "subtitle": location_str or "Divine Temple Experience",
                        "image_url": resolved_img,
                        "image_urls": slide.get("image_urls") or [resolved_img],
                        "target_url": f"/{temple.domain}/portal"
                    })

                elif stype == "FESTIVAL":
                    try:
                        fid = UUID(str(slide.get("festival_id")))
                    except (ValueError, TypeError):
                        continue
                    festival = festivals_map.get(fid)
                    if not festival:
                        continue

                    temple = festival.temple
                    resolved_img = festival.banner_image
                    if not resolved_img and temple:
                        resolved_img = cls.resolve_temple_image(temple)
                    if not resolved_img:
                        resolved_img = "/static/default-temple.jpg"

                    subtitle_str = f"Festival at {temple.name}" if temple else "Sacred Festival Celebration"
                    if festival.start_date:
                        subtitle_str += f" starting {festival.start_date.isoformat()}"

                    resolved_slide.update({
                        "festival_id": str(festival.id),
                        "temple_id": str(temple.id) if temple else None,
                        "title": festival.name,
                        "subtitle": subtitle_str,
                        "image_url": resolved_img,
                        "image_urls": slide.get("image_urls") or [resolved_img],
                        "target_url": f"/{temple.domain}/portal" if temple else "/temples"
                    })

                elif stype in ("CUSTOM", "AD"):
                    resolved_img = slide.get("image_url")
                    if not resolved_img:
                        resolved_img = "/static/default-temple.jpg"

                    resolved_slide.update({
                        "title": slide.get("title", "Spiritual Curation"),
                        "subtitle": slide.get("subtitle", ""),
                        "image_url": resolved_img,
                        "image_urls": slide.get("image_urls") or [resolved_img],
                        "target_url": slide.get("target_url") if slide.get("target_url") else None
                    })

                else:
                    continue

                resolved_slides.append(resolved_slide)
        
        data = {
            "layout": layout_list,
            "carousel": resolved_slides,
            "popular_searches": popular_searches,
            "featured": featured,
            "trending": trending,
            "recently_added": recently_added,
            "upcoming_festivals": upcoming_festivals,
            "states": states,
            "spotlight": spotlight
        }

        # Cache in Redis for 5 minutes
        if redis and now_ts > cls._redis_unavailable_until:
            try:
                await asyncio.wait_for(redis.set(cache_key, json.dumps(data), ex=300), timeout=0.1)
                logger.info("Saved homepage data to Redis cache")
            except Exception as e:
                logger.warning(f"Failed to write to Redis cache, disabling for 60s: {e}")
                cls._redis_unavailable_until = now_ts + 60.0

        return data
