import logging
from uuid import UUID
from datetime import datetime, date
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.hall_booking import BookingAuditLog, BookingStatusHistory
from app.models.domain import utcnow

logger = logging.getLogger("tms.services.booking_audit")

def _make_serializable(data):
    if data is None:
        return None
    if isinstance(data, dict):
        return {k: _make_serializable(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_make_serializable(v) for v in data]
    if isinstance(data, UUID):
        return str(data)
    if isinstance(data, (datetime, date)):
        return data.isoformat()
    return data

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
            previous_values=_make_serializable(previous_values),
            new_values=_make_serializable(new_values),
            ip_metadata=_make_serializable(ip_metadata)
        )
        db.add(audit_log)
        await db.flush()
        
        # Centralized Activity Logs integration
        try:
            from app.modules.audit.services.activity_log_service import ActivityLogService
            from app.models.domain import User
            from sqlalchemy.future import select
            
            perf_name = "System"
            perf_role = "SYSTEM"
            if performed_by:
                perf_uuid = UUID(str(performed_by))
                user_res = await db.execute(select(User).filter(User.id == perf_uuid))
                user_obj = user_res.scalar_one_or_none()
                if user_obj:
                    perf_name = user_obj.name
                    perf_role = user_obj.role or "STAFF"
            
            severity, risk_score = ActivityLogService.determine_risk_and_severity("BOOKINGS", action)
            
            await ActivityLogService.emit_event(
                db=db,
                temple_id=UUID(str(temple_id)),
                module_name="BOOKINGS",
                entity_name="Booking",
                entity_id=str(booking_id),
                action_type=action,
                action_category="BOOKING_OPERATION",
                description=f"Booking operation '{action}' performed",
                before_value=_make_serializable(previous_values),
                after_value=_make_serializable(new_values),
                performed_by_user_id=UUID(str(performed_by)) if performed_by else None,
                performed_by_name=perf_name,
                performed_by_role=perf_role,
                ip_address=ip_metadata.get("ip_address", "127.0.0.1") if isinstance(ip_metadata, dict) else "127.0.0.1",
                severity=severity,
                risk_score=risk_score
            )
        except Exception as e:
            logger.error(f"Failed to propagate booking audit log to centralized activity logs: {str(e)}", exc_info=True)
            
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
        
        # Centralized Activity Logs integration for status change
        try:
            from app.modules.audit.services.activity_log_service import ActivityLogService
            from app.models.domain import User, HallBooking
            from sqlalchemy.future import select
            
            b_uuid = UUID(str(booking_id))
            booking_res = await db.execute(select(HallBooking).filter(HallBooking.id == b_uuid))
            booking = booking_res.scalar_one_or_none()
            t_id = booking.temple_id if booking else None
            
            perf_name = "System"
            perf_role = "SYSTEM"
            if changed_by:
                perf_uuid = UUID(str(changed_by))
                user_res = await db.execute(select(User).filter(User.id == perf_uuid))
                user_obj = user_res.scalar_one_or_none()
                if user_obj:
                    perf_name = user_obj.name
                    perf_role = user_obj.role or "STAFF"
            
            severity, risk_score = ActivityLogService.determine_risk_and_severity("BOOKINGS", "STATUS_CHANGE")
            
            await ActivityLogService.emit_event(
                db=db,
                temple_id=t_id or UUID("00000000-0000-0000-0000-000000000000"),
                module_name="BOOKINGS",
                entity_name="Booking",
                entity_id=str(booking_id),
                action_type="STATUS_CHANGE",
                action_category="BOOKING_STATUS_UPDATE",
                description=reason or f"Booking status transitioned from {old_status} to {new_status}",
                before_value={"status": old_status},
                after_value={"status": new_status},
                performed_by_user_id=UUID(str(changed_by)) if changed_by else None,
                performed_by_name=perf_name,
                performed_by_role=perf_role,
                severity=severity,
                risk_score=risk_score
            )
        except Exception as e:
            logger.error(f"Failed to propagate booking status audit log to centralized activity logs: {str(e)}", exc_info=True)
            
        return status_log
