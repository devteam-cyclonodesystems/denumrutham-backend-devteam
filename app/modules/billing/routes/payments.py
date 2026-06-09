"""
Payment processing API endpoints — production-ready structure with mock gateway.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from uuid import UUID, uuid4
from pydantic import BaseModel
from typing import Optional

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.response import api_response
from app.modules.billing.models.billing_models import Payment, PaymentStatus
from app.modules.bookings.models.booking_models import ServiceBooking, ServiceBookingStatus, utcnow
from app.schemas.domain import TokenData

router = APIRouter()


# ── Schemas ───────────────────────────────────────────────────────────
class PaymentIntentRequest(BaseModel):
    reference_id: UUID
    amount: float
    payment_method: Optional[str] = "UPI_QR"


class PaymentConfirmRequest(BaseModel):
    payment_id: UUID
    transaction_id: str  # From payment gateway


async def process_payment_success(db: AsyncSession, payment: Payment, transaction_id: str):
    from app.modules.bookings.models.booking_models import ServiceBooking, GuestBooking, ServiceBookingStatus
    from app.modules.temple_management.models.offering import Offering
    from app.modules.inventory.models.inventory_models import StoreSalesOrder
    from app.modules.billing.models.billing_models import PaymentStatus
    
    payment.status = PaymentStatus.SUCCESS
    payment.transaction_id = transaction_id
    
    # 1. Update ServiceBooking if exists
    sb_stmt = select(ServiceBooking).filter(ServiceBooking.id == payment.reference_id)
    sb_res = await db.execute(sb_stmt)
    sb = sb_res.scalar_one_or_none()
    if sb:
        sb.status = ServiceBookingStatus.PAID
        
    # 2. Update GuestBooking if exists
    gb_stmt = select(GuestBooking).filter(GuestBooking.id == payment.reference_id)
    gb_res = await db.execute(gb_stmt)
    gb = gb_res.scalar_one_or_none()
    if gb:
        gb.payment_status = "PAID"
        
    # 3. Update Offering if exists
    off_stmt = select(Offering).filter(Offering.id == payment.reference_id)
    off_res = await db.execute(off_stmt)
    offering = off_res.scalar_one_or_none()
    if offering:
        offering.payment_status = "PAID"
        offering.paid_amount = offering.total_amount
        offering.balance_amount = 0.0
        
    # 4. Update StoreSalesOrder if exists
    sso_stmt = select(StoreSalesOrder).filter(StoreSalesOrder.id == payment.reference_id)
    sso_res = await db.execute(sso_stmt)
    sso = sso_res.scalar_one_or_none()
    if sso:
        sso.payment_status = "PAID"


# ── Create Payment Intent ─────────────────────────────────────────────
@router.post("/intent")
async def create_payment_intent(
    data: PaymentIntentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Create a payment intent for a booking, offering, or store order.
    """
    from app.modules.bookings.models.booking_models import ServiceBooking, GuestBooking, ServiceBookingStatus
    from app.modules.temple_management.models.offering import Offering
    from app.modules.inventory.models.inventory_models import StoreSalesOrder

    # Verify reference entity exists and find temple_id
    temple_id = None
    
    # 1. ServiceBooking?
    sb_stmt = select(ServiceBooking).filter(ServiceBooking.id == data.reference_id)
    sb_res = await db.execute(sb_stmt)
    sb = sb_res.scalar_one_or_none()
    if sb:
        temple_id = sb.temple_id
        if sb.status == ServiceBookingStatus.PAID:
            raise HTTPException(status_code=400, detail="Booking already paid")
            
    # 2. GuestBooking?
    if not temple_id:
        gb_stmt = select(GuestBooking).filter(GuestBooking.id == data.reference_id)
        gb_res = await db.execute(gb_stmt)
        gb = gb_res.scalar_one_or_none()
        if gb:
            temple_id = gb.temple_id
            if gb.payment_status == "PAID":
                raise HTTPException(status_code=400, detail="Guest booking already paid")
                
    # 3. Offering?
    if not temple_id:
        off_stmt = select(Offering).filter(Offering.id == data.reference_id)
        off_res = await db.execute(off_stmt)
        offering = off_res.scalar_one_or_none()
        if offering:
            temple_id = offering.temple_id
            if offering.payment_status == "PAID":
                raise HTTPException(status_code=400, detail="Offering already paid")
                
    # 4. StoreSalesOrder?
    if not temple_id:
        sso_stmt = select(StoreSalesOrder).filter(StoreSalesOrder.id == data.reference_id)
        sso_res = await db.execute(sso_stmt)
        sso = sso_res.scalar_one_or_none()
        if sso:
            temple_id = sso.temple_id
            if sso.payment_status == "PAID":
                raise HTTPException(status_code=400, detail="Store order already paid")
                
    if not temple_id:
        raise HTTPException(status_code=404, detail="Reference entity not found")

    # Create payment record
    payment = Payment(
        temple_id=temple_id,
        reference_id=data.reference_id,
        amount=data.amount,
        status=PaymentStatus.PENDING,
        service_booking_id=data.reference_id if sb else None,
        transaction_id=None,
    )
    db.add(payment)
    await db.flush()

    # Mock: generate a fake gateway reference
    mock_gateway_ref = f"MOCK-{uuid4().hex[:12].upper()}"
    payment.provider_ref = mock_gateway_ref
    await db.commit()
    await db.refresh(payment)

    return api_response(
        data={
            "payment_id": str(payment.id),
            "amount": payment.amount,
            "status": payment.status.value,
            "provider_ref": mock_gateway_ref,
            "gateway_url": f"https://mock-gateway.example.com/pay/{mock_gateway_ref}",
        },
        message="Payment intent created",
    )


# ── Confirm Payment ──────────────────────────────────────────────────
@router.post("/confirm")
async def confirm_payment(
    data: PaymentConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Confirm a payment after gateway callback.
    """
    result = await db.execute(
        select(Payment).filter(Payment.id == data.payment_id)
    )
    payment = result.scalars().first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    if payment.status == PaymentStatus.SUCCESS:
        return api_response(
            data={"payment_id": str(payment.id), "status": "SUCCESS"},
            message="Payment already confirmed",
        )

    await process_payment_success(db, payment, data.transaction_id)
    await db.commit()

    return api_response(
        data={
            "payment_id": str(payment.id),
            "transaction_id": data.transaction_id,
            "status": "SUCCESS",
        },
        message="Payment confirmed and records updated",
    )


# ── Verify Payment (Webhook) ─────────────────────────────────────────
@router.post("/verify/{reference_id}")
async def verify_payment(
    reference_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Mock payment gateway webhook.
    """
    result = await db.execute(
        select(Payment).filter(Payment.reference_id == reference_id)
    )
    payment = result.scalars().first()

    if not payment:
        raise HTTPException(status_code=404, detail="Payment reference not found")

    if payment.status == PaymentStatus.SUCCESS:
        return api_response(
            data={"payment_id": str(payment.id)},
            message="Payment already successful",
        )

    mock_txn_id = f"WEBHOOK-{uuid4().hex[:10].upper()}"
    await process_payment_success(db, payment, mock_txn_id)
    await db.commit()

    return api_response(
        data={
            "payment_id": str(payment.id),
            "status": "SUCCESS",
        },
        message="Payment verified and records confirmed",
    )

