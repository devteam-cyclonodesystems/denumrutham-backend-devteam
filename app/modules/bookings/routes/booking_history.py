"""
Booking History & Re-book Routes.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from uuid import UUID
from typing import List, Optional
from datetime import datetime, timezone

from app.core.database import get_db
from app.core.deps import get_current_user
from app.schemas.domain import TokenData
from app.schemas.devotee_portal import ServiceBookingResponse, ServiceBookingCreate
from app.models.domain import ServiceBooking, TempleService as TempleServiceModel, Temple
from app.services.devotee_booking_service import DevoteeBookingService
from app.core.response import api_response

router = APIRouter()


@router.get("/history")
async def get_booking_history(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all past bookings for the current user (booking history)."""
    bookings = await DevoteeBookingService.get_my_bookings(db, current_user.sub)
    bookings_list = [ServiceBookingResponse.model_validate(b).model_dump() for b in bookings]
    return api_response(data=bookings_list, message="Booking history retrieved")


@router.post("/rebook/{booking_id}", status_code=201)
async def rebook(
    booking_id: UUID,
    booking_date: Optional[str] = None,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Re-book from a previous booking.
    Creates a new booking with the same service and temple, optionally with a new date.
    """
    # Fetch the original booking
    result = await db.execute(
        select(ServiceBooking).filter(ServiceBooking.id == booking_id)
    )
    original = result.scalars().first()
    if not original:
        raise HTTPException(status_code=404, detail="Original booking not found")

    # Verify ownership
    if str(original.devotee_user_id) != current_user.sub:
        raise HTTPException(status_code=403, detail="Not your booking to re-book")

    # Parse new booking date or use current datetime
    if booking_date:
        try:
            new_date = datetime.fromisoformat(booking_date)
            if new_date.tzinfo is None:
                new_date = new_date.replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format")
    else:
        new_date = datetime.now(timezone.utc)

    # Verify service is still active
    srv_result = await db.execute(
        select(TempleServiceModel).filter(
            TempleServiceModel.id == original.service_id,
            TempleServiceModel.active == True,
        )
    )
    service = srv_result.scalars().first()
    if not service:
        raise HTTPException(status_code=400, detail="Service is no longer available")

    # Create the new booking  
    from app.models.domain import ServiceBookingStatus
    new_booking = ServiceBooking(
        temple_id=original.temple_id,
        devotee_user_id=original.devotee_user_id,
        service_id=original.service_id,
        booking_date=new_date,
        amount=service.price,
        status=ServiceBookingStatus.PENDING,
        devotee_name=original.devotee_name,
        devotee_phone=original.devotee_phone,
        notes=f"Re-booked from {booking_id}",
    )
    db.add(new_booking)
    await db.commit()
    await db.refresh(new_booking)

    # Enrich response
    temple_result = await db.execute(select(Temple).filter(Temple.id == new_booking.temple_id))
    temple = temple_result.scalars().first()

    return api_response(
        data={
            "booking_id": str(new_booking.id),
            "original_booking_id": str(booking_id),
            "service_name": service.service_name,
            "temple_name": temple.name if temple else "",
            "booking_date": new_booking.booking_date.isoformat(),
            "amount": new_booking.amount,
            "status": new_booking.status.value,
        },
        message="Re-booking successful",
        status_code=201
    )
