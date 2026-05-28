"""
Temple Follow Routes — Follow/unfollow temples, re-book from history.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import List

from app.core.database import get_db
from app.core.deps import get_current_user
from app.schemas.domain import TokenData
from app.schemas.follow import FollowTempleRequest, FollowedTempleResponse, FollowStatusResponse
from app.services.follow_service import FollowService
from app.core.response import api_response

router = APIRouter()


@router.post("/", status_code=201)
async def follow_temple(
    data: FollowTempleRequest,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Follow a temple for notifications and quick access."""
    follower = await FollowService.follow_temple(
        db, UUID(current_user.sub), data.temple_id
    )
    return api_response(
        data={"temple_id": str(data.temple_id)},
        message="Temple followed",
        status_code=201
    )


@router.delete("/{temple_id}")
async def unfollow_temple(
    temple_id: UUID,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Unfollow a temple."""
    await FollowService.unfollow_temple(db, UUID(current_user.sub), temple_id)
    return api_response(message="Temple unfollowed")


@router.get("/")
async def get_followed_temples(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all temples followed by the current user."""
    temples = await FollowService.get_followed_temples(db, UUID(current_user.sub))
    return api_response(data=[t.model_dump() if hasattr(t, 'model_dump') else t for t in temples], message="Followed temples retrieved")


@router.get("/check/{temple_id}")
async def check_follow_status(
    temple_id: UUID,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check if the current user follows a specific temple."""
    is_following = await FollowService.is_following(
        db, UUID(current_user.sub), temple_id
    )
    status_resp = FollowStatusResponse(is_following=is_following, temple_id=temple_id)
    return api_response(data=status_resp.model_dump() if hasattr(status_resp, 'model_dump') else status_resp, message="Follow status retrieved")


@router.get("/count/{temple_id}")
async def get_follower_count(
    temple_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get the follower count for a temple. Public endpoint."""
    count = await FollowService.get_follower_count(db, temple_id)
    return api_response(data={"temple_id": str(temple_id), "follower_count": count}, message="Follower count retrieved")
