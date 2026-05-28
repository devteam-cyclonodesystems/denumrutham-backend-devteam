"""
Temple Audit Query Service — Read-only access to temple status audit history.

Phase 3 Enhanced:
  - Pagination (limit, offset) with proper count queries
  - Date range filtering (date_from, date_to)
  - Sorting (desc by default, configurable)
  - Performant queries using indexed columns
"""
import logging
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, asc, func

from app.models.domain import TempleStatusAudit

logger = logging.getLogger(__name__)


class TempleAuditService:
    """Read-only service for temple status audit trail queries."""

    @staticmethod
    async def get_temple_audit_history(
        db: AsyncSession,
        temple_id: UUID,
        limit: int = 50,
        offset: int = 0,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        sort_order: str = "desc",
    ) -> dict:
        """
        Retrieve the full status change history for a temple.

        Args:
            db: Database session
            temple_id: Temple UUID to query
            limit: Max records to return (default 50, max 200)
            offset: Pagination offset
            date_from: Filter — only records after this datetime (inclusive)
            date_to: Filter — only records before this datetime (inclusive)
            sort_order: "desc" (default, newest first) or "asc" (oldest first)

        Returns:
            dict with "records" list, "total" count, pagination metadata
        """
        # Build base filter — uses index on temple_id
        base_filter = [TempleStatusAudit.temple_id == temple_id]

        # Date range filtering
        if date_from:
            base_filter.append(TempleStatusAudit.changed_at >= date_from)
        if date_to:
            base_filter.append(TempleStatusAudit.changed_at <= date_to)

        # Count total (performant — uses func.count instead of loading all rows)
        count_query = select(func.count(TempleStatusAudit.id)).filter(*base_filter)
        count_result = await db.execute(count_query)
        total = count_result.scalar() or 0

        # Sort order
        order_col = (
            desc(TempleStatusAudit.changed_at)
            if sort_order.lower() != "asc"
            else asc(TempleStatusAudit.changed_at)
        )

        # Fetch paginated records
        query = (
            select(TempleStatusAudit)
            .filter(*base_filter)
            .order_by(order_col)
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(query)
        records = result.scalars().all()

        items = [
            {
                "id": str(r.id),
                "temple_id": str(r.temple_id),
                "old_status": r.old_status,
                "new_status": r.new_status,
                "changed_by": str(r.changed_by) if r.changed_by else None,
                "changed_at": r.changed_at.isoformat() if r.changed_at else None,
                "reason": r.reason,
            }
            for r in records
        ]

        logger.info(
            "Fetched %d audit records for temple %s (total: %d, offset: %d)",
            len(items), temple_id, total, offset,
        )

        return {
            "records": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": (offset + limit) < total,
        }
