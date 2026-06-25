"""
Archana Booking Service Module

Purpose:
Manages devotee booking lifecycles for temple Poojas and Archanas.

Responsibilities:
- Prepares bookings lists and executes daily pooja schedules
- Multi-tenant isolated via temple context boundaries
- Lock-free receipt sequential number generation

Operational Notes:
- Heavy database operations, utilizes SQLAlchemy async sessions
- Integrates with financial transaction ledgers upon payment confirmation
"""

"""Archana Service — Enterprise-grade Archana/Pooja booking management."""
import logging
from uuid import UUID
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.models.archana import (
    EnterpriseArchanaBooking, 
    ArchanaBookingMember, 
    ArchanaBookingItem, 
    ArchanaCatalog,
    RitualQueue,
    ArchanaStatus,
    QueueStatus,
    ArchanaBookingAudit,
    CatalogStatus,
    CatalogVersion,
    DeityMaster,
    DeityAudit
)
from app.schemas.archana import EnterpriseArchanaBookingCreate, ArchanaCatalogCreate, ArchanaCatalogUpdate
from app.core.exceptions import ServiceException
from datetime import datetime, timezone, timedelta
from app.repositories.archana_repository import ArchanaRepository
from app.services.accounting_service import AccountingService
from app.utils.timezone_utils import local_to_utc
from app.core.database import engine



logger = logging.getLogger("tms.services.archana")

class DeityService:

    @staticmethod
    async def get_deities(db: AsyncSession, temple_id: str, active_only: bool = False) -> List[DeityMaster]:
        return await ArchanaRepository.get_deities(db, UUID(temple_id), active_only)

    @staticmethod
    async def create_deity(db: AsyncSession, temple_id: UUID, deity_in: Dict[str, Any], created_by: UUID) -> DeityMaster:
        name = deity_in.get("deity_name", "").strip()
        if not name:
            logger.warning("Deity creation failed: Name missing for temple %s", temple_id)
            raise ServiceException("Deity name is required", "NAME_REQUIRED")
        
        # Duplicate Check (Normalized)
        existing = await ArchanaRepository.get_deity_by_name(db, temple_id, name)
        if existing:
            logger.info("Deity creation rejected: Duplicate name '%s' for temple %s", name, temple_id)
            raise ServiceException(f"Deity '{name}' already exists in this temple.", "DUPLICATE_DEITY")

        try:
            deity = DeityMaster(
                tenant_id=temple_id,
                deity_name=name,
                normalized_name=name.lower(),
                display_name=deity_in.get("display_name", "").strip() or None,
                icon=deity_in.get("icon"),
                display_order=deity_in.get("display_order", 0),
                created_by=created_by
            )
            await ArchanaRepository.create_deity(db, deity)
            
            audit = DeityAudit(
                deity_id=deity.id,
                action="CREATED",
                actor_id=created_by,
                new_state={"name": deity.deity_name}
            )
            db.add(audit)
            await db.commit()
            await db.refresh(deity)
            
            logger.info("Deity created successfully: %s (ID: %s) by user %s", name, deity.id, created_by)
            return deity
        except Exception as e:
            logger.error("Failed to persist deity '%s' for temple %s: %s", name, temple_id, str(e), exc_info=True)
            await db.rollback()
            raise ServiceException("Internal failure while saving deity. Please try again.", "SAVE_FAILED")

    @staticmethod
    async def update_deity(db: AsyncSession, deity_id: UUID, update_in: Dict[str, Any], actor_id: UUID) -> DeityMaster:
        deity = await ArchanaRepository.get_deity(db, deity_id)
        if not deity:
            raise ServiceException("Deity not found", "DEITY_NOT_FOUND", status_code=404)
        
        old_state = {"name": deity.deity_name, "status": deity.status}
        
        # Handle name change normalization and duplicate check
        if "deity_name" in update_in:
            new_name = update_in["deity_name"].strip()
            if not new_name:
                raise ServiceException("Deity name cannot be empty", "NAME_REQUIRED")
            
            if new_name.lower() != deity.normalized_name:
                existing = await ArchanaRepository.get_deity_by_name(db, deity.tenant_id, new_name)
                if existing:
                    raise ServiceException(f"Deity '{new_name}' already exists.", "DUPLICATE_DEITY")
                deity.deity_name = new_name
                deity.normalized_name = new_name.lower()

        for field, value in update_in.items():
            if field == "deity_name":
                continue
            if hasattr(deity, field):
                setattr(deity, field, value)
        
        audit = DeityAudit(
            deity_id=deity.id,
            action="UPDATED",
            actor_id=actor_id,
            old_state=old_state,
            new_state={"name": deity.deity_name, "status": deity.status}
        )
        db.add(audit)
        await db.commit()
        await db.refresh(deity)
        return deity

class ArchanaService:
    @staticmethod
    async def create_booking(
        db: AsyncSession,
        booking_in: EnterpriseArchanaBookingCreate,
        temple_id: str,
        created_by_id: Optional[str] = None,
        device_id: Optional[str] = None,
        offline_event_id: Optional[str] = None
    ) -> EnterpriseArchanaBooking:
        tid = UUID(str(temple_id))
        
        # 1. Idempotency Check
        if booking_in.idempotency_key:
            existing = await ArchanaRepository.get_booking_by_idempotency_key(db, tid, booking_in.idempotency_key)
            if existing:
                logger.info(f"Duplicate request detected via idempotency key: {booking_in.idempotency_key}")
                return existing

        # 2. Duplicate Window Check (Phase 1.D)
        # Prevent same devotee booking same archana within 5 minutes (configurable window)
        duplicate_window = 5 # minutes (todo: load from temple settings)
        duplicate = await ArchanaRepository.check_duplicate_booking(
            db, tid, booking_in.primary_devotee_name, booking_in.phone_number, duplicate_window
        )
        if duplicate:
            raise ServiceException(
                f"A similar booking was already created for {booking_in.primary_devotee_name} in the last {duplicate_window} minutes.",
                "DUPLICATE_BOOKING",
                status_code=400
            )

        # 3. Generate Ref ID
        count = await ArchanaRepository.get_booking_count(db, tid)
        now = datetime.now(timezone.utc)
        ref_id = f"AR-{now.strftime('%Y%m%d')}-{str(count + 1).zfill(4)}"

        # 2. Fetch Catalog (Approved items only)
        catalog_items = await ArchanaRepository.get_catalog(db, tid, status=CatalogStatus.APPROVED)
        catalog = {str(s.id): s for s in catalog_items}
        
        delivery_charge = booking_in.delivery_charge if booking_in.prasadam_collection == "Deliver to Temple Devotees" else 0.0
        booking = EnterpriseArchanaBooking(
            temple_id=tid,
            ref_id=ref_id,
            idempotency_key=booking_in.idempotency_key,
            primary_devotee_name=booking_in.primary_devotee_name,
            phone_number=booking_in.phone_number,
            email=booking_in.email,
            whatsapp_consent=booking_in.whatsapp_consent,
            booking_date=booking_in.booking_date or now,
            ritual_time=local_to_utc(booking_in.ritual_time),
            priority_slot=booking_in.priority_slot,
            dakshina=booking_in.dakshina,
            delivery_charge=delivery_charge,
            payment_mode=booking_in.payment_mode,
            booking_mode=booking_in.booking_mode,
            prasadam_collection=booking_in.prasadam_collection,
            remarks=booking_in.remarks,
            status=ArchanaStatus.CONFIRMED,
            created_by=UUID(created_by_id) if created_by_id else None
        )

        total_amount = 0.0
        for m_in in booking_in.members:
            member = ArchanaBookingMember(
                name=m_in.name,
                nakshatra=m_in.nakshatra,
                is_primary=m_in.is_primary
            )
            for i_in in m_in.items:
                service = catalog.get(str(i_in.service_id))
                if not service:
                    logger.warning(f"Service {i_in.service_id} not found or not approved")
                    continue
                
                item_total = service.price * i_in.quantity
                total_amount += item_total
                
                # PHASE 4: IMMUTABLE SNAPSHOTS
                item = ArchanaBookingItem(
                    service_id=service.id,
                    quantity=i_in.quantity,
                    price_at_booking=service.price,
                    ritual_name_snapshot=service.name,
                    ritual_deity_snapshot=m_in.manual_deity_name or (service.deity.deity_name if service.deity else "General"),
                    ritual_duration_snapshot=service.duration_minutes,
                    ritual_version_id=service.version,
                    total_price=item_total
                )
                member.items.append(item)
            booking.members.append(member)

        booking.total_amount = total_amount
        booking.delivery_charge = delivery_charge
        booking.grand_total = total_amount + booking_in.dakshina + delivery_charge

        # 3. Persist
        await ArchanaRepository.create_booking(db, booking)
        await db.flush()

        # 4. Initialize Queue Entry (Only if not a future booking)
        is_future = False
        ritual_time = booking.ritual_time
        if ritual_time:
            is_future = ritual_time > now
            logger.info(
                f"Booking {ref_id}: ritual_time={ritual_time.isoformat()}, "
                f"now={now.isoformat()}, is_future={is_future}"
            )
        else:
            logger.info(f"Booking {ref_id}: ritual_time is None/empty, treating as immediate booking")

        queue_entry = None
        queue_token = None

        if not is_future:
            logger.info(f"Booking {ref_id}: Creating queue entry (is_future={is_future})")
            # Base sequential token on total queue entries to prevent duplicates/gaps
            queue_count_res = await db.execute(
                select(func.count(RitualQueue.id)).filter(RitualQueue.temple_id == tid)
            )
            queue_count = queue_count_res.scalar() or 0
            queue_token = f"T-{str(queue_count + 1).zfill(3)}"

            waiting_count_res = await db.execute(
                select(func.count(RitualQueue.id)).filter(
                    RitualQueue.temple_id == tid, 
                    RitualQueue.status == QueueStatus.WAITING
                )
            )
            waiting_count = waiting_count_res.scalar() or 0
            est_start = now + timedelta(minutes=waiting_count * 10)

            queue_entry = RitualQueue(
                temple_id=tid,
                booking_id=booking.id,
                token_number=queue_token,
                status=QueueStatus.WAITING,
                priority=10 if booking.priority_slot else 0,
                estimated_start_time=est_start
            )
            db.add(queue_entry)
            await db.flush()
        else:
            logger.info(f"Booking {ref_id}: Skipping queue (future booking, ritual_time={ritual_time.isoformat()})")

        # 5. Accounting Integration
        if booking.grand_total > 0:
            await AccountingService.record_booking_ledger(
                db=db, temple_id=tid, booking=booking, recorded_by=booking.created_by
            )
            # Master Ledger SOT Unification: Write booking to transactions table
            from app.services.transaction_service import TransactionService
            txn_source = "manual" if (booking.booking_channel or "").upper() == "COUNTER" else "system"
            await TransactionService.create_transaction(
                db=db,
                temple_id=str(tid),
                txn_type="income",
                category="archana",
                amount=booking.grand_total,
                description=f"Archana Booking {booking.ref_id} for {booking.primary_devotee_name}",
                reference_id=booking.ref_id,
                source=txn_source
            )

        # 5.1 Initialize Executions
        if queue_entry:
            from app.services.archana_lifecycle_service import ArchanaLifecycleService
            await ArchanaLifecycleService.initialize_executions(db, queue_entry.id)

        # 6. Audit
        audit_state = {"ref_id": ref_id, "total": booking.grand_total}
        if queue_token:
            audit_state["token"] = queue_token
        else:
            audit_state["status"] = "UPCOMING"

        audit = ArchanaBookingAudit(
            booking_id=booking.id, action="CREATED", actor_id=booking.created_by,
            new_state=audit_state
        )
        db.add(audit)

        await db.commit()

        # Load fully populated booking with relations before returning
        from sqlalchemy.orm import selectinload
        stmt = select(EnterpriseArchanaBooking).options(
            selectinload(EnterpriseArchanaBooking.members).selectinload(ArchanaBookingMember.items),
            selectinload(EnterpriseArchanaBooking.queue_entry)
        ).filter(EnterpriseArchanaBooking.id == booking.id)
        res = await db.execute(stmt)
        booking = res.unique().scalar_one()
        return booking

    @staticmethod
    async def promote_matured_bookings(db: AsyncSession, temple_id: Any) -> int:
        """Promote bookings whose ritual time has arrived to the operational queue."""
        tid = UUID(str(temple_id))
        now = datetime.now(timezone.utc)

        # Select bookings with ritual_time <= now that do not have a RitualQueue entry
        query = select(EnterpriseArchanaBooking).outerjoin(
            RitualQueue, EnterpriseArchanaBooking.id == RitualQueue.booking_id
        ).filter(
            EnterpriseArchanaBooking.temple_id == tid,
            EnterpriseArchanaBooking.status == ArchanaStatus.CONFIRMED,
            EnterpriseArchanaBooking.ritual_time <= now,
            RitualQueue.id == None
        ).order_by(EnterpriseArchanaBooking.ritual_time.asc())

        if engine.dialect.name != "sqlite":
            query = query.with_for_update(of=EnterpriseArchanaBooking)

        res = await db.execute(query)
        matured_bookings = res.scalars().all()

        if not matured_bookings:
            return 0

        # Get count of existing queue entries for token generation
        queue_count_res = await db.execute(
            select(func.count(RitualQueue.id)).filter(RitualQueue.temple_id == tid)
        )
        queue_count = queue_count_res.scalar() or 0

        promoted_count = 0
        from app.services.archana_lifecycle_service import ArchanaLifecycleService

        for booking in matured_bookings:
            queue_count += 1
            token = f"T-{str(queue_count).zfill(3)}"

            # Estimate start time based on waiting queue count
            waiting_count_res = await db.execute(
                select(func.count(RitualQueue.id)).filter(
                    RitualQueue.temple_id == tid, 
                    RitualQueue.status == QueueStatus.WAITING
                )
            )
            waiting_count = waiting_count_res.scalar() or 0
            est_start = now + timedelta(minutes=waiting_count * 10)

            queue_entry = RitualQueue(
                temple_id=tid,
                booking_id=booking.id,
                token_number=token,
                status=QueueStatus.WAITING,
                priority=10 if booking.priority_slot else 0,
                estimated_start_time=est_start
            )
            db.add(queue_entry)
            await db.flush()

            # Initialize executions
            await ArchanaLifecycleService.initialize_executions(db, queue_entry.id)

            # Audit log for promotion
            audit = ArchanaBookingAudit(
                booking_id=booking.id,
                action="PROMOTED_TO_QUEUE",
                actor_id=None,  # System automated
                new_state={"token": token, "promotion_time": now.isoformat()}
            )
            db.add(audit)
            promoted_count += 1

        await db.commit()
        logger.info(f"Promoted {promoted_count} matured bookings to queue for temple {tid}")
        return promoted_count

    @staticmethod
    async def propose_catalog_item(
        db: AsyncSession, 
        temple_id: UUID, 
        item_in: ArchanaCatalogCreate, 
        requested_by: UUID
    ) -> ArchanaCatalog:
        """Counter Staff workflow: propose a new ritual or update."""
        item = ArchanaCatalog(
            temple_id=temple_id,
            name=item_in.name,
            price=item_in.price,
            deity_id=item_in.deity_id,
            duration_minutes=item_in.duration_minutes,
            remarks=getattr(item_in, 'remarks', None),
            description=item_in.description,
            image_url=item_in.image_url,
            status=CatalogStatus.PENDING_APPROVAL,
            requested_by=requested_by
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)
        return item

    @staticmethod
    async def approve_catalog_item(
        db: AsyncSession, 
        item_id: UUID, 
        approved_by: UUID,
        final_price: Optional[float] = None
    ) -> ArchanaCatalog:
        """Manager workflow: approve and version the ritual."""
        item = await ArchanaRepository.get_catalog_item(db, item_id)
        if not item:
            raise ServiceException("Ritual not found", "NOT_FOUND", status_code=404)
            
        # Create a version before updating (if it was already approved once)
        if item.status == CatalogStatus.APPROVED:
            # Update effective_to of the previous version
            prev_version_stmt = select(CatalogVersion).filter(
                CatalogVersion.catalog_id == item.id,
                CatalogVersion.version == item.version,
                CatalogVersion.effective_to == None
            )
            prev_version_res = await db.execute(prev_version_stmt)
            prev_version = prev_version_res.scalar_one_or_none()
            if prev_version:
                prev_version.effective_to = datetime.now(timezone.utc)

            version = CatalogVersion(
                catalog_id=item.id,
                version=item.version,
                price=item.price,
                metadata_snapshot={
                    "name": item.name,
                    "deity_id": str(item.deity_id) if item.deity_id else None,
                    "duration": item.duration_minutes
                },
                effective_from=item.updated_at or item.created_at,
                effective_to=datetime.now(timezone.utc),
                created_by=approved_by
            )
            db.add(version)
            item.version += 1
            
        if final_price is not None:
            item.price = final_price
            
        item.status = CatalogStatus.APPROVED
        item.approved_by = approved_by
        item.is_active = True
        
        await db.commit()
        await db.refresh(item)
        return item

    @staticmethod
    async def reject_catalog_item(
        db: AsyncSession, 
        item_id: UUID, 
        reason: str,
        rejected_by: UUID
    ) -> ArchanaCatalog:
        item = await ArchanaRepository.get_catalog_item(db, item_id)
        if not item:
            raise ServiceException("Ritual not found", "NOT_FOUND", status_code=404)
        
        item.status = CatalogStatus.DRAFT
        item.rejection_reason = reason
        await db.commit()
        await db.refresh(item)
        return item

    @staticmethod
    async def get_catalog(db: AsyncSession, temple_id: str, status: Optional[CatalogStatus] = None):
        return await ArchanaRepository.get_catalog(db, UUID(temple_id), status)

    @staticmethod
    async def create_catalog_item(
        db: AsyncSession,
        temple_id: UUID,
        item_in: ArchanaCatalogCreate,
        created_by: UUID,
        auto_approve: bool = False
    ) -> ArchanaCatalog:
        """Manager workflow: directly create and optionally auto-approve a catalog item."""
        
        # Validation
        if not item_in.name or not item_in.name.strip():
            raise ServiceException("Archana Name is required", "NAME_REQUIRED")
        
        if item_in.price <= 0:
            raise ServiceException("Price must be greater than ₹0", "INVALID_PRICE")
            
        if not item_in.deity_id:
            raise ServiceException("Deity is required", "DEITY_REQUIRED")

        # Duplicate Check
        existing = await ArchanaRepository.get_catalog_item_by_name(db, temple_id, item_in.name.strip())
        if existing:
            raise ServiceException(f"An Archana Service with the name '{item_in.name}' already exists.", "DUPLICATE_NAME")

        item = ArchanaCatalog(
            temple_id=temple_id,
            name=item_in.name.strip(),
            price=item_in.price,
            deity_id=item_in.deity_id,
            duration_minutes=item_in.duration_minutes,
            remarks=item_in.remarks.strip() if item_in.remarks else None,
            description=item_in.description.strip() if item_in.description else None,
            image_url=item_in.image_url,
            daily_limit=item_in.daily_limit,
            is_active=True if auto_approve else item_in.is_active,
            status=CatalogStatus.APPROVED if auto_approve else CatalogStatus.PENDING_APPROVAL,
            requested_by=created_by,
            approved_by=created_by if auto_approve else None,
        )
        db.add(item)
        await db.commit()
        await db.refresh(item)
        logger.info(f"Catalog item created: {item.name} (₹{item.price}) by {created_by}")
        return item

    @staticmethod
    async def update_catalog_item(
        db: AsyncSession,
        item_id: UUID,
        update_in: ArchanaCatalogUpdate,
        updated_by: UUID
    ) -> ArchanaCatalog:
        """Update an existing catalog item. Creates a version snapshot if price changes."""
        item = await ArchanaRepository.get_catalog_item(db, item_id)
        if not item:
            raise ServiceException("Service not found", "SERVICE_NOT_FOUND", status_code=404)

        # Validation for updates
        if update_in.name is not None:
            if not update_in.name.strip():
                raise ServiceException("Archana Name cannot be empty", "NAME_REQUIRED")
            
            # Check for duplicate if name changed
            if update_in.name.strip() != item.name:
                existing = await ArchanaRepository.get_catalog_item_by_name(db, item.temple_id, update_in.name.strip())
                if existing:
                    raise ServiceException(f"An Archana Service with the name '{update_in.name}' already exists.", "DUPLICATE_NAME")

        if update_in.price is not None and update_in.price <= 0:
            raise ServiceException("Price must be greater than ₹0", "INVALID_PRICE")

        old_price = item.price

        # Apply updates
        for field, value in update_in.model_dump(exclude_unset=True).items():
            if isinstance(value, str):
                setattr(item, field, value.strip() if value else None)
            else:
                setattr(item, field, value)

        # If price changed, create version snapshot
        if update_in.price is not None and update_in.price != old_price:
            version = CatalogVersion(
                catalog_id=item.id,
                version=item.version,
                price=old_price,
                metadata_snapshot={
                    "name": item.name,
                    "deity_id": str(item.deity_id) if item.deity_id else None,
                    "duration": item.duration_minutes
                },
                effective_from=item.updated_at or item.created_at,
                effective_to=datetime.now(timezone.utc),
                created_by=updated_by
            )
            db.add(version)
            item.version += 1
            logger.info(f"Price version created for {item.name}: ₹{old_price} → ₹{update_in.price}")

        await db.commit()
        await db.refresh(item)
        return item

    @staticmethod
    async def archive_catalog_item(db: AsyncSession, item_id: UUID) -> ArchanaCatalog:
        """Archive a catalog item (soft delete)."""
        item = await ArchanaRepository.get_catalog_item(db, item_id)
        if not item:
            raise ServiceException("Service not found", "NOT_FOUND", status_code=404)
        item.status = CatalogStatus.ARCHIVED
        item.is_active = False
        await db.commit()
        await db.refresh(item)
        return item

    @staticmethod
    async def toggle_catalog_item(db: AsyncSession, item_id: UUID) -> ArchanaCatalog:
        """Toggle active/inactive state for an approved catalog item."""
        item = await ArchanaRepository.get_catalog_item(db, item_id)
        if not item:
            raise ServiceException("Service not found", "NOT_FOUND", status_code=404)
        item.is_active = not item.is_active
        await db.commit()
        await db.refresh(item)
        return item

    @staticmethod
    async def update_queue_status(db: AsyncSession, queue_id: UUID, status: QueueStatus, priest_id: Optional[UUID] = None) -> RitualQueue:
        return await ArchanaRepository.update_queue_status(db, queue_id, status, priest_id)

    @staticmethod
    async def get_bookings(db: AsyncSession, temple_id: str, skip: int = 0, limit: int = 50):
        return await ArchanaRepository.get_bookings(db, UUID(temple_id), skip, limit)

    @staticmethod
    async def get_kpis(db: AsyncSession, temple_id: str):
        return await ArchanaRepository.get_kpis(db, UUID(temple_id))
    
    @staticmethod
    async def get_queue(db: AsyncSession, temple_id: str):
        return await ArchanaRepository.get_queue(db, UUID(temple_id))


