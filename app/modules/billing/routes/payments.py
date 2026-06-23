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
        await create_execution_for_devotee_booking(db, sb)
        
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


async def create_execution_for_devotee_booking(db: AsyncSession, sb: ServiceBooking):
    from app.models.archana import (
        EnterpriseArchanaBooking, ArchanaBookingMember, ArchanaBookingItem,
        RitualQueue, ArchanaExecution, ArchanaStatus, QueueStatus
    )
    import uuid
    from datetime import datetime, timezone
    
    # 1. EnterpriseArchanaBooking
    ref_id = f"AR{sb.id.hex[:6].upper()}"
    eb = EnterpriseArchanaBooking(
        id=sb.id,
        temple_id=sb.temple_id,
        ref_id=ref_id,
        primary_devotee_id=sb.devotee_user_id,
        primary_devotee_name=sb.devotee_name,
        phone_number=sb.devotee_phone,
        total_amount=sb.amount,
        dakshina=sb.dakshina_amount,
        grand_total=sb.amount + sb.dakshina_amount,
        booking_mode="Online",
        status=ArchanaStatus.CONFIRMED,
        created_at=sb.created_at
    )
    db.add(eb)
    
    # 2. RitualQueue
    # Get sequential token number for this temple today
    from sqlalchemy import func
    today = datetime.now(timezone.utc).date()
    token_stmt = select(func.count(RitualQueue.id)).filter(
        RitualQueue.temple_id == sb.temple_id,
        func.date(RitualQueue.estimated_start_time) == today
    )
    token_res = await db.execute(token_stmt)
    token_seq = (token_res.scalar() or 0) + 1
    token_number = f"T-{token_seq:03d}"
    
    queue = RitualQueue(
        id=uuid.uuid4(),
        temple_id=sb.temple_id,
        booking_id=sb.id,
        token_number=token_number,
        status=QueueStatus.WAITING,
        estimated_start_time=sb.booking_date
    )
    db.add(queue)
    
    # 3. Add members & items
    family_members = sb.booking_metadata.get("family_members", []) if isinstance(sb.booking_metadata, dict) else []
    
    # Primary member
    primary_nakshatra = sb.booking_metadata.get("nakshatra") if isinstance(sb.booking_metadata, dict) else None
    if not primary_nakshatra:
        primary_nakshatra = "Unknown Star"
        
    primary_member = ArchanaBookingMember(
        id=uuid.uuid4(),
        booking_id=sb.id,
        name=sb.devotee_name,
        nakshatra=primary_nakshatra,
        is_primary=True
    )
    db.add(primary_member)
    
    # Primary item
    from app.modules.temple_management.models.temple_models import TempleService as TempleServiceModel
    srv_res = await db.execute(select(TempleServiceModel).filter(TempleServiceModel.id == sb.service_id))
    srv = srv_res.scalars().first()
    srv_name = srv.service_name if srv else "Unknown Ritual"
    
    primary_item = ArchanaBookingItem(
        id=uuid.uuid4(),
        member_id=primary_member.id,
        service_id=sb.service_id,
        quantity=1,
        price_at_booking=sb.amount,
        total_price=sb.amount,
        ritual_name_snapshot=srv_name,
        ritual_duration_snapshot=5
    )
    db.add(primary_item)
    
    # Primary execution
    primary_execution = ArchanaExecution(
        id=uuid.uuid4(),
        temple_id=sb.temple_id,
        booking_item_id=primary_item.id,
        queue_id=queue.id,
        status=QueueStatus.WAITING
    )
    db.add(primary_execution)
    
    # Add family members if any
    for fm in family_members:
        fm_name = fm.get("name")
        fm_nakshatra = fm.get("nakshatra", "Unknown Star")
        if not fm_name:
            continue
        fm_member = ArchanaBookingMember(
            id=uuid.uuid4(),
            booking_id=sb.id,
            name=fm_name,
            nakshatra=fm_nakshatra,
            is_primary=False
        )
        db.add(fm_member)
        
        # Check if they have a specific service, else use primary service
        fm_service_id = fm.get("service_id")
        if fm_service_id:
            try:
                fm_service_uuid = uuid.UUID(fm_service_id)
            except ValueError:
                fm_service_uuid = sb.service_id
        else:
            fm_service_uuid = sb.service_id
            
        fm_srv_res = await db.execute(select(TempleServiceModel).filter(TempleServiceModel.id == fm_service_uuid))
        fm_srv = fm_srv_res.scalars().first()
        fm_srv_name = fm_srv.service_name if fm_srv else srv_name
        fm_price = fm_srv.price if fm_srv else sb.amount
        
        fm_item = ArchanaBookingItem(
            id=uuid.uuid4(),
            member_id=fm_member.id,
            service_id=fm_service_uuid,
            quantity=1,
            price_at_booking=fm_price,
            total_price=fm_price,
            ritual_name_snapshot=fm_srv_name,
            ritual_duration_snapshot=5
        )
        db.add(fm_item)
        
        # Add execution tracker for this family member
        fm_execution = ArchanaExecution(
            id=uuid.uuid4(),
            temple_id=sb.temple_id,
            booking_item_id=fm_item.id,
            queue_id=queue.id,
            status=QueueStatus.WAITING
        )
        db.add(fm_execution)


from fastapi import Request

@router.post("/razorpay/webhook")
async def razorpay_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Public webhook endpoint to receive and verify Razorpay events.
    """
    signature = request.headers.get("X-Razorpay-Signature", "")
    body = await request.body()
    
    # Get webhook secret
    import os
    from app.core.payments.razorpay_provider import RazorpayProvider
    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    if not secret:
        # Check PlatformGlobalSetting
        from app.modules.governance.models.governance_models import PlatformGlobalSetting
        try:
            stmt = select(PlatformGlobalSetting).filter(PlatformGlobalSetting.key == "razorpay_config")
            res = await db.execute(stmt)
            setting = res.scalar_one_or_none()
            if setting and isinstance(setting.value, dict):
                secret = setting.value.get("webhook_secret", "")
        except Exception:
            pass
            
    # Verify signature
    if not RazorpayProvider.verify_webhook_signature(body, signature, secret):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
        
    try:
        event_data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
        
    from app.services.devotee_booking_service import DevoteeBookingService
    success = await DevoteeBookingService.process_payment_webhook(db, event_data)
    
    return {"status": "ok" if success else "ignored"}



