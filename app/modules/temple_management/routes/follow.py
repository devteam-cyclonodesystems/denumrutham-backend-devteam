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


from pydantic import BaseModel
class UpdateFollowerPreferencesRequest(BaseModel):
    push_enabled: bool
    festival_enabled: bool
    announcement_enabled: bool
    event_enabled: bool
    pooja_reminder_enabled: bool
    custom_categories: dict = {}


@router.get("/{temple_id}/preferences")
async def get_follower_preferences(
    temple_id: UUID,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Get notifications preferences for a temple follower, creating follower/preference record if needed."""
    # Check if already following
    is_following = await FollowService.is_following(db, UUID(current_user.sub), temple_id)
    if not is_following:
        follower = await FollowService.follow_temple(db, UUID(current_user.sub), temple_id)
    else:
        follower_res = await db.execute(
            select(TempleFollower).filter(
                TempleFollower.user_id == UUID(current_user.sub),
                TempleFollower.temple_id == temple_id
            )
        )
        follower = follower_res.scalars().first()

    if not follower:
        raise HTTPException(status_code=404, detail="Follower record not found")

    from app.models.domain import TempleFollowerPreference
    stmt = select(TempleFollowerPreference).filter(TempleFollowerPreference.follower_id == follower.id)
    res = await db.execute(stmt)
    pref = res.scalars().first()

    if not pref:
        pref = TempleFollowerPreference(
            follower_id=follower.id,
            push_enabled=True,
            festival_enabled=True,
            announcement_enabled=True,
            event_enabled=True,
            pooja_reminder_enabled=True,
            custom_categories={}
        )
        db.add(pref)
        await db.commit()
        await db.refresh(pref)

    return api_response(data={
        "push_enabled": pref.push_enabled,
        "festival_enabled": pref.festival_enabled,
        "announcement_enabled": pref.announcement_enabled,
        "event_enabled": pref.event_enabled,
        "pooja_reminder_enabled": pref.pooja_reminder_enabled,
        "custom_categories": pref.custom_categories
    }, message="Preferences retrieved")


@router.put("/{temple_id}/preferences")
async def update_follower_preferences(
    temple_id: UUID,
    data: UpdateFollowerPreferencesRequest,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update notifications preferences for a temple follower."""
    is_following = await FollowService.is_following(db, UUID(current_user.sub), temple_id)
    if not is_following:
        follower = await FollowService.follow_temple(db, UUID(current_user.sub), temple_id)
    else:
        follower_res = await db.execute(
            select(TempleFollower).filter(
                TempleFollower.user_id == UUID(current_user.sub),
                TempleFollower.temple_id == temple_id
            )
        )
        follower = follower_res.scalars().first()

    if not follower:
        raise HTTPException(status_code=404, detail="Follower record not found")

    from app.models.domain import TempleFollowerPreference
    stmt = select(TempleFollowerPreference).filter(TempleFollowerPreference.follower_id == follower.id)
    res = await db.execute(stmt)
    pref = res.scalars().first()

    if not pref:
        pref = TempleFollowerPreference(
            follower_id=follower.id,
            push_enabled=data.push_enabled,
            festival_enabled=data.festival_enabled,
            announcement_enabled=data.announcement_enabled,
            event_enabled=data.event_enabled,
            pooja_reminder_enabled=data.pooja_reminder_enabled,
            custom_categories=data.custom_categories
        )
        db.add(pref)
    else:
        pref.push_enabled = data.push_enabled
        pref.festival_enabled = data.festival_enabled
        pref.announcement_enabled = data.announcement_enabled
        pref.event_enabled = data.event_enabled
        pref.pooja_reminder_enabled = data.pooja_reminder_enabled
        pref.custom_categories = data.custom_categories

    await db.commit()
    return api_response(message="Preferences updated successfully")
