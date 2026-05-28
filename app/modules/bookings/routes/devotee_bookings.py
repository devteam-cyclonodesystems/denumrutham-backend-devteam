from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from app.api.deps import get_db, get_current_user
from app.schemas.domain import TokenData
from app.schemas.devotee_portal import (
    ServiceBookingCreate, ServiceBookingResponse,
    DevoteeProfileResponse, DevoteeProfileUpdate, PaymentResponse,
)
from app.services.devotee_booking_service import DevoteeBookingService
from app.services.notification_service import NotificationService

router = APIRouter()


@router.post("/bookings", response_model=ServiceBookingResponse)
async def create_booking(
    data: ServiceBookingCreate,
    background_tasks: BackgroundTasks,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a service booking for the current devotee."""
    booking, service = await DevoteeBookingService.create_booking(db, data, current_user.sub)

    background_tasks.add_task(
        NotificationService.send_whatsapp_message,
        phone_number=booking.devotee_phone,
        template_name="booking_confirmation",
        payload={"service": service.service_name, "amount": service.price}
    )

    return ServiceBookingResponse(
        id=booking.id,
        temple_id=booking.temple_id,
        service_id=booking.service_id,
        booking_date=booking.booking_date,
        amount=booking.amount,
        status=booking.status,
        devotee_name=booking.devotee_name,
        devotee_phone=booking.devotee_phone,
        notes=booking.notes,
        created_at=booking.created_at,
        service_name=service.service_name,
    )


@router.get("/bookings/my", response_model=List[ServiceBookingResponse])
async def get_my_bookings(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all bookings for the current user."""
    items = await DevoteeBookingService.get_my_bookings(db, current_user.sub)
    return [ServiceBookingResponse(**item) for item in items]


@router.get("/bookings/{booking_id}/payment", response_model=PaymentResponse)
async def get_booking_payment(
    booking_id: str,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get payment details for a booking (includes UPI ID for QR)."""
    payment, upi_id = await DevoteeBookingService.get_booking_payment(db, booking_id, current_user.sub)

    return PaymentResponse(
        id=payment.id,
        temple_id=payment.temple_id,
        amount=payment.amount,
        payment_method=payment.payment_method,
        status=payment.status,
        service_booking_id=payment.service_booking_id,
        upi_id=upi_id,
        created_at=payment.created_at,
    )


@router.get("/profile", response_model=DevoteeProfileResponse)
async def get_devotee_profile(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the current devotee's profile."""
    return await DevoteeBookingService.get_devotee_profile(db, current_user.sub)


@router.put("/profile", response_model=DevoteeProfileResponse)
async def update_devotee_profile(
    data: DevoteeProfileUpdate,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the current devotee's profile."""
    return await DevoteeBookingService.update_devotee_profile(db, current_user.sub, data)
