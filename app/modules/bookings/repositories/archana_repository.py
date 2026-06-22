from typing import List, Optional, Dict, Any
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, and_, Date
from sqlalchemy.orm import selectinload
from app.models.archana import (
    ArchanaCatalog, 
    EnterpriseArchanaBooking, 
    ArchanaBookingMember, 
    ArchanaBookingItem, 
    RitualQueue,
    ArchanaExecution,
    ArchanaStatus,
    QueueStatus,
    CatalogStatus,
    DeityMaster
)
from datetime import datetime, date, timezone

class ArchanaRepository:

    @staticmethod
    async def get_catalog(db: AsyncSession, temple_id: UUID, status: Optional[CatalogStatus] = None) -> List[ArchanaCatalog]:
        query = select(ArchanaCatalog).filter(ArchanaCatalog.temple_id == temple_id)
        if status:
            query = query.filter(ArchanaCatalog.status == status)
        else:
            # Default to only showing active and approved items for general use
            query = query.filter(ArchanaCatalog.status == CatalogStatus.APPROVED, ArchanaCatalog.is_active == True)
            
        result = await db.execute(
            query.options(selectinload(ArchanaCatalog.deity))
            .order_by(ArchanaCatalog.name)
        )
        return result.scalars().all()

    @staticmethod
    async def get_catalog_item(db: AsyncSession, item_id: UUID) -> Optional[ArchanaCatalog]:
        result = await db.execute(
            select(ArchanaCatalog)
            .filter(ArchanaCatalog.id == item_id)
            .options(selectinload(ArchanaCatalog.deity))
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_catalog_item_by_name(db: AsyncSession, temple_id: UUID, name: str) -> Optional[ArchanaCatalog]:
        result = await db.execute(
            select(ArchanaCatalog).filter(
                ArchanaCatalog.temple_id == temple_id,
                ArchanaCatalog.name == name,
                ArchanaCatalog.status != CatalogStatus.ARCHIVED
            )
        )
        return result.scalars().first()

    # --- Deity Master Methods ---
    @staticmethod
    async def get_deities(db: AsyncSession, temple_id: UUID, active_only: bool = False) -> List[DeityMaster]:
        from app.models.archana import DeityStatus
        query = select(DeityMaster).filter(DeityMaster.tenant_id == temple_id)
        if active_only:
            query = query.filter(DeityMaster.status == DeityStatus.ACTIVE)
        
        result = await db.execute(query.order_by(DeityMaster.display_order, DeityMaster.deity_name))
        return result.scalars().all()

    @staticmethod
    async def get_deity_by_name(db: AsyncSession, temple_id: UUID, name: str) -> Optional[DeityMaster]:
        result = await db.execute(
            select(DeityMaster).filter(
                DeityMaster.tenant_id == temple_id,
                DeityMaster.normalized_name == name.strip().lower()
            )
        )
        return result.scalars().first()

    @staticmethod
    async def get_deity(db: AsyncSession, deity_id: UUID) -> Optional[DeityMaster]:
        result = await db.execute(select(DeityMaster).filter(DeityMaster.id == deity_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def create_deity(db: AsyncSession, deity: DeityMaster) -> DeityMaster:
        db.add(deity)
        await db.flush()
        return deity



    @staticmethod
    async def create_booking(db: AsyncSession, booking: EnterpriseArchanaBooking) -> EnterpriseArchanaBooking:
        db.add(booking)
        await db.flush()
        return booking

    @staticmethod
    async def get_booking_by_idempotency_key(db: AsyncSession, temple_id: UUID, key: str) -> Optional[EnterpriseArchanaBooking]:
        result = await db.execute(
            select(EnterpriseArchanaBooking)
            .filter(EnterpriseArchanaBooking.temple_id == temple_id, EnterpriseArchanaBooking.idempotency_key == key)
            .options(
                selectinload(EnterpriseArchanaBooking.members)
                .selectinload(ArchanaBookingMember.items)
            )
        )
        return result.scalars().first()

    @staticmethod
    async def check_duplicate_booking(
        db: AsyncSession, 
        temple_id: UUID, 
        devotee_name: str, 
        phone: Optional[str],
        window_minutes: int
    ) -> Optional[EnterpriseArchanaBooking]:
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        
        query = select(EnterpriseArchanaBooking).filter(
            EnterpriseArchanaBooking.temple_id == temple_id,
            EnterpriseArchanaBooking.primary_devotee_name == devotee_name,
            EnterpriseArchanaBooking.created_at >= cutoff,
            EnterpriseArchanaBooking.status != ArchanaStatus.CANCELLED
        )
        if phone:
            query = query.filter(EnterpriseArchanaBooking.phone_number == phone)
            
        result = await db.execute(query.options(selectinload(EnterpriseArchanaBooking.members)))
        return result.scalars().first()

    @staticmethod
    async def get_bookings(
        db: AsyncSession, 
        temple_id: UUID, 
        skip: int = 0, 
        limit: int = 50,
        status: Optional[ArchanaStatus] = None
    ) -> List[Dict[str, Any]]:
        query = select(EnterpriseArchanaBooking).filter(EnterpriseArchanaBooking.temple_id == temple_id)
        if status:
            query = query.filter(EnterpriseArchanaBooking.status == status)
        
        query = query.order_by(EnterpriseArchanaBooking.created_at.desc()).offset(skip).limit(limit)
        query = query.options(
            selectinload(EnterpriseArchanaBooking.members)
            .selectinload(ArchanaBookingMember.items),
            selectinload(EnterpriseArchanaBooking.queue_entry)
        )
        
        result = await db.execute(query)
        bookings = result.scalars().all()
        
        data = []
        for b in bookings:
            computed_status = "Waiting"
            if b.status == ArchanaStatus.CANCELLED:
                computed_status = "Cancelled"
            elif b.status == ArchanaStatus.COMPLETED:
                computed_status = "Completed"
            elif b.queue_entry:
                q = b.queue_entry
                if q.status == QueueStatus.CANCELLED:
                    computed_status = "Cancelled"
                elif q.status == QueueStatus.COMPLETED:
                    computed_status = "Completed"
                elif q.status == QueueStatus.IN_PROGRESS:
                    computed_status = "In Progress"
                elif q.status == QueueStatus.WAITING:
                    computed_status = "Waiting"
            elif b.ritual_time:
                now_utc = datetime.now(timezone.utc)
                r_time = b.ritual_time
                if r_time.tzinfo is None:
                    r_time = r_time.replace(tzinfo=timezone.utc)
                if r_time > now_utc:
                    computed_status = "Upcoming"

            data.append({
                "id": str(b.id),
                "ref_id": b.ref_id,
                "primary_devotee_name": b.primary_devotee_name,
                "grand_total": b.grand_total,
                "dakshina": b.dakshina or 0.0,
                "payment_mode": b.payment_mode,
                "prasadam_collection": b.prasadam_collection,
                "status": b.status.value,
                "computed_status": computed_status,
                "created_at": b.created_at.isoformat() if b.created_at else None,
                "phone_number": b.phone_number
            })
        return data

    @staticmethod
    async def get_queue(db: AsyncSession, temple_id: UUID) -> List[Dict[str, Any]]:
        # Fetch queue entries with minimal required relations
        result = await db.execute(
            select(RitualQueue)
            .filter(RitualQueue.temple_id == temple_id)
            .filter(RitualQueue.status.in_([QueueStatus.WAITING, QueueStatus.ACKNOWLEDGED, QueueStatus.IN_PROGRESS]))
            .options(
                selectinload(RitualQueue.executions)
                    .selectinload(ArchanaExecution.item)
                    .selectinload(ArchanaBookingItem.member),
                selectinload(RitualQueue.booking)
            )
            .order_by(RitualQueue.priority.desc(), RitualQueue.estimated_start_time.asc())
        )
        queue_entries = result.scalars().all()
        
        # Manually map to dict to prevent RecursionError in FastAPI's jsonable_encoder
        data = []
        for q in queue_entries:
            q_dict = {
                "id": str(q.id),
                "token_number": q.token_number,
                "status": q.status.value,
                "priority": q.priority,
                "estimated_start_time": q.estimated_start_time.isoformat() if q.estimated_start_time else None,
                "booking": {
                    "primary_devotee_name": q.booking.primary_devotee_name if q.booking else "Guest"
                },
                "executions": []
            }
            
            for ex in q.executions:
                ex_dict = {
                    "id": str(ex.id),
                    "status": ex.status.value,
                    "start_time": ex.start_time.isoformat() if ex.start_time else None,
                    "expected_completion_time": ex.expected_completion_time.isoformat() if ex.expected_completion_time else None,
                    "completed_at": ex.completed_at.isoformat() if ex.completed_at else None,
                    "acknowledged_at": ex.acknowledged_at.isoformat() if ex.acknowledged_at else None,
                    "ritual_name": ex.item.ritual_name_snapshot if ex.item else "Unknown Archana",
                    "devotee": ex.item.member.name if ex.item and ex.item.member else "Guest",
                    "star": ex.item.member.nakshatra if ex.item and ex.item.member else "Unknown Star",
                    "item": {
                        "ritual_name_snapshot": ex.item.ritual_name_snapshot if ex.item else None,
                        "ritual_deity_snapshot": ex.item.ritual_deity_snapshot if ex.item else None,
                        "ritual_duration_snapshot": ex.item.ritual_duration_snapshot if ex.item else 0,
                        "member": {
                            "name": ex.item.member.name if ex.item and ex.item.member else "Guest",
                            "nakshatra": ex.item.member.nakshatra if ex.item and ex.item.member else "Unknown Star"
                        }
                    }
                }
                q_dict["executions"].append(ex_dict)
            
            data.append(q_dict)
            
        return data

    @staticmethod
    async def get_booking_count(db: AsyncSession, temple_id: UUID) -> int:
        result = await db.execute(
            select(func.count(EnterpriseArchanaBooking.id)).filter(EnterpriseArchanaBooking.temple_id == temple_id)
        )
        return result.scalar() or 0

    @staticmethod
    async def get_kpis(db: AsyncSession, temple_id: UUID):
        today = date.today()
        
        # Total Bookings
        total_res = await db.execute(
            select(func.count(EnterpriseArchanaBooking.id))
            .filter(EnterpriseArchanaBooking.temple_id == temple_id)
        )
        total = total_res.scalar() or 0
        
        # Confirmed
        confirmed_res = await db.execute(
            select(func.count(EnterpriseArchanaBooking.id))
            .filter(EnterpriseArchanaBooking.temple_id == temple_id, EnterpriseArchanaBooking.status == ArchanaStatus.CONFIRMED)
        )
        confirmed = confirmed_res.scalar() or 0

        # Cancelled
        cancelled_res = await db.execute(
            select(func.count(EnterpriseArchanaBooking.id))
            .filter(EnterpriseArchanaBooking.temple_id == temple_id, EnterpriseArchanaBooking.status == ArchanaStatus.CANCELLED)
        )
        cancelled = cancelled_res.scalar() or 0

        # Total Revenue
        revenue_res = await db.execute(
            select(func.sum(EnterpriseArchanaBooking.grand_total))
            .filter(EnterpriseArchanaBooking.temple_id == temple_id, EnterpriseArchanaBooking.status != ArchanaStatus.CANCELLED)
        )
        revenue = revenue_res.scalar() or 0.0

        # Today's Bookings
        today_res = await db.execute(
            select(func.count(EnterpriseArchanaBooking.id))
            .filter(
                EnterpriseArchanaBooking.temple_id == temple_id, 
                func.cast(EnterpriseArchanaBooking.created_at, Date) == today
            )
        )
        today_count = today_res.scalar() or 0

        # Pending Queue
        queue_res = await db.execute(
            select(func.count(RitualQueue.id))
            .filter(RitualQueue.temple_id == temple_id, RitualQueue.status == QueueStatus.WAITING)
        )
        pending_queue = queue_res.scalar() or 0

        # Completed Rituals
        completed_res = await db.execute(
            select(func.count(RitualQueue.id))
            .filter(RitualQueue.temple_id == temple_id, RitualQueue.status == QueueStatus.COMPLETED)
        )
        completed = completed_res.scalar() or 0

        return {
            "total_bookings": total,
            "confirmed_bookings": confirmed,
            "cancelled_bookings": cancelled,
            "total_revenue": float(revenue),
            "today_bookings": today_count,
            "pending_queue": pending_queue,
            "completed_rituals": completed
        }

    @staticmethod
    async def update_queue_status(db: AsyncSession, queue_id: UUID, status: QueueStatus, priest_id: Optional[UUID] = None) -> RitualQueue:
        result = await db.execute(select(RitualQueue).filter(RitualQueue.id == queue_id))
        queue = result.scalar_one_or_none()
        if not queue:
            raise ServiceException("Queue entry not found", "NOT_FOUND", status_code=404)
        
        queue.status = status
        if priest_id:
            import logging
            logger = logging.getLogger("tms.repositories.archana")
            logger.info(
                "Legacy priest_id received and ignored in queue status update",
                extra={
                    "priest_id": str(priest_id),
                    "queue_id": str(queue_id)
                }
            )
        queue.priest_id = None
        
        if status == QueueStatus.IN_PROGRESS or status == QueueStatus.ACTIVE:
            queue.actual_start_time = datetime.now(timezone.utc)
        elif status == QueueStatus.COMPLETED:
            queue.completed_at = datetime.now(timezone.utc)
            
        import logging
        logger = logging.getLogger("tms.repositories.archana")
        logger.error(
            "PRE-COMMIT QUEUE STATE",
            extra={
                "queue_id": str(queue.id),
                "priest_id": str(queue.priest_id),
                "status": str(queue.status)
            }
        )
        await db.commit()
        await db.refresh(queue)
        return queue
