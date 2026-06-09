"""
Service Recommendation Service — CRUD and resolution logic.
"""
import logging
from uuid import UUID
from typing import Optional, List
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
