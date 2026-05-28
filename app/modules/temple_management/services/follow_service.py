"""
Follow Service — Devotee follows/unfollows temples.
"""
import logging
from uuid import UUID
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from fastapi import HTTPException

from app.models.domain import TempleFollower, Temple

logger = logging.getLogger(__name__)


class FollowService:
    """Temple follow/unfollow operations."""

    @staticmethod
    async def follow_temple(db: AsyncSession, user_id: UUID, temple_id: UUID) -> TempleFollower:
        """Follow a temple."""
        # Check temple exists
        temple_result = await db.execute(select(Temple).filter(Temple.id == temple_id))
        temple = temple_result.scalars().first()
        if not temple:
            raise HTTPException(status_code=404, detail="Temple not found")

        # Check if already following
        existing = await db.execute(
            select(TempleFollower).filter(
                TempleFollower.user_id == user_id,
                TempleFollower.temple_id == temple_id,
            )
        )
        if existing.scalars().first():
            raise HTTPException(status_code=409, detail="Already following this temple")

        follower = TempleFollower(user_id=user_id, temple_id=temple_id)
        db.add(follower)
        await db.commit()
        await db.refresh(follower)

        logger.info("User %s followed temple %s", user_id, temple_id)
        return follower

    @staticmethod
    async def unfollow_temple(db: AsyncSession, user_id: UUID, temple_id: UUID) -> dict:
        """Unfollow a temple."""
        result = await db.execute(
            select(TempleFollower).filter(
                TempleFollower.user_id == user_id,
                TempleFollower.temple_id == temple_id,
            )
        )
        follower = result.scalars().first()
        if not follower:
            raise HTTPException(status_code=404, detail="Not following this temple")

        await db.delete(follower)
        await db.commit()

        logger.info("User %s unfollowed temple %s", user_id, temple_id)
        return {"message": "Unfollowed successfully"}

    @staticmethod
    async def is_following(db: AsyncSession, user_id: UUID, temple_id: UUID) -> bool:
        """Check if user follows a temple."""
        result = await db.execute(
            select(TempleFollower).filter(
                TempleFollower.user_id == user_id,
                TempleFollower.temple_id == temple_id,
            )
        )
        return result.scalars().first() is not None

    @staticmethod
    async def get_followed_temples(db: AsyncSession, user_id: UUID) -> list:
        """Get all temples followed by a user."""
        result = await db.execute(
            select(TempleFollower)
            .filter(TempleFollower.user_id == user_id)
            .order_by(TempleFollower.created_at.desc())
        )
        followers = result.scalars().all()

        enriched = []
        for f in followers:
            temple_result = await db.execute(select(Temple).filter(Temple.id == f.temple_id))
            temple = temple_result.scalars().first()
            enriched.append({
                "id": f.id,
                "temple_id": f.temple_id,
                "temple_name": temple.name if temple else "",
                "temple_location": temple.location if temple else "",
                "created_at": f.created_at,
            })

        return enriched

    @staticmethod
    async def get_follower_count(db: AsyncSession, temple_id: UUID) -> int:
        """Get the number of followers for a temple."""
        result = await db.execute(
            select(func.count()).select_from(TempleFollower).filter(
                TempleFollower.temple_id == temple_id
            )
        )
        return result.scalar() or 0
