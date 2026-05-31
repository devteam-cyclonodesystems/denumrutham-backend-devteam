from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from uuid import UUID
from typing import Optional
from datetime import datetime, timezone
import logging

from app.schemas.domain import TempleUpdateFull
from app.services.superadmin_service import SuperAdminService

# Import other services and models if necessary:
# from app.services.hall_service import HallService
# from app.services.employee_service import EmployeeService

logger = logging.getLogger(__name__)

class ApprovalExecutor:
    """Safe Execution Layer validating payload and dispatching to services natively."""
    
    @staticmethod
    async def execute_module_action(
        db: AsyncSession, 
        module: str, 
        entity_id: str, 
        request_payload: dict,
        executed_by: Optional[str] = None,
    ):
        """Dispatches an approved payload safely mapped to service functions after dynamic Pydantic validation."""
        
        if module == "temples":
            try:
                # Schema mismatch triggers ValidationError
                valid_data = TempleUpdateFull(**request_payload)
            except Exception as e:
                logger.error(f"Schema validation failed for {module}: {str(e)}")
                raise ValueError("Payload schema validation failed.")
            
            # NEVER writes JSON directly. We call the service layer abstraction safely
            await SuperAdminService.update_temple(db, str(entity_id), valid_data, updated_by=executed_by)

        elif module == "hall_bookings_refund":
            from app.modules.bookings.models.booking_models import HallBooking, RefundHistory
            from app.services.hall_service import HallService
            
            # 1. Fetch the booking
            booking_res = await db.execute(
                select(HallBooking).filter(HallBooking.id == UUID(entity_id))
            )
            booking = booking_res.scalar_one_or_none()
            if not booking:
                raise ValueError("Booking not found")
                
            # 2. Process the refund via HallService (auto_commit=False is critical)
            amount = request_payload.get("amount")
            refund_method = request_payload.get("refund_method", "Cash")
            refund_status = request_payload.get("refund_status", "Full")
            reason = request_payload.get("reason", "")
            
            await HallService.process_refund(
                db=db,
                temple_id=str(booking.temple_id),
                booking_id=str(booking.id),
                amount=amount,
                refund_method=refund_method,
                refund_status=refund_status,
                reason=reason,
                user_id=executed_by,
                auto_commit=False,
            )
            
            # 3. Update the RefundHistory record
            refund_stmt = select(RefundHistory).filter(
                RefundHistory.booking_id == booking.id,
                RefundHistory.status == "PENDING"
            ).with_for_update()
            refund_res = await db.execute(refund_stmt)
            refund_hist = refund_res.scalar_one_or_none()
            if refund_hist:
                from decimal import Decimal
                refund_hist.status = "COMPLETED"
                refund_hist.approved_by = UUID(executed_by) if executed_by else None
                refund_hist.processed_at = datetime.now(timezone.utc)
                refund_hist.amount_paid_after = Decimal(str(booking.amount_paid or 0.0))
                refund_hist.balance_after = Decimal(str(booking.amount or 0.0)) - Decimal(str(booking.amount_paid or 0.0))
                refund_hist.payment_status_after = booking.payment_status
                
            # 4. Update the Booking
            booking.refund_status = "COMPLETED"
            booking.has_pending_refund = False

        # Example blocks for scalability:
        # elif module == "halls": ...
        # elif module == "finance": ...
        # elif module == "hr": ...
        else:
            raise ValueError(f"No execution handler registered for module: {module}")
        
        logger.info(f"Safely executed approval block natively mapped to module {module} -> {entity_id}")

    @staticmethod
    async def execute_module_rejection(
        db: AsyncSession,
        module: str,
        entity_id: str,
        request_payload: dict,
        rejected_by: Optional[str] = None,
        remarks: Optional[str] = None,
    ):
        """Dispatches a rejected payload safely to update state locks and record governance events."""
        logger.info(f"Executing rejection block for module {module} -> {entity_id}")
        
        if module == "hall_bookings_refund":
            from app.modules.bookings.models.booking_models import HallBooking, RefundHistory
            from app.services.booking_audit_service import BookingAuditService
            
            # 1. Fetch the booking
            booking_res = await db.execute(
                select(HallBooking).filter(HallBooking.id == UUID(entity_id))
            )
            booking = booking_res.scalar_one_or_none()
            if not booking:
                raise ValueError("Booking not found")
                
            # 2. Update the RefundHistory record
            refund_stmt = select(RefundHistory).filter(
                RefundHistory.booking_id == booking.id,
                RefundHistory.status == "PENDING"
            ).with_for_update()
            refund_res = await db.execute(refund_stmt)
            refund_hist = refund_res.scalar_one_or_none()
            if refund_hist:
                refund_hist.status = "REJECTED"
                refund_hist.rejected_by = UUID(rejected_by) if rejected_by else None
                refund_hist.processed_at = datetime.now(timezone.utc)
                refund_hist.decision_reason = remarks
                
            # 3. Reset Booking refund locks
            booking.refund_status = "REJECTED"
            booking.has_pending_refund = False
            
            # 4. Audit trail
            await BookingAuditService.log_action(
                db=db,
                temple_id=str(booking.temple_id),
                booking_id=str(booking.id),
                action="REFUND_REJECTED",
                performed_by=rejected_by,
                new_values={"remarks": remarks}
            )
        else:
            # For other modules, no default rejection handler needed, just log
            logger.info(f"No specific rejection execution needed for module {module}")
