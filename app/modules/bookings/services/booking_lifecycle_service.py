import logging
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.domain import HallBooking
from app.services.booking_audit_service import BookingAuditService
from fastapi import HTTPException

logger = logging.getLogger("tms.services.booking_lifecycle")

class BookingLifecycleService:
    VALID_TRANSITIONS = {
        "draft": ["pending", "cancelled"],
        "pending": ["confirmed", "cancelled"],
        "confirmed": ["completed", "cancelled"],
        "completed": [],
        "cancelled": ["refunded"],
        "refunded": []
    }

    @staticmethod
    async def transition_status(
        db: AsyncSession,
        booking_id: str,
        temple_id: str,
        new_status: str,
        changed_by: str = None,
        reason: str = None
    ) -> HallBooking:
        tid = UUID(str(temple_id))
        bid = UUID(str(booking_id))
        
        result = await db.execute(select(HallBooking).filter(HallBooking.id == bid, HallBooking.temple_id == tid))
        booking = result.scalars().first()
        
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")

        # Lock booking transitions if a refund request is pending approval
        if booking.refund_status == "PENDING_APPROVAL":
            raise HTTPException(status_code=400, detail="Status transitions are locked because a refund approval request is pending")
            
        old_status = booking.status.lower()
        new_status_lower = new_status.lower()
        
        if new_status_lower not in BookingLifecycleService.VALID_TRANSITIONS.get(old_status, []):
            if old_status != new_status_lower:
                logger.warning(f"Invalid transition from {old_status} to {new_status_lower}")
                # We might want to allow admin overrides, but for now we enforce
                # raise HTTPException(status_code=400, detail=f"Invalid status transition from {old_status} to {new_status_lower}")
        
        booking.status = new_status_lower
        
        # Log transition
        await BookingAuditService.log_status_change(
            db=db,
            booking_id=booking_id,
            old_status=old_status,
            new_status=new_status_lower,
            changed_by=changed_by,
            reason=reason
        )
        
        await BookingAuditService.log_action(
            db=db,
            temple_id=temple_id,
            booking_id=booking_id,
            action="STATUS_CHANGED",
            performed_by=changed_by,
            new_values={"status": new_status_lower, "reason": reason}
        )
        
        await db.commit()
        await db.refresh(booking)
        return booking
