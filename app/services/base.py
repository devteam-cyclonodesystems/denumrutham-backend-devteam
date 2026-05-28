from sqlalchemy.ext.asyncio import AsyncSession
from app.repositories.base import CRUDBase
from app.models.domain import Devotee, Booking, Donation, Pooja
from app.schemas.domain import DevoteeCreate, BookingCreate, DonationCreate, PoojaCreate

devotee_repo = CRUDBase[Devotee, DevoteeCreate, DevoteeCreate](Devotee)
booking_repo = CRUDBase[Booking, BookingCreate, BookingCreate](Booking)
donation_repo = CRUDBase[Donation, DonationCreate, DonationCreate](Donation)
pooja_repo = CRUDBase[Pooja, PoojaCreate, PoojaCreate](Pooja)


class BaseService:
    # --- Devotees ---
    @staticmethod
    async def create_devotee(db: AsyncSession, devotee_in: DevoteeCreate, temple_id: str):
        return await devotee_repo.create(db=db, obj_in=devotee_in, temple_id=temple_id)

    @staticmethod
    async def get_devotees(db: AsyncSession, temple_id: str, skip: int = 0, limit: int = 100):
        return await devotee_repo.get_multi_by_temple(db=db, temple_id=temple_id, skip=skip, limit=limit)

    # --- Poojas ---
    @staticmethod
    async def create_pooja(db: AsyncSession, pooja_in: PoojaCreate, temple_id: str):
        return await pooja_repo.create(db=db, obj_in=pooja_in, temple_id=temple_id)

    @staticmethod
    async def get_poojas(db: AsyncSession, temple_id: str, skip: int = 0, limit: int = 100):
        return await pooja_repo.get_multi_by_temple(db=db, temple_id=temple_id, skip=skip, limit=limit)

    # --- Bookings ---
    @staticmethod
    async def create_booking(db: AsyncSession, booking_in: BookingCreate, temple_id: str, user_id: str):
        booking = await booking_repo.create(db=db, obj_in=booking_in, temple_id=temple_id)
        await booking_repo.create_audit_log(
            db, temple_id=temple_id, user_id=user_id,
            action="BOOKING_CREATED", details=f"Amount: {booking.total_amount}"
        )
        return booking

    @staticmethod
    async def get_bookings(db: AsyncSession, temple_id: str, skip: int = 0, limit: int = 100):
        return await booking_repo.get_multi_by_temple(db=db, temple_id=temple_id, skip=skip, limit=limit)

    # --- Donations ---
    @staticmethod
    async def create_donation(db: AsyncSession, donation_in: DonationCreate, temple_id: str, user_id: str):
        donation = await donation_repo.create(db=db, obj_in=donation_in, temple_id=temple_id)
        await donation_repo.create_audit_log(
            db, temple_id=temple_id, user_id=user_id,
            action="DONATION_RECEIVED", details=f"Amount: {donation.amount}"
        )
        return donation

    @staticmethod
    async def get_donations(db: AsyncSession, temple_id: str, skip: int = 0, limit: int = 100):
        return await donation_repo.get_multi_by_temple(db=db, temple_id=temple_id, skip=skip, limit=limit)
