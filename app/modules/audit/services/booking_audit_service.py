import logging
from uuid import UUID
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.hall_booking import BookingAuditLog, BookingStatusHistory
from app.models.domain import utcnow

logger = logging.getLogger("tms.services.booking_audit")

class BookingAuditService:
    @staticmethod
    async def log_action(
        db: AsyncSession,
        temple_id: str,
        booking_id: str,
        action: str,
        performed_by: str = None,
        previous_values: dict = None,
        new_values: dict = None,
        ip_metadata: dict = None
    ) -> BookingAuditLog:
        """Log a generic action on a booking."""
        audit_log = BookingAuditLog(
            temple_id=UUID(str(temple_id)),
            booking_id=UUID(str(booking_id)),
            action=action,
            performed_by=UUID(str(performed_by)) if performed_by else None,
            previous_values=previous_values,
            new_values=new_values,
            ip_metadata=ip_metadata
        )
        db.add(audit_log)
        await db.flush()
        return audit_log

    @staticmethod
    async def log_status_change(
        db: AsyncSession,
        booking_id: str,
        old_status: str,
        new_status: str,
        changed_by: str = None,
        reason: str = None
    ) -> BookingStatusHistory:
        """Log a status transition."""
        status_log = BookingStatusHistory(
            booking_id=UUID(str(booking_id)),
            old_status=old_status,
            new_status=new_status,
            changed_by=UUID(str(changed_by)) if changed_by else None,
            reason=reason
        )
        db.add(status_log)
        await db.flush()
        return status_log
