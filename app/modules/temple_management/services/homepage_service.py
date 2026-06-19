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
    async def resolve_claim_status(cls, db: AsyncSession, temple: Temple) -> str:
        if temple.management_mode == "SELF_MANAGED":
            return "CLAIMED"
        if temple.management_mode == "GOVERNED":
            return "GOVERNED"
        if temple.verification_level == 3:
            return "OFFICIAL"
        if temple.verification_level == 2:
            return "CLAIMED"
            
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
        trending_scores: Dict[UUID, float] = None
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
            # Trending sorts will be scored inside Python using trending_scores maps to satisfy normalization requirement
            pass
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
            claim_badge = await cls.resolve_claim_status(db, temple)
            
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
        stmt = (
            select(TempleProfile.state, sa.func.count(Temple.id).label("temple_count"))
            .join(Temple, Temple.id == TempleProfile.temple_id)
            .join(TempleWebsiteSettingsLive, Temple.id == TempleWebsiteSettingsLive.temple_id)
            .filter(Temple.is_active == True, Temple.status == "APPROVED", Temple.directory_status == "ACTIVE")
            .filter(TempleProfile.state != None, TempleProfile.state != "")
            .group_by(TempleProfile.state)
            .order_by(TempleProfile.state.asc())
        )
        result = await db.execute(stmt)
        rows = result.all()
        return [{"state": r.state, "temple_count": r.temple_count} for r in rows]

    @classmethod
    async def calculate_trending_scores(cls, db: AsyncSession, followers_map: Dict[UUID, int]) -> Dict[UUID, float]:
        """
        Rank trending temples over the last 7 days using normalized signals.
        Score = 40% Views + 30% Searches + 20% Followers + 10% Activities
        """
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        
        # 1. Bulk query view and search events in the last 7 days
        event_stmt = (
            select(
                PortalAnalyticsEvent.temple_id,
                PortalAnalyticsEvent.event_name,
                sa.func.count(PortalAnalyticsEvent.id).label("count")
            )
            .filter(PortalAnalyticsEvent.created_at >= seven_days_ago)
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
    async def get_temple_spotlight(cls, db: AsyncSession, followers_map: Dict[UUID, int], trending_scores: Dict[UUID, float]) -> Optional[Dict[str, Any]]:
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
            claim_badge = await cls.resolve_claim_status(db, t)
            
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
        
        # 2. Calculate trending scores
        trending_scores = await cls.calculate_trending_scores(db, followers_map)
        
        popular_searches = ["Sabarimala", "Guruvayur", "Tirupati", "Meenakshi", "Kedarnath", "Puri Jagannath"]
        
        featured = await cls.get_temples_by_category(db, "FEATURED", limit=6, followers_map=followers_map)
        trending = await cls.get_temples_by_category(db, "TRENDING", limit=6, followers_map=followers_map, trending_scores=trending_scores)
        recently_added = await cls.get_temples_by_category(db, "RECENTLY_ADDED", limit=12, followers_map=followers_map)
        upcoming_festivals = await cls.get_upcoming_festivals(db, limit=10, followers_map=followers_map)
        states = await cls.get_states_directory(db)
        spotlight = await cls.get_temple_spotlight(db, followers_map=followers_map, trending_scores=trending_scores)
        
        data = {
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
