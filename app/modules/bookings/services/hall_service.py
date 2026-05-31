"""Hall Service — Hall CRUD + HallBooking with automatic transaction creation."""
import logging
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from app.models.domain import Hall, HallBooking
from app.models.hall_booking import PaymentLedger, PaymentTransaction
from app.schemas.hall import HallCreate, HallUpdate, HallBookingCreate, HallBookingUpdate
from app.services.transaction_service import TransactionService
from app.services.booking_conflict_service import BookingConflictService
from app.services.booking_pricing_service import PricingEngineService
from app.services.booking_lifecycle_service import BookingLifecycleService
from app.services.booking_audit_service import BookingAuditService
from fastapi import HTTPException

logger = logging.getLogger("tms.services.hall")


class HallService:

    @staticmethod
    async def create_hall(db: AsyncSession, hall_in: HallCreate, temple_id: str) -> Hall:
        tid = UUID(str(temple_id))
        hall = Hall(
            temple_id=tid,
            name=hall_in.name,
            capacity=hall_in.capacity,
            amenities=hall_in.amenities,
            price_per_day=hall_in.price_per_day,
            image_emoji=hall_in.image_emoji,
            status=hall_in.status,
        )
        db.add(hall)
        await db.commit()
        await db.refresh(hall)
        return hall

    @staticmethod
    async def get_halls(db: AsyncSession, temple_id: str):
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(Hall).filter(Hall.temple_id == tid, Hall.is_active == True).order_by(Hall.created_at)
        )
        return result.scalars().all()

    @staticmethod
    async def update_hall(db: AsyncSession, hall_id: str, update_in: HallUpdate, temple_id: str):
        hid = UUID(str(hall_id))
        tid = UUID(str(temple_id))
        
        result = await db.execute(select(Hall).filter(Hall.id == hid, Hall.temple_id == tid))
        hall = result.scalar_one_or_none()
        if not hall:
            return None
            
        update_data = update_in.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(hall, key, value)
            
        await db.commit()
        await db.refresh(hall)
        return hall

    @staticmethod
    async def delete_hall(db: AsyncSession, hall_id: str, temple_id: str):
        hid = UUID(str(hall_id))
        tid = UUID(str(temple_id))
        
        result = await db.execute(select(Hall).filter(Hall.id == hid, Hall.temple_id == tid))
        hall = result.scalar_one_or_none()
        if not hall:
            return False
            
        hall.is_active = False
        await db.commit()
        return True

    @staticmethod
    async def create_hall_booking(
        db: AsyncSession,
        booking_in: HallBookingCreate,
        temple_id: str,
        created_by: str = "Admin",
        user_id: str = None,
    ) -> HallBooking:
        tid = UUID(str(temple_id))

        # --- Phase 1: Overlap Prevention ---
        has_conflict = await BookingConflictService.check_conflict(
            db=db,
            temple_id=temple_id,
            hall_id=str(booking_in.hall_id),
            start_date=booking_in.date,
            start_time=booking_in.start_time,
            end_date=booking_in.end_date,
            end_time=booking_in.end_time
        )
        if has_conflict:
            raise HTTPException(status_code=409, detail="The hall is already booked or reserved for the selected time slot.")
            
        # --- Phase 5: Advanced Pricing Engine ---
        price_calc = await PricingEngineService.calculate_price(
            db=db,
            temple_id=temple_id,
            hall_id=str(booking_in.hall_id),
            base_amount=booking_in.amount,
            discount_amount=booking_in.discount_amount,
            booking_date=booking_in.date
        )
        final_amount = price_calc["final_amount"]

        # Generate ref number
        count_result = await db.execute(
            select(func.count(HallBooking.id)).filter(HallBooking.temple_id == tid)
        )
        count = count_result.scalar() or 0
        from datetime import datetime
        now = datetime.utcnow()
        mm = str(now.month).zfill(2)
        yy = str(now.year)[-2:]
        ref = f"HB{str(count + 1).zfill(3)}/{mm}{yy}"

        booking = HallBooking(
            temple_id=tid,
            hall_id=booking_in.hall_id,
            ref_number=ref,
            customer_name=booking_in.customer_name,
            address=booking_in.address,
            phone=booking_in.phone,
            date=booking_in.date,
            start_time=booking_in.start_time,
            end_date=booking_in.end_date,
            end_time=booking_in.end_time,
            purpose=booking_in.purpose,
            amount=final_amount,
            discount_amount=price_calc["discount_amount"],
            payment_type=booking_in.payment_type,
            amount_paid=booking_in.amount_paid,
            payment_mode=booking_in.payment_mode,
            booking_mode=booking_in.booking_mode,
            remarks=booking_in.remarks,
            status="pending",
            payment_status="PENDING" if booking_in.amount_paid < final_amount else "SUCCESS",
            created_by=created_by,
        )
        db.add(booking)
        await db.flush()
        
        # --- Phase 6: Payment Reconciliation System ---
        ledger = PaymentLedger(
            temple_id=tid,
            booking_id=booking.id,
            total_amount=final_amount,
            paid_amount=booking_in.amount_paid,
            due_amount=max(0, final_amount - booking_in.amount_paid),
            status="PARTIAL" if (booking_in.amount_paid > 0 and booking_in.amount_paid < final_amount) else ("COMPLETED" if booking_in.amount_paid >= final_amount else "PENDING")
        )
        db.add(ledger)
        await db.flush()
        
        if booking_in.amount_paid > 0:
            payment_txn = PaymentTransaction(
                temple_id=tid,
                ledger_id=ledger.id,
                transaction_type="PAYMENT",
                amount=booking_in.amount_paid,
                payment_mode=booking_in.payment_mode,
                status="SUCCESS"
            )
            db.add(payment_txn)
            
            # 🔥 TRANSACTION ENGINE: Auto-create income transaction
            await TransactionService.create_transaction(
                db=db,
                temple_id=temple_id,
                txn_type="income",
                category="hall_booking",
                amount=booking_in.amount_paid,
                description=f"Hall Booking advance - {booking_in.customer_name}",
                reference_id=ref,
                source="system",
            )
            
        # --- Phase 7: Audit Trail ---
        await BookingAuditService.log_action(
            db=db,
            temple_id=temple_id,
            booking_id=str(booking.id),
            action="CREATED",
            performed_by=user_id,
            new_values={"customer": booking.customer_name, "amount": final_amount}
        )
        await BookingAuditService.log_status_change(
            db=db,
            booking_id=str(booking.id),
            old_status="none",
            new_status="pending",
            changed_by=user_id
        )

        await db.commit()
        await db.refresh(booking)
        return booking

    @staticmethod
    async def get_hall_bookings(db: AsyncSession, temple_id: str, skip: int = 0, limit: int = 200):
        tid = UUID(str(temple_id))
        result = await db.execute(
            select(HallBooking)
            .filter(HallBooking.temple_id == tid)
            .order_by(HallBooking.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return result.scalars().all()

    @staticmethod
    async def update_hall_booking(
        db: AsyncSession, booking_id: str, update_in: HallBookingUpdate, temple_id: str, user_id: str = None
    ) -> HallBooking:
        tid = UUID(str(temple_id))
        bid = UUID(str(booking_id))
        result = await db.execute(
            select(HallBooking).filter(HallBooking.id == bid, HallBooking.temple_id == tid)
        )
        booking = result.scalars().first()
        if not booking:
            return None

        # Lock booking from updates if a refund request is pending approval
        if booking.refund_status == "PENDING_APPROVAL":
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Financial modifications are locked because a refund approval request is pending")

        update_data = update_in.model_dump(exclude_unset=True)
        
        # Payment tracking additions
        old_amount_paid = booking.amount_paid or 0.0
        new_amount_paid = update_data.get("amount_paid")

        # Capture old values for general audit log before applying updates
        old_values = {}
        for key in update_data.keys():
            old_values[key] = getattr(booking, key)

        # Recalculate final amount using PricingEngine if pricing-relevant fields are updated
        new_base_amount = update_data.get("amount")
        new_discount_amount = update_data.get("discount_amount")
        new_date = update_data.get("date")
        new_hall_id = update_data.get("hall_id")

        if any(v is not None for v in [new_base_amount, new_discount_amount, new_date, new_hall_id]):
            calc_base = new_base_amount if new_base_amount is not None else (booking.amount + booking.discount_amount)
            calc_discount = new_discount_amount if new_discount_amount is not None else booking.discount_amount
            calc_date = new_date if new_date is not None else booking.date
            calc_hall_id = str(new_hall_id) if new_hall_id is not None else str(booking.hall_id)

            price_calc = await PricingEngineService.calculate_price(
                db=db,
                temple_id=temple_id,
                hall_id=calc_hall_id,
                base_amount=calc_base,
                discount_amount=calc_discount,
                booking_date=calc_date
            )
            # Override with calculated values (amount stores final net amount)
            update_data["amount"] = price_calc["final_amount"]
            update_data["discount_amount"] = price_calc["discount_amount"]

        # Apply update attributes
        for key, value in update_data.items():
            setattr(booking, key, value)

        # Synchronize and update the ledger
        ledger_result = await db.execute(
            select(PaymentLedger).filter(PaymentLedger.booking_id == bid)
        )
        ledger = ledger_result.scalar_one_or_none()
        if ledger:
            ledger.total_amount = booking.amount
            if new_amount_paid is not None:
                ledger.paid_amount = new_amount_paid
            ledger.due_amount = max(0.0, ledger.total_amount - ledger.paid_amount)
            ledger.status = "COMPLETED" if ledger.due_amount <= 0 else ("PARTIAL" if ledger.paid_amount > 0 else "PENDING")

        # Process additional payment transaction and log if amount paid increased
        if new_amount_paid is not None:
            diff = new_amount_paid - old_amount_paid
            if diff > 0 and ledger:
                pay_mode = update_data.get("payment_mode") or booking.payment_mode or "Cash"
                payment_txn = PaymentTransaction(
                    temple_id=tid,
                    ledger_id=ledger.id,
                    transaction_type="PAYMENT",
                    amount=diff,
                    payment_mode=pay_mode,
                    status="SUCCESS"
                )
                db.add(payment_txn)
                
                await TransactionService.create_transaction(
                    db=db,
                    temple_id=str(temple_id),
                    txn_type="income",
                    category="hall_booking",
                    amount=diff,
                    description=f"Hall Booking due payment - {booking.customer_name}",
                    reference_id=booking.ref_number,
                    source="system"
                )
                
                await BookingAuditService.log_action(
                    db=db,
                    temple_id=temple_id,
                    booking_id=booking_id,
                    action="PAYMENT_ADDED",
                    performed_by=user_id,
                    new_values={"amount": diff, "payment_mode": pay_mode}
                )

        current_paid = booking.amount_paid or 0.0
        booking.payment_status = "SUCCESS" if (booking.amount - current_paid) <= 0 else ("PARTIAL" if current_paid > 0 else "PENDING")

        # Log general update action if not just a payment addition
        if update_data:
            await BookingAuditService.log_action(
                db=db,
                temple_id=temple_id,
                booking_id=booking_id,
                action="UPDATED",
                performed_by=user_id,
                previous_values=old_values,
                new_values=update_data
            )

        await db.commit()
        await db.refresh(booking)
        return booking

    @staticmethod
    async def get_booking_transactions(db: AsyncSession, booking_id: str, temple_id: str) -> list:
        tid = UUID(str(temple_id))
        bid = UUID(str(booking_id))
        
        # Get ledger
        ledger_result = await db.execute(
            select(PaymentLedger).filter(PaymentLedger.booking_id == bid, PaymentLedger.temple_id == tid)
        )
        ledger = ledger_result.scalar_one_or_none()
        if not ledger:
            return []
            
        # Get transactions
        txns_result = await db.execute(
            select(PaymentTransaction).filter(PaymentTransaction.ledger_id == ledger.id).order_by(PaymentTransaction.created_at.asc())
        )
        txns = txns_result.scalars().all()
        
        res = []
        for idx, tx in enumerate(txns):
            seq_names = ["1st", "2nd", "3rd"]
            seq = seq_names[idx] if idx < len(seq_names) else f"{idx + 1}th"
            res.append({
                "seq": seq,
                "id": str(tx.id),
                "transaction_type": tx.transaction_type,
                "amount": tx.amount,
                "payment_mode": tx.payment_mode,
                "status": tx.status,
                "created_at": tx.created_at.isoformat() if tx.created_at else None
            })
        return res

    @staticmethod
    async def cancel_hall_booking(db: AsyncSession, booking_id: str, temple_id: str, user_id: str = None) -> HallBooking:
        return await BookingLifecycleService.transition_status(db, booking_id, temple_id, "cancelled", changed_by=user_id)

    @staticmethod
    async def approve_hall_booking(db: AsyncSession, booking_id: str, temple_id: str, user_id: str = None) -> HallBooking:
        return await BookingLifecycleService.transition_status(db, booking_id, temple_id, "confirmed", changed_by=user_id)

    @staticmethod
    async def process_refund(
        db: AsyncSession,
        temple_id: str,
        booking_id: str,
        amount: float,
        refund_method: str = "Cash",
        refund_status: str = "Full",
        reason: str = "",
        user_id: str = None,
        auto_commit: bool = True,
    ) -> dict:
        """Process a refund for a hall booking."""
        tid = UUID(str(temple_id))
        bid = UUID(str(booking_id))
        from decimal import Decimal

        # Get the booking
        result = await db.execute(
            select(HallBooking).filter(HallBooking.id == bid, HallBooking.temple_id == tid)
        )
        booking = result.scalar_one_or_none()
        if not booking:
            return None

        # Validate refund amount (Phase 18: Decimal financial safety)
        amount_dec = Decimal(str(amount))
        amount_paid_dec = Decimal(str(booking.amount_paid or 0.0))
        if amount_dec > amount_paid_dec:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Refund amount exceeds paid amount")

        # Get or create payment ledger
        ledger_result = await db.execute(
            select(PaymentLedger).filter(PaymentLedger.booking_id == bid)
        )
        ledger = ledger_result.scalar_one_or_none()

        if ledger:
            ledger_total_dec = Decimal(str(ledger.total_amount or 0.0))
            ledger_refunded_dec = Decimal(str(ledger.refunded_amount or 0.0)) + amount_dec
            ledger_paid_dec = max(Decimal(0), Decimal(str(ledger.paid_amount or 0.0)) - amount_dec)
            
            ledger.refunded_amount = float(ledger_refunded_dec)
            ledger.paid_amount = float(ledger_paid_dec)
            ledger.due_amount = float(max(Decimal(0), ledger_total_dec - ledger_paid_dec))
            
            if ledger_refunded_dec >= ledger_total_dec:
                ledger.status = "REFUNDED"
            else:
                ledger.status = "PARTIAL"

            # Create refund transaction record
            refund_txn = PaymentTransaction(
                temple_id=tid,
                ledger_id=ledger.id,
                transaction_type="REFUND",
                amount=amount,
                payment_mode=refund_method,
                status="SUCCESS",
            )
            db.add(refund_txn)

        # Update booking status (both Full and Partial refunds decrement amount_paid)
        if refund_status == "Full":
            booking.status = "cancelled"
            booking.payment_status = "REFUNDED"
        else:
            booking.payment_status = "PARTIALLY_REFUNDED"
            
        booking.amount_paid = float(max(Decimal(0), amount_paid_dec - amount_dec))

        # Create expense transaction for accounting
        from datetime import datetime
        now = datetime.utcnow()
        ref = booking.ref_number or str(booking.id)[:8]
        await TransactionService.create_transaction(
            db=db,
            temple_id=temple_id,
            txn_type="expense",
            category="hall_booking",
            amount=amount,
            description=f"Hall Booking refund - {booking.customer_name} ({refund_status})",
            reference_id=ref,
            source="system",
        )

        # Audit trail
        await BookingAuditService.log_action(
            db=db,
            temple_id=temple_id,
            booking_id=booking_id,
            action="REFUND_PROCESSED",
            performed_by=user_id,
            new_values={"amount": amount, "method": refund_method, "type": refund_status, "reason": reason}
        )

        if auto_commit:
            await db.commit()
        else:
            await db.flush()

        return {
            "id": str(booking.id),
            "booking_id": booking_id,
            "amount": amount,
            "refund_method": refund_method,
            "refund_status": refund_status,
            "reason": reason,
            "status": "APPROVED",
            "created_at": now.isoformat(),
        }

    @staticmethod
    async def get_booking_audit_trail(db: AsyncSession, booking_id: str, temple_id: str) -> list:
        tid = UUID(str(temple_id))
        bid = UUID(str(booking_id))
        
        from app.models.hall_booking import BookingAuditLog
        from app.models.domain import User
        
        result = await db.execute(
            select(BookingAuditLog, User.name)
            .outerjoin(User, BookingAuditLog.performed_by == User.id)
            .filter(BookingAuditLog.booking_id == bid, BookingAuditLog.temple_id == tid)
            .order_by(BookingAuditLog.created_at.desc())
        )
        logs = result.all()
        
        res = []
        for log_row in logs:
            log = log_row[0]
            user_name = log_row[1] or "System"
            res.append({
                "id": str(log.id),
                "action": log.action,
                "performed_by_name": user_name,
                "previous_values": log.previous_values,
                "new_values": log.new_values,
                "ip_metadata": log.ip_metadata,
                "created_at": log.created_at.isoformat() if log.created_at else None
            })
        return res

