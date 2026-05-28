"""Archana Booking API endpoints with simplified enterprise operational layers."""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional, Dict, Any
from uuid import UUID
from app.api.deps import get_db, get_current_user, get_current_temple_id
from app.schemas.domain import TokenData
from app.schemas.archana import (
    EnterpriseArchanaBookingCreate, 
    EnterpriseArchanaBookingResponse,
    ArchanaCatalogResponse,
    ArchanaCatalogCreate,
    ArchanaCatalogUpdate,
    DashboardKPIs,
    RitualQueueResponse,
    CatalogStatus
)
from app.services.archana_service import ArchanaService, DeityService

from app.services.accounting_service import AccountingService
from app.services.receipt_service import ReceiptService
from app.core.response import api_response
from app.models.archana import QueueStatus
from app.utils.timezone_utils import local_to_utc, utc_to_ist

logger = logging.getLogger("tms.api.archana_bookings")

router = APIRouter()

async def check_booking_locked(db: AsyncSession, temple_id: UUID, booking) -> bool:
    from app.models.accounting import DailySettlement
    from sqlalchemy import func
    
    booking_date_only = booking.booking_date.date()
    query = select(DailySettlement).filter(
        DailySettlement.temple_id == temple_id,
        func.date(DailySettlement.settlement_date) == booking_date_only,
        DailySettlement.status == "CLOSED"
    )
    res = await db.execute(query)
    settlement = res.scalars().first()
    
    if not settlement:
        return False
        
    if booking.created_at and settlement.closed_at:
        return booking.created_at <= settlement.closed_at
        
    return True


@router.get("/kpis")
async def get_archana_kpis(
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    await ArchanaService.promote_matured_bookings(db, temple_id)
    data = await ArchanaService.get_kpis(db, temple_id)
    fin_kpis = await AccountingService.get_financial_kpis(db, UUID(temple_id))
    data.update(fin_kpis)
    return api_response(data=data)

# --- Deity Management ---
@router.get("/deities")
async def list_deities(
    active_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    data = await DeityService.get_deities(db, temple_id, active_only)
    return api_response(data=data)

@router.post("/deities")
async def create_deity(
    deity_in: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
    current_user: TokenData = Depends(get_current_user),
):
    data = await DeityService.create_deity(db, UUID(temple_id), deity_in, UUID(current_user.sub))
    return api_response(data=data, message="Deity added successfully")

@router.patch("/deities/{deity_id}")
async def update_deity(
    deity_id: UUID,
    update_in: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    logger.info(f"User {current_user.sub} updating deity {deity_id} with fields: {list(update_in.keys())}")
    data = await DeityService.update_deity(db, deity_id, update_in, UUID(current_user.sub))
    return api_response(data=data, message="Deity updated")

# --- Catalog Management ---
@router.get("/catalog")
async def get_archana_catalog(
    status: Optional[CatalogStatus] = Query(None),
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    """Fetches rituals. Defaults to APPROVED for counter staff."""
    data = await ArchanaService.get_catalog(db, temple_id, status)
    return api_response(data=data)

@router.post("/catalog/propose")
async def propose_ritual(
    item_in: ArchanaCatalogCreate,
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
    current_user: TokenData = Depends(get_current_user),
):
    """Workflow: Counter staff proposing a new ritual entry."""
    data = await ArchanaService.propose_catalog_item(
        db, UUID(temple_id), item_in, UUID(current_user.sub)
    )
    return api_response(data=data, message="Ritual proposal submitted for approval.")

@router.post("/catalog/{item_id}/approve")
async def approve_ritual(
    item_id: UUID,
    final_price: Optional[float] = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """Workflow: Manager approving a ritual entry."""
    data = await ArchanaService.approve_catalog_item(
        db, item_id, UUID(current_user.sub), final_price
    )
    return api_response(data=data, message="Ritual entry approved and activated.")

@router.post("/catalog/{item_id}/reject")
async def reject_ritual(
    item_id: UUID,
    reason: str = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """Workflow: Manager rejecting a ritual proposal."""
    data = await ArchanaService.reject_catalog_item(
        db, item_id, reason, UUID(current_user.sub)
    )
    return api_response(data=data, message="Ritual proposal rejected.")

@router.post("/catalog/create")
async def create_catalog_item(
    item_in: ArchanaCatalogCreate,
    auto_approve: bool = Query(True),
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
    current_user: TokenData = Depends(get_current_user),
):
    """Manager workflow: create a new catalog item with optional auto-approval."""
    data = await ArchanaService.create_catalog_item(
        db, UUID(temple_id), item_in, UUID(current_user.sub), auto_approve=auto_approve
    )
    return api_response(data=data, message="Archana service created successfully.")

@router.put("/catalog/{item_id}")
async def update_catalog_item(
    item_id: UUID,
    update_in: ArchanaCatalogUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """Update a catalog item. Price changes create immutable version snapshots."""
    data = await ArchanaService.update_catalog_item(
        db, item_id, update_in, UUID(current_user.sub)
    )
    return api_response(data=data, message="Archana service updated.")

@router.post("/catalog/{item_id}/archive")
async def archive_catalog_item(
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Archive a catalog item (soft delete)."""
    data = await ArchanaService.archive_catalog_item(db, item_id)
    return api_response(data=data, message="Service archived.")

@router.post("/catalog/{item_id}/toggle")
async def toggle_catalog_item(
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Toggle active/inactive status for a catalog item."""
    data = await ArchanaService.toggle_catalog_item(db, item_id)
    return api_response(data=data, message="Service status toggled.")


@router.get("/catalog/all")
async def get_all_catalog(
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    """Get ALL catalog items regardless of status (for management view)."""
    from sqlalchemy.future import select as sel
    from sqlalchemy.orm import selectinload
    from app.models.archana import ArchanaCatalog as AC
    result = await db.execute(
        sel(AC).filter(AC.temple_id == UUID(temple_id))
        .options(selectinload(AC.deity))
        .order_by(AC.name)
    )
    items = result.scalars().all()
    return api_response(data=items)


@router.post("")
async def create_archana_booking(
    booking_in: EnterpriseArchanaBookingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    data = await ArchanaService.create_booking(
        db=db, 
        booking_in=booking_in, 
        temple_id=temple_id,
        created_by_id=current_user.sub,
    )
    # Serialize data using EnterpriseArchanaBookingResponse to avoid infinite recursion in jsonable_encoder
    serialized_data = EnterpriseArchanaBookingResponse.model_validate(data).model_dump(mode="json")
    return api_response(data=serialized_data, message="Booking confirmed successfully")

@router.post("/close-day")
async def close_day(
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
    current_user: TokenData = Depends(get_current_user),
):
    actual_total = payload.get("actual_total", 0.0)
    variance_reason = payload.get("variance_reason")
    
    data = await AccountingService.close_day(
        db=db,
        temple_id=UUID(temple_id),
        actual_total=float(actual_total),
        closed_by=UUID(current_user.sub),
        variance_reason=variance_reason
    )
    await db.commit()
    return api_response(data={"settlement_id": str(data.id)}, message="Business day closed and settled successfully.")


@router.get("")
async def list_archana_bookings(
    skip: int = 0,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    await ArchanaService.promote_matured_bookings(db, temple_id)
    data = await ArchanaService.get_bookings(db=db, temple_id=temple_id, skip=skip, limit=limit)
    return api_response(data=data)

@router.get("/queue")
async def get_ritual_queue(
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    await ArchanaService.promote_matured_bookings(db, temple_id)
    data = await ArchanaService.get_queue(db, temple_id)
    return api_response(data=data)

@router.patch("/queue/{queue_id}/status")
async def update_queue_status(
    queue_id: UUID,
    status: QueueStatus = Body(..., embed=True),
    priest_id: Optional[UUID] = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
):
    data = await ArchanaService.update_queue_status(db, queue_id, status, priest_id)
    return api_response(data=data, message="Ritual progress updated.")

@router.post("/executions/{execution_id}/start")
async def start_execution(
    execution_id: UUID,
    priest_id: UUID = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    import logging
    logger = logging.getLogger("tms.api.archana")
    logger.info(f"User {current_user.sub} attempting to START execution {execution_id} for priest {priest_id}")
    
    from app.services.archana_lifecycle_service import ArchanaLifecycleService
    try:
        data = await ArchanaLifecycleService.start_ritual(
            db, execution_id, priest_id, UUID(current_user.sub)
        )
        return api_response(data=data, message="Ritual started.")
    except Exception as e:
        logger.error(f"Failed to start ritual {execution_id}: {str(e)}", exc_info=True)
        raise e

@router.post("/executions/start-selected")
async def start_selected_executions(
    execution_ids: List[UUID] = Body(..., embed=True),
    priest_id: UUID = Body(..., embed=True),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    import logging
    logger = logging.getLogger("tms.api.archana")
    logger.info(f"User {current_user.sub} attempting to START GROUPED executions {execution_ids} for priest {priest_id}")
    
    from app.services.archana_lifecycle_service import ArchanaLifecycleService
    try:
        data = await ArchanaLifecycleService.start_grouped_rituals(
            db, execution_ids, priest_id, UUID(current_user.sub), UUID(temple_id)
        )
        return api_response(data=data, message=f"{len(data)} rituals started together.")
    except Exception as e:
        logger.error(f"Failed to start grouped rituals {execution_ids}: {str(e)}", exc_info=True)
        raise e

@router.post("/executions/{execution_id}/complete")
async def complete_execution(
    execution_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    import logging
    logger = logging.getLogger("tms.api.archana")
    logger.info(f"User {current_user.sub} attempting to COMPLETE execution {execution_id}")
    
    from app.services.archana_lifecycle_service import ArchanaLifecycleService
    try:
        data = await ArchanaLifecycleService.complete_ritual(
            db, execution_id, UUID(current_user.sub)
        )
        return api_response(data=data, message="Ritual completed.")
    except Exception as e:
        logger.error(f"Failed to complete ritual {execution_id}: {str(e)}", exc_info=True)
        raise e

@router.get("/{booking_id}/receipt")
async def get_booking_receipt(
    booking_id: UUID,
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    # Lookup booking and generate manifest
    from app.models.archana import EnterpriseArchanaBooking, ArchanaBookingMember
    from sqlalchemy.future import select
    from sqlalchemy.orm import joinedload
    
    query = select(EnterpriseArchanaBooking).options(
        joinedload(EnterpriseArchanaBooking.members).joinedload(ArchanaBookingMember.items),
        joinedload(EnterpriseArchanaBooking.queue_entry)
    ).filter(EnterpriseArchanaBooking.id == booking_id, EnterpriseArchanaBooking.temple_id == UUID(temple_id))
    
    res = await db.execute(query)
    booking = res.unique().scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
        
    manifest = await ReceiptService.get_receipt_manifest(db, booking)
    logger.info(f"Receipt generated for booking {booking_id}")
    return api_response(data=manifest)


@router.get("/{booking_id}/details")
async def get_booking_details(
    booking_id: UUID,
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
    current_user: TokenData = Depends(get_current_user),
):
    """Get full booking details including audit trail for the booking detail viewer."""
    await ArchanaService.promote_matured_bookings(db, temple_id)
    from app.models.archana import (
        EnterpriseArchanaBooking, ArchanaBookingMember, ArchanaBookingItem,
        ArchanaBookingAudit, RitualQueue, ArchanaExecution
    )
    from sqlalchemy.future import select
    from sqlalchemy.orm import joinedload, selectinload
    
    # Fetch booking with all relations
    query = select(EnterpriseArchanaBooking).options(
        selectinload(EnterpriseArchanaBooking.members).selectinload(ArchanaBookingMember.items),
        joinedload(EnterpriseArchanaBooking.queue_entry).selectinload(RitualQueue.executions),
    ).filter(
        EnterpriseArchanaBooking.id == booking_id,
        EnterpriseArchanaBooking.temple_id == UUID(temple_id)
    )
    
    res = await db.execute(query)
    booking = res.unique().scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    
    # Fetch audit trail
    audit_query = select(ArchanaBookingAudit).filter(
        ArchanaBookingAudit.booking_id == booking_id
    ).order_by(ArchanaBookingAudit.timestamp.asc())
    audit_res = await db.execute(audit_query)
    audits = audit_res.scalars().all()
    
    # Build comprehensive response
    queue = booking.queue_entry
    executions = queue.executions if queue else []
    
    # Determine timeline states
    timeline = []
    timeline.append({"state": "CREATED", "timestamp": booking.created_at.isoformat() if booking.created_at else None, "completed": True})
    timeline.append({"state": "VERIFIED", "timestamp": booking.created_at.isoformat() if booking.created_at else None, "completed": booking.status.value in ['CONFIRMED', 'COMPLETED', 'IN_PROGRESS']})
    
    any_in_progress = any(ex.status.value == 'IN_PROGRESS' for ex in executions)
    any_completed = any(ex.status.value == 'COMPLETED' for ex in executions)
    all_completed = all(ex.status.value == 'COMPLETED' for ex in executions) if executions else False
    
    start_time = None
    completion_time = None
    for ex in executions:
        if ex.start_time:
            if not start_time or ex.start_time < start_time:
                start_time = ex.start_time
        if ex.completed_at:
            if not completion_time or ex.completed_at > completion_time:
                completion_time = ex.completed_at
    
    timeline.append({"state": "IN_PROGRESS", "timestamp": start_time.isoformat() if start_time else None, "completed": any_in_progress or any_completed})
    timeline.append({"state": "COMPLETED", "timestamp": completion_time.isoformat() if completion_time else None, "completed": all_completed})
    
    # Members and items
    members_data = []
    for m in booking.members:
        items_data = []
        for item in m.items:
            items_data.append({
                "id": str(item.id),
                "service_id": str(item.service_id),
                "ritual_name": item.ritual_name_snapshot,
                "deity": item.ritual_deity_snapshot,
                "quantity": item.quantity,
                "price": item.price_at_booking,
                "total": item.total_price,
                "duration": item.ritual_duration_snapshot,
            })
        members_data.append({
            "id": str(m.id),
            "name": m.name,
            "nakshatra": m.nakshatra,
            "is_primary": m.is_primary,
            "items": items_data,
        })
    
    # Audit trail
    audit_data = [{
        "action": a.action,
        "actor_id": str(a.actor_id) if a.actor_id else None,
        "timestamp": a.timestamp.isoformat() if a.timestamp else None,
        "old_state": a.old_state,
        "new_state": a.new_state,
    } for a in audits]
    
    # Fetch creator profile
    creator_name = None
    if booking.created_by:
        from app.models.domain import User
        creator_query = select(User).filter(User.id == booking.created_by)
        creator_res = await db.execute(creator_query)
        creator = creator_res.scalar_one_or_none()
        if creator:
            display_name = creator.name.strip() if creator.name else ""
            if not display_name:
                display_name = creator.user_id
            role_str = creator.role.replace('_', ' ') if creator.role else "STAFF"
            creator_name = f"{display_name} ({role_str})"
        else:
            creator_name = str(booking.created_by)

    # Fetch refunds
    from app.models.archana import ArchanaRefund
    refund_query = select(ArchanaRefund).filter(ArchanaRefund.booking_id == booking_id)
    refund_res = await db.execute(refund_query)
    refunds = refund_res.scalars().all()
    refunds_data = [{
        "id": str(r.id),
        "ref_id": r.ref_id,
        "refund_method": r.refund_method,
        "refund_status": r.refund_status,
        "status": r.status,
        "amount": r.amount,
        "reason": r.reason,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in refunds]

    is_locked = await check_booking_locked(db, UUID(temple_id), booking)
    
    # Calculate computed status
    from app.models.archana import ArchanaStatus, QueueStatus
    computed_status = "Waiting"
    if booking.status == ArchanaStatus.CANCELLED or booking.status == "CANCELLED":
        computed_status = "Cancelled"
    elif booking.status == ArchanaStatus.COMPLETED or booking.status == "COMPLETED":
        computed_status = "Completed"
    elif queue:
        if queue.status == QueueStatus.CANCELLED or queue.status == "CANCELLED":
            computed_status = "Cancelled"
        elif queue.status == QueueStatus.COMPLETED or queue.status == "COMPLETED":
            computed_status = "Completed"
        elif queue.status == QueueStatus.IN_PROGRESS or queue.status == "IN_PROGRESS":
            computed_status = "In Progress"
        elif queue.status == QueueStatus.WAITING or queue.status == "WAITING":
            computed_status = "Waiting"
    elif booking.ritual_time:
        now_utc = datetime.now(timezone.utc)
        r_time = booking.ritual_time
        if r_time.tzinfo is None:
            r_time = r_time.replace(tzinfo=timezone.utc)
        if r_time > now_utc:
            computed_status = "Upcoming"

    detail = {
        "id": str(booking.id),
        "is_locked": is_locked,
        "ref_id": booking.ref_id,
        "primary_devotee_name": booking.primary_devotee_name,
        "phone_number": booking.phone_number,
        "email": booking.email,
        "booking_date": booking.booking_date.isoformat() if booking.booking_date else None,
        "ritual_time": utc_to_ist(booking.ritual_time).isoformat() if booking.ritual_time else None,
        "total_amount": booking.total_amount,
        "dakshina": booking.dakshina,
        "delivery_charge": getattr(booking, "delivery_charge", 0.0),
        "grand_total": booking.grand_total,
        "payment_mode": booking.payment_mode,
        "booking_mode": booking.booking_mode,
        "prasadam_collection": booking.prasadam_collection,
        "status": booking.status.value,
        "computed_status": computed_status,
        "remarks": booking.remarks,
        "created_by": creator_name,
        "created_at": booking.created_at.isoformat() if booking.created_at else None,
        "manual_deity_name": getattr(booking, 'manual_deity_name', None),
        "queue": {
            "token_number": queue.token_number if queue else None,
            "status": queue.status.value if queue else None,
            "start_time": start_time.isoformat() if start_time else None,
            "completion_time": completion_time.isoformat() if completion_time else None,
        } if queue else None,
        "members": members_data,
        "timeline": timeline,
        "audit_trail": audit_data,
        "refunds": refunds_data,
    }
    
    logger.info(f"Booking details fetched for {booking_id} by user {current_user.sub}")
    return api_response(data=detail)
@router.patch("/{booking_id}/update")
async def update_booking_details(
    booking_id: UUID,
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
    current_user: TokenData = Depends(get_current_user),
):
    from app.models.archana import EnterpriseArchanaBooking, RitualQueue, QueueStatus
    
    query = select(EnterpriseArchanaBooking).filter(
        EnterpriseArchanaBooking.id == booking_id,
        EnterpriseArchanaBooking.temple_id == UUID(temple_id)
    )
    res = await db.execute(query)
    booking = res.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
        
    is_locked = await check_booking_locked(db, UUID(temple_id), booking)
    if is_locked:
        raise HTTPException(
            status_code=400,
            detail="This booking is locked because the daily accounts for this date have been confirmed and closed. It cannot be modified."
        )
    
    # Guard: Reject edits after ritual has started
    queue_res = await db.execute(select(RitualQueue).filter(RitualQueue.booking_id == booking_id))
    queue_entry = queue_res.scalar_one_or_none()
    if queue_entry and queue_entry.status in [QueueStatus.IN_PROGRESS, QueueStatus.COMPLETED]:
        raise HTTPException(
            status_code=400,
            detail="Cannot edit booking after the ritual has started."
        )
        
    if "primary_devotee_name" in payload:
        booking.primary_devotee_name = payload["primary_devotee_name"]
    if "phone_number" in payload:
        booking.phone_number = payload["phone_number"]
    if "email" in payload:
        booking.email = payload["email"]
    if "remarks" in payload:
        booking.remarks = payload["remarks"]
    if "payment_mode" in payload:
        booking.payment_mode = payload["payment_mode"]
    if "prasadam_collection" in payload:
        booking.prasadam_collection = payload["prasadam_collection"]
        if booking.prasadam_collection != "Deliver to home":
            booking.delivery_charge = 0.0
    if "delivery_charge" in payload:
        booking.delivery_charge = float(payload["delivery_charge"]) if booking.prasadam_collection == "Deliver to home" else 0.0
    if "ritual_time" in payload:
        if payload["ritual_time"]:
            try:
                time_str = payload["ritual_time"]
                if time_str.endswith("Z"):
                    time_str = time_str[:-1] + "+00:00"
                if "T" in time_str:
                    parsed_dt = datetime.fromisoformat(time_str)
                else:
                    parsed_dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                booking.ritual_time = local_to_utc(parsed_dt)
            except Exception as e:
                logger.error(f"Error parsing ritual_time: {e}")
                raise HTTPException(status_code=400, detail="Invalid ritual_time format. Use ISO format.")
        else:
            booking.ritual_time = None
        
    # Recalculate grand_total
    booking.grand_total = booking.total_amount + booking.dakshina + booking.delivery_charge
        
    from app.models.archana import ArchanaBookingAudit
    audit = ArchanaBookingAudit(
        booking_id=booking.id,
        action="UPDATED",
        actor_id=UUID(current_user.sub),
        new_state=payload
    )
    db.add(audit)
    
    await db.commit()
    return api_response(message="Booking details updated successfully.")


@router.post("/{booking_id}/cancel")
async def cancel_booking(
    booking_id: UUID,
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
    current_user: TokenData = Depends(get_current_user),
):
    from app.models.archana import EnterpriseArchanaBooking, ArchanaStatus, QueueStatus
    from app.models.archana import ArchanaBookingAudit, RitualQueue
    
    query = select(EnterpriseArchanaBooking).filter(
        EnterpriseArchanaBooking.id == booking_id,
        EnterpriseArchanaBooking.temple_id == UUID(temple_id)
    )
    res = await db.execute(query)
    booking = res.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
        
    is_locked = await check_booking_locked(db, UUID(temple_id), booking)
    if is_locked:
        raise HTTPException(
            status_code=400,
            detail="This booking is locked because the daily accounts for this date have been confirmed and closed. It cannot be cancelled."
        )
    
    # Guard: Reject cancellation after ritual has started
    queue_check = await db.execute(select(RitualQueue).filter(RitualQueue.booking_id == booking_id))
    queue_check_entry = queue_check.scalar_one_or_none()
    if queue_check_entry and queue_check_entry.status in [QueueStatus.IN_PROGRESS, QueueStatus.COMPLETED]:
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel booking after the ritual has started."
        )
        
    booking.status = ArchanaStatus.CANCELLED
    
    queue_query = select(RitualQueue).filter(RitualQueue.booking_id == booking_id)
    queue_res = await db.execute(queue_query)
    queue_entry = queue_res.scalar_one_or_none()
    if queue_entry:
        queue_entry.status = QueueStatus.CANCELLED
        
    audit = ArchanaBookingAudit(
        booking_id=booking.id,
        action="CANCELLED",
        actor_id=UUID(current_user.sub),
        new_state={"status": "CANCELLED"}
    )
    db.add(audit)
    
    await db.commit()
    return api_response(message="Booking cancelled successfully.")


@router.get("/refunds")
async def list_refunds(
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
):
    from app.models.archana import ArchanaRefund, EnterpriseArchanaBooking
    
    query = select(ArchanaRefund).filter(
        ArchanaRefund.temple_id == UUID(temple_id)
    ).order_by(ArchanaRefund.created_at.desc())
    res = await db.execute(query)
    refunds = res.scalars().all()
    
    data = []
    for r in refunds:
        b_query = select(EnterpriseArchanaBooking).filter(EnterpriseArchanaBooking.id == r.booking_id)
        b_res = await db.execute(b_query)
        booking = b_res.scalar_one_or_none()
        
        data.append({
            "id": str(r.id),
            "ref_id": r.ref_id,
            "booking_id": str(r.booking_id),
            "booking_ref_id": booking.ref_id if booking else "N/A",
            "primary_devotee_name": booking.primary_devotee_name if booking else "N/A",
            "refund_method": r.refund_method,
            "refund_status": r.refund_status,
            "status": r.status,
            "amount": r.amount,
            "reason": r.reason,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
        
    return api_response(data=data)


@router.post("/refunds")
async def create_refund_request(
    payload: Dict[str, Any] = Body(...),
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
    current_user: TokenData = Depends(get_current_user),
):
    from app.models.archana import ArchanaRefund, EnterpriseArchanaBooking
    import random
    from datetime import datetime
    
    booking_id_str = payload.get("booking_id")
    refund_method = payload.get("refund_method", "Cash")
    refund_status = payload.get("refund_status", "Full")
    amount = float(payload.get("amount", 0.0))
    reason = payload.get("reason", "")
    
    if not booking_id_str:
        raise HTTPException(status_code=400, detail="booking_id is required")
        
    booking_id = UUID(booking_id_str)
    
    b_query = select(EnterpriseArchanaBooking).filter(
        EnterpriseArchanaBooking.id == booking_id,
        EnterpriseArchanaBooking.temple_id == UUID(temple_id)
    )
    b_res = await db.execute(b_query)
    booking = b_res.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
        
    date_str = datetime.now().strftime("%Y%m%d")
    random_num = random.randint(1000, 9999)
    ref_id = f"REF-{date_str}-{random_num}"
    
    refund = ArchanaRefund(
        temple_id=UUID(temple_id),
        ref_id=ref_id,
        booking_id=booking_id,
        refund_method=refund_method,
        refund_status=refund_status,
        status="PENDING",
        amount=amount,
        reason=reason,
        created_by=UUID(current_user.sub)
    )
    db.add(refund)
    await db.flush()
    
    from app.models.archana import ArchanaBookingAudit
    audit = ArchanaBookingAudit(
        booking_id=booking_id,
        action="REFUND_REQUESTED",
        actor_id=UUID(current_user.sub),
        new_state={
            "refund_id": str(refund.id),
            "ref_id": ref_id,
            "amount": amount,
            "refund_method": refund_method,
            "refund_status": refund_status,
            "reason": reason
        }
    )
    db.add(audit)
    
    await db.commit()
    
    return api_response(message="Refund request submitted successfully.", data={"ref_id": ref_id})


@router.post("/refunds/{refund_id}/approve")
async def approve_refund(
    refund_id: UUID,
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
    current_user: TokenData = Depends(get_current_user),
):
    from app.models.archana import ArchanaRefund, EnterpriseArchanaBooking
    
    query = select(ArchanaRefund).filter(
        ArchanaRefund.id == refund_id,
        ArchanaRefund.temple_id == UUID(temple_id)
    )
    res = await db.execute(query)
    refund = res.scalar_one_or_none()
    if not refund:
        raise HTTPException(status_code=404, detail="Refund request not found")
        
    if refund.status != "PENDING":
        raise HTTPException(status_code=400, detail=f"Refund request is already {refund.status}")
        
    refund.status = "APPROVED"
    refund.approved_by = UUID(current_user.sub)
    
    # Update related booking and queue entry to CANCELLED
    from app.models.archana import ArchanaStatus, QueueStatus, RitualQueue, ArchanaBookingAudit
    b_query = select(EnterpriseArchanaBooking).filter(EnterpriseArchanaBooking.id == refund.booking_id)
    b_res = await db.execute(b_query)
    booking = b_res.scalar_one_or_none()
    if booking:
        booking.status = ArchanaStatus.CANCELLED
        
        queue_query = select(RitualQueue).filter(RitualQueue.booking_id == booking.id)
        queue_res = await db.execute(queue_query)
        queue_entry = queue_res.scalar_one_or_none()
        if queue_entry:
            queue_entry.status = QueueStatus.CANCELLED
            
        # Log refund approval audit
        audit_approve = ArchanaBookingAudit(
            booking_id=booking.id,
            action="REFUND_APPROVED",
            actor_id=UUID(current_user.sub),
            new_state={
                "refund_id": str(refund.id),
                "ref_id": refund.ref_id,
                "amount": refund.amount,
                "status": "APPROVED"
            }
        )
        db.add(audit_approve)
        
        # Log cancel audit
        audit_cancel = ArchanaBookingAudit(
            booking_id=booking.id,
            action="CANCELLED",
            actor_id=UUID(current_user.sub),
            new_state={"status": "CANCELLED", "context": f"Refund approval {refund.ref_id}"}
        )
        db.add(audit_cancel)
        
    from app.models.accounting import FinancialLedgerEntry, LedgerEntryType
    ledger_entry = FinancialLedgerEntry(
        temple_id=UUID(temple_id),
        entry_type=LedgerEntryType.REFUND,
        ref_id=refund.ref_id,
        amount=-refund.amount,
        payment_mode=refund.refund_method,
        recorded_by=UUID(current_user.sub),
        description=f"Refund against booking {refund.booking_id}: {refund.reason}"
    )
    db.add(ledger_entry)
    
    await db.commit()
    return api_response(message="Refund approved successfully.")


@router.post("/refunds/{refund_id}/cancel")
async def cancel_refund(
    refund_id: UUID,
    db: AsyncSession = Depends(get_db),
    temple_id: str = Depends(get_current_temple_id),
    current_user: TokenData = Depends(get_current_user),
):
    from app.models.archana import ArchanaRefund
    
    query = select(ArchanaRefund).filter(
        ArchanaRefund.id == refund_id,
        ArchanaRefund.temple_id == UUID(temple_id)
    )
    res = await db.execute(query)
    refund = res.scalar_one_or_none()
    if not refund:
        raise HTTPException(status_code=404, detail="Refund request not found")
        
    if refund.status != "PENDING":
        raise HTTPException(status_code=400, detail=f"Refund request is already {refund.status}")
        
    refund.status = "CANCELLED"
    
    from app.models.archana import ArchanaBookingAudit
    audit = ArchanaBookingAudit(
        booking_id=refund.booking_id,
        action="REFUND_REJECTED",
        actor_id=UUID(current_user.sub),
        new_state={
            "refund_id": str(refund.id),
            "ref_id": refund.ref_id,
            "status": "REJECTED"
        }
    )
    db.add(audit)
    
    await db.commit()
    return api_response(message="Refund request cancelled/rejected successfully.")

