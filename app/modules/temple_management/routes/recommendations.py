"""
Service Recommendations Manager Endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.core.database.deps import get_db, get_current_temple_id, get_current_temple_manager
from app.schemas.domain import TokenData
from app.modules.temple_management.schemas.recommendation import (
    ServiceRecommendationCreate,
    ServiceRecommendationUpdate,
    ServiceRecommendationResponse,
)
from app.modules.temple_management.services.recommendation_service import RecommendationService

router = APIRouter(prefix="/recommendations")


@router.post("", response_model=ServiceRecommendationResponse)
async def create_recommendation(
    *,
    db: AsyncSession = Depends(get_db),
    payload: ServiceRecommendationCreate,
    current_user: TokenData = Depends(get_current_temple_manager),
    temple_id_str: str = Depends(get_current_temple_id),
):
    temple_id = UUID(temple_id_str)
    return await RecommendationService.create_recommendation(
        db=db, temple_id=temple_id, payload=payload
    )


@router.get("", response_model=List[ServiceRecommendationResponse])
async def list_recommendations(
    *,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_temple_manager),
    temple_id_str: str = Depends(get_current_temple_id),
):
    temple_id = UUID(temple_id_str)
    return await RecommendationService.list_recommendations(db=db, temple_id=temple_id)


@router.get("/{recommendation_id}", response_model=ServiceRecommendationResponse)
async def get_recommendation(
    recommendation_id: UUID,
    *,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_temple_manager),
    temple_id_str: str = Depends(get_current_temple_id),
):
    temple_id = UUID(temple_id_str)
    return await RecommendationService.get_recommendation(
        db=db, temple_id=temple_id, recommendation_id=recommendation_id
    )


@router.patch("/{recommendation_id}", response_model=ServiceRecommendationResponse)
async def update_recommendation(
    recommendation_id: UUID,
    *,
    db: AsyncSession = Depends(get_db),
    payload: ServiceRecommendationUpdate,
    current_user: TokenData = Depends(get_current_temple_manager),
    temple_id_str: str = Depends(get_current_temple_id),
):
    temple_id = UUID(temple_id_str)
    return await RecommendationService.update_recommendation(
        db=db, temple_id=temple_id, recommendation_id=recommendation_id, payload=payload
    )


@router.delete("/{recommendation_id}")
async def delete_recommendation(
    recommendation_id: UUID,
    *,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_temple_manager),
    temple_id_str: str = Depends(get_current_temple_id),
):
    temple_id = UUID(temple_id_str)
    return await RecommendationService.delete_recommendation(
        db=db, temple_id=temple_id, recommendation_id=recommendation_id
    )
