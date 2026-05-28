import logging
from uuid import UUID
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_, and_
from app.models.domain import HallBooking
from app.models.hall_booking import BookingHold, BookingConflict

logger = logging.getLogger("tms.services.booking_conflict")

class BookingConflictService:
    @staticmethod
    def _parse_datetime(date_str: str, time_str: str) -> datetime:
        # Fallback time if not provided
        if not time_str:
            time_str = "00:00"
        try:
            return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        except ValueError:
            return datetime.strptime(date_str, "%Y-%m-%d")

    @staticmethod
    async def check_conflict(
        db: AsyncSession,
        temple_id: str,
        hall_id: str,
        start_date: str,
        start_time: str,
        end_date: str,
        end_time: str,
        exclude_booking_id: str = None
    ) -> bool:
        tid = UUID(str(temple_id))
        hid = UUID(str(hall_id))
        
        req_start = BookingConflictService._parse_datetime(start_date, start_time)
        req_end = BookingConflictService._parse_datetime(end_date, end_time)

        # Retrieve all active bookings for this hall
        query = select(HallBooking).filter(
            HallBooking.temple_id == tid,
            HallBooking.hall_id == hid,
            HallBooking.status.in_(["pending", "confirmed"])
        )
        if exclude_booking_id:
            query = query.filter(HallBooking.id != UUID(str(exclude_booking_id)))

        result = await db.execute(query)
        active_bookings = result.scalars().all()

        for b in active_bookings:
            b_start = BookingConflictService._parse_datetime(b.date, b.start_time)
            b_end = BookingConflictService._parse_datetime(b.end_date, b.end_time)
            
            # Check overlap: (StartA <= EndB) and (EndA >= StartB)
            if req_start < b_end and req_end > b_start:
                return True # Conflict found
                
        # Also check soft holds
        now = datetime.utcnow()
        holds_query = select(BookingHold).filter(
            BookingHold.temple_id == tid,
            BookingHold.hall_id == hid,
            BookingHold.expires_at > now
        )
        holds_result = await db.execute(holds_query)
        active_holds = holds_result.scalars().all()
        
        for h in active_holds:
            # Assuming hold start/end are datetime objects in UTC
            if req_start.timestamp() < h.end_time.timestamp() and req_end.timestamp() > h.start_time.timestamp():
                return True
                
        return False
        
    @staticmethod
    async def log_conflict(
        db: AsyncSession,
        temple_id: str,
        hall_id: str,
        primary_booking_id: str,
        overlapping_booking_id: str = None,
        conflict_type: str = "HARD_OVERLAP"
    ) -> BookingConflict:
        conflict = BookingConflict(
            temple_id=UUID(str(temple_id)),
            hall_id=UUID(str(hall_id)),
            primary_booking_id=UUID(str(primary_booking_id)),
            overlapping_booking_id=UUID(str(overlapping_booking_id)) if overlapping_booking_id else None,
            conflict_type=conflict_type,
            status="PENDING"
        )
        db.add(conflict)
        await db.flush()
        return conflict
