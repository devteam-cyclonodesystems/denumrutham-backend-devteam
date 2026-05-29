"""Devotee Booking Service — Service bookings, payments, and profile management."""
from uuid import UUID
from datetime import datetime, timezone
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException

from app.modules.temple_management.models.temple_models import TempleService, Temple, TempleProfile
from app.modules.bookings.models.booking_models import ServiceBooking, ServiceBookingStatus, PaymentMethod, DevoteeProfile
from app.modules.billing.models.billing_models import Payment, PaymentStatus


class DevoteeBookingService:

    @staticmethod
    async def create_booking(db: AsyncSession, data, user_id: str):
        uid = UUID(user_id)

        # Verify service exists and is active
        service_result = await db.execute(
            select(TempleService).filter(
                TempleService.id == data.service_id,
                TempleService.temple_id == data.temple_id,
                TempleService.active == True,
            )
        )
        service = service_result.scalars().first()
        if not service:
            raise HTTPException(status_code=404, detail="Service not found or inactive")

        # Parse booking date
        try:
            booking_date = datetime.fromisoformat(data.booking_date)
            if booking_date.tzinfo is None:
                booking_date = booking_date.replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid booking date format")

        # Create booking
        booking = ServiceBooking(
            temple_id=data.temple_id,
            devotee_user_id=uid,
            service_id=data.service_id,
            booking_date=booking_date,
            amount=service.price,
            status=ServiceBookingStatus.PENDING,
            devotee_name=data.devotee_name,
            devotee_phone=data.devotee_phone,
            notes=data.notes or "",
        )
        db.add(booking)
        await db.flush()

        # Create payment record
        payment = Payment(
            temple_id=data.temple_id,
            reference_id=booking.id,
            amount=service.price,
            status=PaymentStatus.PENDING,
            payment_method=PaymentMethod.UPI_QR,
            service_booking_id=booking.id,
        )
        db.add(payment)
        await db.commit()
        await db.refresh(booking)

        return booking, service

    @staticmethod
    async def get_my_bookings(db: AsyncSession, user_id: str):
        uid = UUID(user_id)

        result = await db.execute(
            select(ServiceBooking)
            .filter(ServiceBooking.devotee_user_id == uid)
            .order_by(ServiceBooking.created_at.desc())
        )
        bookings = result.scalars().all()

        enriched = []
        for b in bookings:
            service_name = None
            temple_name = None
            srv = await db.execute(select(TempleService).filter(TempleService.id == b.service_id))
            srv_obj = srv.scalars().first()
            if srv_obj:
                service_name = srv_obj.service_name
            tmpl = await db.execute(select(Temple).filter(Temple.id == b.temple_id))
            tmpl_obj = tmpl.scalars().first()
            if tmpl_obj:
                temple_name = tmpl_obj.name

            enriched.append({
                "id": b.id,
                "temple_id": b.temple_id,
                "service_id": b.service_id,
                "booking_date": b.booking_date,
                "amount": b.amount,
                "status": b.status,
                "devotee_name": b.devotee_name,
                "devotee_phone": b.devotee_phone,
                "notes": b.notes,
                "created_at": b.created_at,
                "service_name": service_name,
                "temple_name": temple_name,
            })
        return enriched

    @staticmethod
    async def get_booking_payment(db: AsyncSession, booking_id: str, user_id: str):
        bid = UUID(booking_id)

        booking_result = await db.execute(
            select(ServiceBooking).filter(ServiceBooking.id == bid)
        )
        booking = booking_result.scalars().first()
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")

        if str(booking.devotee_user_id) != user_id:
            raise HTTPException(status_code=403, detail="Not your booking")

        payment_result = await db.execute(
            select(Payment).filter(Payment.service_booking_id == bid)
        )
        payment = payment_result.scalars().first()
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")

        profile_result = await db.execute(
            select(TempleProfile).filter(TempleProfile.temple_id == booking.temple_id)
        )
        profile = profile_result.scalars().first()
        upi_id = profile.upi_id if profile else ""

        return payment, upi_id

    @staticmethod
    async def get_devotee_profile(db: AsyncSession, user_id: str):
        uid = UUID(user_id)
        result = await db.execute(
            select(DevoteeProfile).filter(DevoteeProfile.user_id == uid)
        )
        profile = result.scalars().first()
        if not profile:
            raise HTTPException(status_code=404, detail="Devotee profile not found")
        return profile

    @staticmethod
    async def update_devotee_profile(db: AsyncSession, user_id: str, data):
        uid = UUID(user_id)
        result = await db.execute(
            select(DevoteeProfile).filter(DevoteeProfile.user_id == uid)
        )
        profile = result.scalars().first()
        if not profile:
            raise HTTPException(status_code=404, detail="Devotee profile not found")

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(profile, field, value)

        await db.commit()
        await db.refresh(profile)
        return profile
