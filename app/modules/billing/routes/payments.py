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
    service_booking_id: UUID
    amount: float
    payment_method: Optional[str] = "UPI_QR"


class PaymentConfirmRequest(BaseModel):
    payment_id: UUID
    transaction_id: str  # From payment gateway


# ── Create Payment Intent ─────────────────────────────────────────────
@router.post("/intent")
async def create_payment_intent(
    data: PaymentIntentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """
    Create a payment intent for a service booking.
    In production, this would call the actual payment gateway SDK.
    """
    # Verify booking exists
    result = await db.execute(
        select(ServiceBooking).filter(ServiceBooking.id == data.service_booking_id)
    )
    booking = result.scalars().first()
    if not booking:
        raise HTTPException(status_code=404, detail="Service booking not found")

    if booking.status == ServiceBookingStatus.PAID:
        raise HTTPException(status_code=400, detail="Booking already paid")

    # Create payment record
    payment = Payment(
        temple_id=booking.temple_id,
        reference_id=data.service_booking_id,
        amount=data.amount,
        status=PaymentStatus.PENDING,
        service_booking_id=data.service_booking_id,
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
    Transitions Payment → SUCCESS and ServiceBooking → PAID.
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

    payment.status = PaymentStatus.SUCCESS
    payment.transaction_id = data.transaction_id

    # Update booking status
    if payment.service_booking_id:
        b_result = await db.execute(
            select(ServiceBooking).filter(ServiceBooking.id == payment.service_booking_id)
        )
        booking = b_result.scalars().first()
        if booking:
            booking.status = ServiceBookingStatus.PAID

    await db.commit()

    return api_response(
        data={
            "payment_id": str(payment.id),
            "transaction_id": data.transaction_id,
            "status": "SUCCESS",
        },
        message="Payment confirmed and booking updated",
    )


# ── Verify Payment (Webhook) ─────────────────────────────────────────
@router.post("/verify/{reference_id}")
async def verify_payment(
    reference_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Mock payment gateway webhook.
    Transitions Payment from PENDING to SUCCESS, and ServiceBooking to PAID.
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

    payment.status = PaymentStatus.SUCCESS
    payment.transaction_id = f"WEBHOOK-{uuid4().hex[:10].upper()}"

    if payment.service_booking_id:
        b_result = await db.execute(
            select(ServiceBooking).filter(ServiceBooking.id == payment.service_booking_id)
        )
        booking = b_result.scalars().first()
        if booking:
            booking.status = ServiceBookingStatus.PAID

    await db.commit()

    return api_response(
        data={
            "payment_id": str(payment.id),
            "status": "SUCCESS",
        },
        message="Payment verified and booking confirmed",
    )
