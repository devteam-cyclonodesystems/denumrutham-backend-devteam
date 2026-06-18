"""
Service Recommendation Service — CRUD and resolution logic.
"""
import logging
import math
import time
import json
import asyncio
from uuid import UUID
from typing import Optional, List
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from fastapi import HTTPException

from app.models.domain import ServiceRecommendation, TempleService, StoreProduct
from app.modules.temple_management.schemas.recommendation import (
    ServiceRecommendationCreate,
    ServiceRecommendationUpdate,
)

logger = logging.getLogger(__name__)

# Global caches to keep recommendations response time under 150ms
_followers_cache = {}
_followers_cache_time = 0.0


class RecommendationService:
    """Operations for service and product recommendations."""

    @staticmethod
    async def create_recommendation(
        db: AsyncSession, temple_id: UUID, payload: ServiceRecommendationCreate
    ) -> ServiceRecommendation:
        """Create a new recommendation relationship."""
        # 1. Enforce multi-tenant validation on source
        if payload.source_service_id:
            svc_res = await db.execute(
                select(TempleService).filter(
                    TempleService.id == payload.source_service_id,
                    TempleService.temple_id == temple_id
                )
            )
            if not svc_res.scalars().first():
                raise HTTPException(status_code=404, detail="Source service not found or unauthorized")
        elif payload.source_product_id:
            prod_res = await db.execute(
                select(StoreProduct).filter(
                    StoreProduct.id == payload.source_product_id,
                    StoreProduct.temple_id == temple_id
                )
            )
            if not prod_res.scalars().first():
                raise HTTPException(status_code=404, detail="Source product not found or unauthorized")

        # 2. Enforce multi-tenant validation on target
        if payload.recommended_service_id:
            svc_res = await db.execute(
                select(TempleService).filter(
                    TempleService.id == payload.recommended_service_id,
                    TempleService.temple_id == temple_id
                )
            )
            if not svc_res.scalars().first():
                raise HTTPException(status_code=404, detail="Recommended service not found or unauthorized")
        elif payload.recommended_product_id:
            prod_res = await db.execute(
                select(StoreProduct).filter(
                    StoreProduct.id == payload.recommended_product_id,
                    StoreProduct.temple_id == temple_id
                )
            )
            if not prod_res.scalars().first():
                raise HTTPException(status_code=404, detail="Recommended product not found or unauthorized")

        # 3. Check for duplicates
        dup_stmt = select(ServiceRecommendation).filter(
            ServiceRecommendation.temple_id == temple_id,
            ServiceRecommendation.source_service_id == payload.source_service_id,
            ServiceRecommendation.source_product_id == payload.source_product_id,
            ServiceRecommendation.recommended_service_id == payload.recommended_service_id,
            ServiceRecommendation.recommended_product_id == payload.recommended_product_id
        )
        dup_res = await db.execute(dup_stmt)
        if dup_res.scalars().first():
            raise HTTPException(status_code=409, detail="Recommendation relationship already exists")

        # 4. Create recommendation
        rec = ServiceRecommendation(
            temple_id=temple_id,
            source_service_id=payload.source_service_id,
            source_product_id=payload.source_product_id,
            recommendation_source_type=payload.recommendation_source_type,
            recommended_service_id=payload.recommended_service_id,
            recommended_product_id=payload.recommended_product_id,
            display_order=payload.display_order,
            is_active=payload.is_active,
        )
        db.add(rec)
        await db.commit()

        # Reload with selectinload to avoid lazy-loading validation errors
        stmt = (
            select(ServiceRecommendation)
            .filter(ServiceRecommendation.id == rec.id)
            .options(
                selectinload(ServiceRecommendation.recommended_service),
                selectinload(ServiceRecommendation.recommended_product),
            )
        )
        res = await db.execute(stmt)
        rec = res.scalars().first()

        logger.info(
            "Created recommendation %s for temple %s (source_type: %s)",
            rec.id,
            temple_id,
            payload.recommendation_source_type,
        )
        return rec

    @staticmethod
    async def list_recommendations(
        db: AsyncSession, temple_id: UUID
    ) -> List[ServiceRecommendation]:
        """List all recommendation configurations for a temple."""
        stmt = (
            select(ServiceRecommendation)
            .filter(ServiceRecommendation.temple_id == temple_id)
            .options(
                selectinload(ServiceRecommendation.recommended_service),
                selectinload(ServiceRecommendation.recommended_product),
            )
            .order_by(ServiceRecommendation.display_order.asc())
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def get_recommendation(
        db: AsyncSession, temple_id: UUID, recommendation_id: UUID
    ) -> ServiceRecommendation:
        """Retrieve a specific recommendation."""
        stmt = (
            select(ServiceRecommendation)
            .filter(
                ServiceRecommendation.id == recommendation_id,
                ServiceRecommendation.temple_id == temple_id,
            )
            .options(
                selectinload(ServiceRecommendation.recommended_service),
                selectinload(ServiceRecommendation.recommended_product),
            )
        )
        res = await db.execute(stmt)
        rec = res.scalars().first()
        if not rec:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        return rec

    @staticmethod
    async def update_recommendation(
        db: AsyncSession,
        temple_id: UUID,
        recommendation_id: UUID,
        payload: ServiceRecommendationUpdate,
    ) -> ServiceRecommendation:
        """Update a recommendation."""
        rec = await RecommendationService.get_recommendation(db, temple_id, recommendation_id)

        if payload.display_order is not None:
            rec.display_order = payload.display_order
        if payload.is_active is not None:
            rec.is_active = payload.is_active

        await db.commit()
        
        # Reload with selectinload to prevent lazy-loading validation errors
        stmt = (
            select(ServiceRecommendation)
            .filter(
                ServiceRecommendation.id == recommendation_id,
                ServiceRecommendation.temple_id == temple_id,
            )
            .options(
                selectinload(ServiceRecommendation.recommended_service),
                selectinload(ServiceRecommendation.recommended_product),
            )
        )
        res = await db.execute(stmt)
        rec = res.scalars().first()
        logger.info("Updated recommendation %s for temple %s", recommendation_id, temple_id)
        return rec

    @staticmethod
    async def delete_recommendation(
        db: AsyncSession, temple_id: UUID, recommendation_id: UUID
    ) -> dict:
        """Delete a recommendation configuration."""
        rec = await RecommendationService.get_recommendation(db, temple_id, recommendation_id)
        await db.delete(rec)
        await db.commit()
        logger.info("Deleted recommendation %s for temple %s", recommendation_id, temple_id)
        return {"message": "Recommendation configuration deleted successfully"}

    @staticmethod
    async def resolve_recommendations(
        db: AsyncSession,
        temple_id: UUID,
        service_id: Optional[UUID] = None,
        product_id: Optional[UUID] = None,
    ) -> List[ServiceRecommendation]:
        """Resolve active recommendations for a given service or product (< 200ms target)."""
        if service_id is None and product_id is None:
            return []

        stmt = select(ServiceRecommendation).filter(
            ServiceRecommendation.temple_id == temple_id,
            ServiceRecommendation.is_active == True,
        )

        if service_id is not None:
            stmt = stmt.filter(ServiceRecommendation.source_service_id == service_id)
        else:
            stmt = stmt.filter(ServiceRecommendation.source_product_id == product_id)

        # Preload relationships for lightning-fast resolution
        stmt = stmt.options(
            selectinload(ServiceRecommendation.recommended_service),
            selectinload(ServiceRecommendation.recommended_product),
        ).order_by(ServiceRecommendation.display_order.asc())

        res = await db.execute(stmt)
        return list(res.scalars().all())

    @classmethod
    async def get_temple_recommendations(
        cls,
        db: AsyncSession,
        user_id: Optional[UUID] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        state: Optional[str] = None,
        district: Optional[str] = None,
        limit: int = 6
    ) -> List[dict]:
        """Rules-based explainable recommendations cache proxy for anonymous requests (< 150ms)."""
        redis = None
        cache_key = None
        if not user_id:
            if lat is not None and lon is not None:
                cache_key = f"recommendations:geo:{round(lat, 1)}:{round(lon, 1)}"
            else:
                cache_key = f"recommendations:{state or 'null'}:{district or 'null'}"
            
            from app.services.broadcast_service import BroadcastService
            try:
                redis = await BroadcastService.get_redis()
                if redis:
                    cached = await asyncio.wait_for(redis.get(cache_key), timeout=0.1)
                    if cached:
                        logger.info("Anonymous recommendations cache hit")
                        return json.loads(cached)
            except Exception as e:
                logger.warning(f"Failed to read recommendations cache: {e}")

        # Compute recommendations
        recommended_temples = await cls._compute_recommendations(
            db, user_id=user_id, lat=lat, lon=lon, state=state, district=district, limit=limit
        )

        # Cache anonymous results
        if not user_id and redis and cache_key:
            try:
                await asyncio.wait_for(redis.set(cache_key, json.dumps(recommended_temples), ex=600), timeout=0.1)
                logger.info("Saved anonymous recommendations to cache")
            except Exception as e:
                logger.warning(f"Failed to write recommendations cache: {e}")

        return recommended_temples

    @classmethod
    async def _compute_recommendations(
        cls,
        db: AsyncSession,
        user_id: Optional[UUID] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        state: Optional[str] = None,
        district: Optional[str] = None,
        limit: int = 6
    ) -> List[dict]:
        from collections import Counter
        
        # 1. Initialize user affinity profiles
        followed_ids = set()
        user_deity_affinity = []
        user_district_affinity = []
        user_state_affinity = []
        
        if user_id:
            # Fetch user followed temples
            from app.modules.temple_management.models.temple_models import TempleFollower, TempleProfile
            from app.models.domain import Temple
            
            follow_stmt = (
                select(TempleFollower.temple_id, Temple.name, TempleProfile.state, TempleProfile.district, TempleProfile.main_deity)
                .join(Temple, Temple.id == TempleFollower.temple_id)
                .outerjoin(TempleProfile, TempleProfile.temple_id == Temple.id)
                .filter(TempleFollower.user_id == user_id, TempleFollower.is_active == True)
            )
            follow_res = await db.execute(follow_stmt)
            follows = follow_res.all()
            
            followed_deities = []
            followed_districts = []
            followed_states = []
            
            for row in follows:
                followed_ids.add(row.temple_id)
                if row.main_deity:
                    followed_deities.append(row.main_deity.strip().lower())
                if row.district:
                    followed_districts.append(row.district.strip().lower())
                if row.state:
                    followed_states.append(row.state.strip().lower())
                    
            # Fetch user viewed temples
            from app.modules.temple_management.models.temple_models import PortalAnalyticsEvent
            view_stmt = (
                select(PortalAnalyticsEvent.temple_id, TempleProfile.state, TempleProfile.district, TempleProfile.main_deity)
                .join(TempleProfile, TempleProfile.temple_id == PortalAnalyticsEvent.temple_id)
                .filter(PortalAnalyticsEvent.user_id == user_id, PortalAnalyticsEvent.event_name == "TEMPLE_VIEW")
                .order_by(PortalAnalyticsEvent.created_at.desc())
                .limit(20)
            )
            view_res = await db.execute(view_stmt)
            views = view_res.all()
            
            viewed_deities = []
            viewed_districts = []
            viewed_states = []
            
            for row in views:
                if row.main_deity:
                    viewed_deities.append(row.main_deity.strip().lower())
                if row.district:
                    viewed_districts.append(row.district.strip().lower())
                if row.state:
                    viewed_states.append(row.state.strip().lower())
                    
            # Combine followed + viewed (giving followed temples 3x weight)
            deity_counts = Counter(followed_deities * 3 + viewed_deities)
            district_counts = Counter(followed_districts * 3 + viewed_districts)
            state_counts = Counter(followed_states * 3 + viewed_states)
            
            user_deity_affinity = [item[0] for item in deity_counts.most_common(3)]
            user_district_affinity = [item[0] for item in district_counts.most_common(2)]
            user_state_affinity = [item[0] for item in state_counts.most_common(2)]

        # 2. Bulk fetch all candidate temples (active, approved, excluding followed)
        from app.models.domain import Temple
        from app.modules.temple_management.models.temple_models import TempleProfile, TempleFollower
        
        stmt = (
            select(Temple)
            .join(TempleProfile, Temple.id == TempleProfile.temple_id)
            .options(
                selectinload(Temple.profile)
            )
            .filter(Temple.is_active == True, Temple.status == "APPROVED", Temple.directory_status == "ACTIVE")
        )
        if followed_ids:
            stmt = stmt.filter(~Temple.id.in_(followed_ids))
            
        res = await db.execute(stmt)
        candidates = res.scalars().all()
        
        if not candidates:
            return []

        # 3. Bulk fetch follower counts (with 60-second in-memory cache)
        global _followers_cache, _followers_cache_time
        import time
        now_time = time.time()
        if not _followers_cache or now_time - _followers_cache_time > 60.0:
            follower_counts_stmt = (
                select(TempleFollower.temple_id, sa.func.count(TempleFollower.id))
                .filter(TempleFollower.is_active == True)
                .group_by(TempleFollower.temple_id)
            )
            follower_res = await db.execute(follower_counts_stmt)
            _followers_cache = {row[0]: row[1] for row in follower_res.all() if row[0]}
            _followers_cache_time = now_time
            
        followers_map = _followers_cache
        
        # 4. Fetch trending scores (read from cache if exists to keep under 150ms)
        trending_scores = {}
        try:
            from app.services.broadcast_service import BroadcastService
            redis = await BroadcastService.get_redis()
            if redis:
                cached_bootstrap = await asyncio.wait_for(redis.get("homepage_bootstrap"), timeout=0.05)
                if cached_bootstrap:
                    bootstrap_data = json.loads(cached_bootstrap)
                    for t in bootstrap_data.get("trending", []):
                        trending_scores[UUID(t["id"])] = t.get("trending_score", 0.0)
        except Exception:
            pass

        # If trending_scores mapping is empty, calculate a quick follower count baseline
        max_followers = max(followers_map.values()) if followers_map else 1
        if max_followers == 0: max_followers = 1
        
        # 5. Score candidates
        scored_candidates = []
        
        def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
            R = 6371.0
            dlat = math.radians(lat2 - lat1)
            dlon = math.radians(lon2 - lon1)
            a = (math.sin(dlat / 2) ** 2 +
                 math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            return R * c

        for t in candidates:
            profile = t.profile
            t_deity = profile.main_deity.strip().lower() if (profile and profile.main_deity) else ""
            t_district = profile.district.strip().lower() if (profile and profile.district) else ""
            t_state = profile.state.strip().lower() if (profile and profile.state) else ""
            
            score = 0.0
            reason = "Popular on Denumrutham"
            reason_code = "FOLLOWER_POPULARITY"
            
            # Follower popularity base score
            follower_count = followers_map.get(t.id, 0)
            score += (follower_count / max_followers) * 10.0
            
            # Trending score baseline
            t_trending = trending_scores.get(t.id, 0.0)
            score += t_trending * 15.0
            
            # Location check
            has_geo = (lat is not None and lon is not None and profile and profile.latitude is not None and profile.longitude is not None)
            distance = None
            if has_geo:
                distance = haversine_distance(lat, lon, profile.latitude, profile.longitude)
                
            # Apply affinity rules
            if user_id:
                # 1. Deity Affinity
                if t_deity and t_deity in user_deity_affinity:
                    score += 50.0 + (3 - user_deity_affinity.index(t_deity)) * 10.0
                    reason = f"Based on your interest in {t_deity.title()}"
                    reason_code = "DEITY_AFFINITY"
                # 2. Location proximity (user logged in + geo)
                elif has_geo and distance <= 50.0:
                    score += 40.0 - (distance / 5.0)
                    reason = "Popular near you"
                    reason_code = "LOCATION_PROXIMITY"
                # 3. Trending in state affinity
                elif t_state and t_state in user_state_affinity:
                    score += 30.0 + t_trending * 10.0
                    reason = f"Trending in {profile.state}"
                    reason_code = "TRENDING_STATE"
                # 4. Trending globally fallback
                elif t_trending > 0.1:
                    score += 20.0 + t_trending * 10.0
                    reason = "Trending globally"
                    reason_code = "TRENDING_GLOBAL"
            else:
                # Anonymous rules
                if has_geo and distance <= 50.0:
                    score += 50.0 - (distance / 5.0)
                    reason = "Popular near you"
                    reason_code = "LOCATION_PROXIMITY"
                elif t_trending > 0.1:
                    score += 30.0 + t_trending * 20.0
                    reason = "Trending globally"
                    reason_code = "TRENDING_GLOBAL"
                elif state and t_state == state.strip().lower():
                    score += 20.0 + t_trending * 10.0
                    reason = f"Trending in {profile.state}"
                    reason_code = "TRENDING_STATE"
                    
            scored_candidates.append({
                "temple": t,
                "score": score,
                "reason": reason,
                "reason_code": reason_code,
                "deity": t_deity,
                "state": t_state,
                "follower_count": follower_count,
                "distance": distance
            })
            
        # 6. Sort and apply diversity selection
        scored_candidates.sort(key=lambda x: x["score"], reverse=True)
        
        temp_selections = []
        selected_deities = {}
        selected_states = {}
        
        for item in scored_candidates:
            if len(temp_selections) >= limit:
                break
                
            t = item["temple"]
            deity = item["deity"]
            t_state = item["state"]
            
            # Soft diversification: limit same deity to max 2, same state to max 3
            if deity and selected_deities.get(deity, 0) >= 2:
                # Skip to preserve diversity, unless we don't have enough candidates
                if len(temp_selections) + (len(scored_candidates) - scored_candidates.index(item)) >= limit:
                    continue
            if t_state and selected_states.get(t_state, 0) >= 3:
                if len(temp_selections) + (len(scored_candidates) - scored_candidates.index(item)) >= limit:
                    continue
                    
            selected_deities[deity] = selected_deities.get(deity, 0) + 1
            selected_states[t_state] = selected_states.get(t_state, 0) + 1
            temp_selections.append(item)
            
        selected = []
        if temp_selections:
            selected_ids = [item["temple"].id for item in temp_selections]
            full_stmt = (
                select(Temple)
                .options(
                    selectinload(Temple.profile),
                    selectinload(Temple.website_settings_live),
                    selectinload(Temple.images)
                )
                .filter(Temple.id.in_(selected_ids))
            )
            full_res = await db.execute(full_stmt)
            full_temples = {t.id: t for t in full_res.scalars().all()}
            
            for item in temp_selections:
                t = full_temples.get(item["temple"].id, item["temple"])
                
                from app.modules.temple_management.services.homepage_service import HomepageService
                resolved_img = HomepageService.resolve_temple_image(t)
                variants = HomepageService.get_image_variants(resolved_img)
                claim_status = await HomepageService.resolve_claim_status(db, t)
                
                selected.append({
                    "id": str(t.id),
                    "name": t.name,
                    "slug": t.domain,
                    "location": t.profile.location or "" if t.profile else "",
                    "district": t.profile.district or "" if t.profile else "",
                    "state": t.profile.state or "" if t.profile else "",
                    "image_url": resolved_img,
                    "image_variants": variants,
                    "claim_status": claim_status,
                    "management_mode": t.management_mode,
                    "verification_level": t.verification_level,
                    "follower_count": item["follower_count"],
                    "reason": item["reason"],
                    "reason_code": item["reason_code"]
                })
                
        return selected
