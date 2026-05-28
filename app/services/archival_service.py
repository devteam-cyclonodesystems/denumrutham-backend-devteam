"""
Placeholder archival service for soft-deleted records.
Provides foundation for future scheduled archival jobs.
"""
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import update

from app.models.domain import User, Temple, Cart, Address, UserTemple

logger = logging.getLogger("tms.archival")

# Tables eligible for archival
ARCHIVAL_TARGETS = [User, Temple, Cart, Address, UserTemple]

# Records inactive for more than this duration are archival candidates
ARCHIVAL_THRESHOLD_DAYS = 90


class ArchivalService:
    """Handles archival of soft-deleted records.

    Usage (future cron/background task):
        await ArchivalService.archive_stale_records(db)
    """

    @staticmethod
    async def get_archival_candidates(
        db: AsyncSession,
        threshold_days: int = ARCHIVAL_THRESHOLD_DAYS,
    ) -> dict:
        """Count records eligible for archival across all tables."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=threshold_days)
        summary = {}
        for model in ARCHIVAL_TARGETS:
            if not hasattr(model, "is_active") or not hasattr(model, "deleted_at"):
                continue
            result = await db.execute(
                select(model).filter(
                    model.is_active == False,
                    model.deleted_at != None,
                    model.deleted_at < cutoff,
                )
            )
            count = len(result.scalars().all())
            summary[model.__tablename__] = count
        return summary

    @staticmethod
    async def archive_stale_records(
        db: AsyncSession,
        threshold_days: int = ARCHIVAL_THRESHOLD_DAYS,
    ) -> dict:
        """Mark stale soft-deleted records with archived_at timestamp.

        This is a placeholder: in production, these records would be
        moved to an archive table or cold storage.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=threshold_days)
        now = datetime.now(timezone.utc)
        results = {}

        for model in ARCHIVAL_TARGETS:
            if not hasattr(model, "deleted_at"):
                continue
            # For now, just log candidates — actual archival would
            # move rows to an archive schema or mark archived_at.
            result = await db.execute(
                select(model).filter(
                    model.is_active == False,
                    model.deleted_at != None,
                    model.deleted_at < cutoff,
                )
            )
            candidates = result.scalars().all()
            results[model.__tablename__] = len(candidates)

            if candidates:
                logger.info(
                    "Archival: %d records in '%s' eligible for archival",
                    len(candidates),
                    model.__tablename__,
                )

        return results
