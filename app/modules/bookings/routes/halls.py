"""Hall & Hall Booking API endpoints with strict tenant enforcement."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel
from app.api.deps import get_db, get_current_user, get_current_temple_id
from app.schemas.domain import TokenData
from app.schemas.hall import HallCreate, HallUpdate, HallResponse, HallBookingCreate, HallBookingResponse, HallBookingUpdate, HallRefundRequest
from app.services.hall_service import HallService

router = APIRouter()


# --- Halls ---
@router.post("/halls", response_model=HallResponse, tags=["halls"])
async def create_hall(
    hall_in: HallCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await HallService.create_hall(db=db, hall_in=hall_in, temple_id=temple_id)


@router.get("/halls", response_model=List[HallResponse], tags=["halls"])
async def list_halls(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await HallService.get_halls(db=db, temple_id=temple_id)


@router.put("/halls/{hall_id}", response_model=HallResponse, tags=["halls"])
async def update_hall(
    hall_id: str,
    hall_in: HallUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    result = await HallService.update_hall(db=db, hall_id=hall_id, update_in=hall_in, temple_id=temple_id)
    if not result:
        raise HTTPException(status_code=404, detail="Venue not found")
    return result


@router.delete("/halls/{hall_id}", tags=["halls"])
async def delete_hall(
    hall_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    result = await HallService.delete_hall(db=db, hall_id=hall_id, temple_id=temple_id)
    if not result:
        raise HTTPException(status_code=404, detail="Venue not found")
    return {"message": "Venue removed successfully"}


# --- Hall Bookings ---
@router.post("/hall-bookings", response_model=HallBookingResponse, tags=["hall-bookings"])
async def create_hall_booking(
    booking_in: HallBookingCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await HallService.create_hall_booking(
        db=db, booking_in=booking_in, temple_id=temple_id,
        created_by=current_user.username or "Admin",
        user_id=current_user.sub,
    )


@router.get("/hall-bookings", response_model=List[HallBookingResponse], tags=["hall-bookings"])
async def list_hall_bookings(
    skip: int = 0,
    limit: int = 200,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await HallService.get_hall_bookings(db=db, temple_id=temple_id, skip=skip, limit=limit)


@router.put("/hall-bookings/{booking_id}", response_model=HallBookingResponse, tags=["hall-bookings"])
async def update_hall_booking(
    booking_id: str,
    update_in: HallBookingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    result = await HallService.update_hall_booking(
        db=db, booking_id=booking_id, update_in=update_in, temple_id=temple_id, user_id=current_user.sub
    )
    if not result:
        raise HTTPException(status_code=404, detail="Booking not found")
    return result


@router.patch("/hall-bookings/{booking_id}/cancel", response_model=HallBookingResponse, tags=["hall-bookings"])
async def cancel_hall_booking(
    booking_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    result = await HallService.cancel_hall_booking(db=db, booking_id=booking_id, temple_id=temple_id, user_id=current_user.sub)
    if not result:
        raise HTTPException(status_code=404, detail="Booking not found")
    return result


@router.patch("/hall-bookings/{booking_id}/approve", response_model=HallBookingResponse, tags=["hall-bookings"])
async def approve_hall_booking(
    booking_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    result = await HallService.approve_hall_booking(db=db, booking_id=booking_id, temple_id=temple_id, user_id=current_user.sub)
    if not result:
        raise HTTPException(status_code=404, detail="Booking not found")
    return result


# --- Refunds ---
class RefundProcessInput(BaseModel):
    status: str  # approved or rejected
    remarks: Optional[str] = None


@router.post("/hall-bookings/refunds", tags=["hall-refunds"])
async def process_hall_refund(
    refund_in: HallRefundRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    from decimal import Decimal
    from uuid import UUID
    from app.modules.bookings.models.booking_models import HallBooking, RefundHistory
    from app.services.approval_service import ApprovalService
    from app.services.booking_audit_service import BookingAuditService
    
    tid = UUID(str(temple_id))
    bid = UUID(str(refund_in.booking_id))
    
    async with db.begin():
        # Get booking with lock
        stmt = select(HallBooking).filter(
            HallBooking.id == bid,
            HallBooking.temple_id == tid
        ).with_for_update()
        booking_res = await db.execute(stmt)
        booking = booking_res.scalar_one_or_none()
        
        if not booking:
            raise HTTPException(status_code=404, detail="Booking not found")
            
        # Check active pending refund lock (Phase 1)
        if booking.refund_status == "PENDING_APPROVAL":
            raise HTTPException(status_code=400, detail="A refund request is already pending approval for this booking.")
            
        # Fully refunded bookings and cancelled bookings check
        if booking.status in ("cancelled", "refunded") or booking.payment_status == "REFUNDED" or (booking.amount_paid or 0.0) <= 0:
            raise HTTPException(
                status_code=400,
                detail="This booking has been cancelled or fully refunded and cannot receive further refund requests."
            )

        # Decimal precision check and Maximum Refundable Amount validation (Phase 18)
        from app.models.hall_booking import PaymentLedger, PaymentTransaction
        from sqlalchemy import func

        # Get ledger
        ledger_stmt = select(PaymentLedger).filter(PaymentLedger.booking_id == bid)
        ledger_res = await db.execute(ledger_stmt)
        ledger = ledger_res.scalar_one_or_none()

        # Get total successful payments
        total_payments = Decimal(str(booking.amount_paid or 0.0))
        if ledger:
            pay_stmt = select(func.sum(PaymentTransaction.amount)).filter(
                PaymentTransaction.ledger_id == ledger.id,
                PaymentTransaction.transaction_type == "PAYMENT",
                PaymentTransaction.status == "SUCCESS"
            )
            pay_res = await db.execute(pay_stmt)
            tx_payments = Decimal(str(pay_res.scalar() or 0.0))
            ledger_paid = Decimal(str(ledger.paid_amount or 0.0))
            total_payments = max(tx_payments, ledger_paid, total_payments)

        # Get total completed or pending refunds
        refund_stmt = select(func.sum(RefundHistory.refund_amount)).filter(
            RefundHistory.booking_id == bid,
            RefundHistory.status.in_(["PENDING", "COMPLETED"])
        )
        refund_res = await db.execute(refund_stmt)
        total_refunds = Decimal(str(refund_res.scalar() or 0.0))

        max_refundable = max(Decimal("0.0"), total_payments - total_refunds)
        amount_dec = Decimal(str(refund_in.amount))

        if amount_dec <= 0:
            raise HTTPException(status_code=400, detail="Refund amount must be greater than zero")

        if amount_dec > max_refundable:
            raise HTTPException(
                status_code=400,
                detail=f"Refund amount of ₹{amount_dec} exceeds maximum refundable amount of ₹{max_refundable} (Paid: ₹{total_payments}, Refunded/Pending: ₹{total_refunds})."
            )
            
        # Determine refund type (FULL or PARTIAL) (Phase 2)
        refund_type = "FULL" if refund_in.refund_status == "Full" else "PARTIAL"
        
        # Create approval request (auto_commit=False, so it runs inside this transaction)
        req_payload = {
            "amount": float(amount_dec),
            "refund_method": refund_in.refund_method,
            "refund_status": refund_in.refund_status,  # "Full" or "Partial"
            "reason": refund_in.reason,
        }
        
        approval_req = await ApprovalService.request_approval(
            db=db,
            temple_id=tid,
            module="hall_bookings_refund",
            entity_id=str(bid),
            requested_by=UUID(str(current_user.sub)),
            request_payload=req_payload,
            auto_commit=False
        )
        
        # Convert float columns to Decimal for NUMERIC columns in database (avoids asyncpg conversion error)
        amount_paid_before_dec = Decimal(str(booking.amount_paid or 0.0))
        balance_before_dec = Decimal(str(booking.amount or 0.0)) - amount_paid_before_dec

        # Create RefundHistory record
        refund_hist = RefundHistory(
            temple_id=tid,
            booking_id=bid,
            booking_reference=booking.ref_number or "",
            customer_name=booking.customer_name or "",
            refund_amount=amount_dec,
            refund_method=refund_in.refund_method,
            refund_reason=refund_in.reason,
            refund_type=refund_type,
            status="PENDING",
            amount_paid_before=amount_paid_before_dec,
            balance_before=balance_before_dec,
            payment_status_before=booking.payment_status,
            requested_by=UUID(str(current_user.sub)),
            approval_request_id=approval_req.id,
        )
        db.add(refund_hist)
        await db.flush()
        
        # Update HallBooking refund state
        booking.refund_status = "PENDING_APPROVAL"
        booking.has_pending_refund = True
        booking.last_refund_history_id = refund_hist.id
        
        # Log to audit trail (Phase 15)
        await BookingAuditService.log_action(
            db=db,
            temple_id=str(tid),
            booking_id=str(bid),
            action="REFUND_SUBMITTED",
            performed_by=current_user.sub,
            new_values={"amount": float(amount_dec), "method": refund_in.refund_method, "type": refund_type}
        )
        
    return {
        "message": "Refund request submitted for approval",
        "approval_request_id": str(approval_req.id),
        "refund_history_id": str(refund_hist.id),
    }


@router.get("/hall-bookings/refund-requests", tags=["hall-refunds"])
async def list_pending_refund_requests(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    from app.models.domain import User
    from app.modules.governance.models.governance_models import ApprovalRequest
    from app.modules.bookings.models.booking_models import HallBooking
    from sqlalchemy import cast
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID
    
    tid = UUID(str(temple_id))
    stmt = (
        select(ApprovalRequest, User.name, HallBooking.ref_number, HallBooking.customer_name)
        .outerjoin(User, ApprovalRequest.requested_by == User.id)
        .outerjoin(HallBooking, cast(ApprovalRequest.entity_id, PG_UUID) == HallBooking.id)
        .filter(
            ApprovalRequest.temple_id == tid,
            ApprovalRequest.module == "hall_bookings_refund",
            ApprovalRequest.status == "pending"
        )
    )
    result = await db.execute(stmt)
    rows = result.all()
    
    reqs = []
    for r, username, ref, cust in rows:
        reqs.append({
            "id": str(r.id),
            "temple_id": str(r.temple_id),
            "module": r.module,
            "entity_id": r.entity_id,
            "status": r.status,
            "requested_by": str(r.requested_by),
            "requested_by_name": username or "Unknown",
            "booking_reference": ref or "",
            "customer_name": cust or "",
            "request_payload": r.request_payload,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return reqs


@router.post("/hall-bookings/refund-requests/{request_id}/process", tags=["hall-refunds"])
async def process_refund_request(
    request_id: str,
    payload: RefundProcessInput,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    from app.modules.governance.models.governance_models import ApprovalRequest
    from app.services.approval_service import ApprovalService
    
    if payload.status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid status")
        
    req_uuid = UUID(request_id)
    stmt = select(ApprovalRequest).filter(ApprovalRequest.id == req_uuid)
    res = await db.execute(stmt)
    req = res.scalar_one_or_none()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if str(req.temple_id) != str(temple_id):
        raise HTTPException(status_code=403, detail="Forbidden")
        
    try:
        updated_req = await ApprovalService.process_approval(
            db=db,
            request_id=req_uuid,
            reviewer_id=UUID(current_user.sub),
            status=payload.status,
            remarks=payload.remarks
        )
        return {
            "message": f"Refund request {payload.status} successfully",
            "approval_request_id": str(updated_req.id),
            "status": updated_req.status
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/hall-bookings/refund-history", tags=["hall-refunds"])
async def get_refund_history(
    status: Optional[str] = None,
    refund_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    from app.models.domain import User
    from app.modules.bookings.models.booking_models import RefundHistory
    from sqlalchemy.orm import aliased
    
    tid = UUID(str(temple_id))
    
    ReqUser = aliased(User)
    AppUser = aliased(User)
    RejUser = aliased(User)
    
    stmt = (
        select(
            RefundHistory,
            ReqUser.name.label("requested_by_name"),
            AppUser.name.label("approved_by_name"),
            RejUser.name.label("rejected_by_name")
        )
        .outerjoin(ReqUser, RefundHistory.requested_by == ReqUser.id)
        .outerjoin(AppUser, RefundHistory.approved_by == AppUser.id)
        .outerjoin(RejUser, RefundHistory.rejected_by == RejUser.id)
        .filter(RefundHistory.temple_id == tid)
        .order_by(RefundHistory.requested_at.desc())
    )
    
    if status:
        stmt = stmt.filter(RefundHistory.status == status)
    if refund_type:
        stmt = stmt.filter(RefundHistory.refund_type == refund_type)
        
    res = await db.execute(stmt)
    rows = res.all()
    
    history_list = []
    for r, req_name, app_name, rej_name in rows:
        history_list.append({
            "id": str(r.id),
            "booking_id": str(r.booking_id),
            "booking_reference": r.booking_reference,
            "customer_name": r.customer_name,
            "refund_amount": float(r.refund_amount),
            "refund_method": r.refund_method,
            "refund_reason": r.refund_reason,
            "refund_type": r.refund_type,
            "status": r.status,
            "amount_paid_before": float(r.amount_paid_before) if r.amount_paid_before is not None else None,
            "amount_paid_after": float(r.amount_paid_after) if r.amount_paid_after is not None else None,
            "balance_before": float(r.balance_before) if r.balance_before is not None else None,
            "balance_after": float(r.balance_after) if r.balance_after is not None else None,
            "payment_status_before": r.payment_status_before,
            "payment_status_after": r.payment_status_after,
            "requested_by": str(r.requested_by),
            "requested_by_name": req_name or "Unknown",
            "approved_by": str(r.approved_by) if r.approved_by else None,
            "approved_by_name": app_name,
            "rejected_by": str(r.rejected_by) if r.rejected_by else None,
            "rejected_by_name": rej_name,
            "review_remarks": r.review_remarks,
            "decision_reason": r.decision_reason,
            "failure_reason": r.failure_reason,
            "failure_code": r.failure_code,
            "failed_at": r.failed_at.isoformat() if r.failed_at else None,
            "requested_at": r.requested_at.isoformat() if r.requested_at else None,
            "processed_at": r.processed_at.isoformat() if r.processed_at else None,
        })
    return history_list


@router.get("/hall-bookings/refund-history/summary", tags=["hall-refunds"])
async def get_refund_summary(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    from app.modules.bookings.models.booking_models import RefundHistory
    from sqlalchemy import func
    
    tid = UUID(str(temple_id))
    
    amt_stmt = select(func.sum(RefundHistory.refund_amount)).filter(
        RefundHistory.temple_id == tid,
        RefundHistory.status == "COMPLETED"
    )
    amt_res = await db.execute(amt_stmt)
    total_amount = amt_res.scalar() or 0.0
    
    counts_stmt = select(
        RefundHistory.status,
        func.count(RefundHistory.id)
    ).filter(RefundHistory.temple_id == tid).group_by(RefundHistory.status)
    counts_res = await db.execute(counts_stmt)
    counts = dict(counts_res.all())
    
    return {
        "total_refund_amount": float(total_amount),
        "total_requests": sum(counts.values()),
        "pending_count": counts.get("PENDING", 0),
        "completed_count": counts.get("COMPLETED", 0),
        "failed_count": counts.get("FAILED", 0),
        "rejected_count": counts.get("REJECTED", 0)
    }


@router.get("/hall-bookings/refund-history/export", tags=["hall-refunds"])
async def export_refund_history(
    format: str = "csv",
    status: Optional[str] = None,
    refund_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    from app.models.domain import User
    from app.modules.bookings.models.booking_models import RefundHistory
    from sqlalchemy.orm import aliased
    import csv
    import io
    from fastapi.responses import StreamingResponse
    from datetime import datetime
    
    tid = UUID(str(temple_id))
    
    ReqUser = aliased(User)
    AppUser = aliased(User)
    
    stmt = (
        select(
            RefundHistory,
            ReqUser.name.label("requested_by_name"),
            AppUser.name.label("approved_by_name")
        )
        .outerjoin(ReqUser, RefundHistory.requested_by == ReqUser.id)
        .outerjoin(AppUser, RefundHistory.approved_by == AppUser.id)
        .filter(RefundHistory.temple_id == tid)
        .order_by(RefundHistory.requested_at.desc())
    )
    
    if status:
        stmt = stmt.filter(RefundHistory.status == status)
    if refund_type:
        stmt = stmt.filter(RefundHistory.refund_type == refund_type)
        
    res = await db.execute(stmt)
    rows = res.all()
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    writer.writerow([
        "ID", "Booking Reference", "Customer Name", "Refund Amount", 
        "Refund Method", "Refund Type", "Status", 
        "Requested By", "Requested At", "Approved By", "Processed At", "Reason"
    ])
    
    for r, req_name, app_name in rows:
        writer.writerow([
            str(r.id),
            r.booking_reference,
            r.customer_name,
            f"{r.refund_amount:.2f}",
            r.refund_method,
            r.refund_type,
            r.status,
            req_name or str(r.requested_by),
            r.requested_at.isoformat() if r.requested_at else "",
            app_name or "" if r.approved_by else "",
            r.processed_at.isoformat() if r.processed_at else "",
            r.refund_reason or ""
        ])
        
    output.seek(0)
    
    filename = f"refund_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode("utf-8")),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/hall-bookings/{booking_id}/refund-history", tags=["hall-refunds"])
async def get_booking_refund_history(
    booking_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    from app.models.domain import User
    from app.modules.bookings.models.booking_models import HallBooking, RefundHistory
    from sqlalchemy.orm import aliased
    import logging
    
    logger = logging.getLogger("tms.api.halls")
    
    bid = UUID(booking_id)
    tid = UUID(str(temple_id))
    
    # Enforce multi-tenant boundaries
    booking_stmt = select(HallBooking).filter(HallBooking.id == bid)
    booking_res = await db.execute(booking_stmt)
    booking = booking_res.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if str(booking.temple_id) != str(temple_id):
        logger.warning(f"TENANT_VALIDATION_FAILURE: User {current_user.sub} tried to access booking {booking_id} of temple {booking.temple_id}")
        raise HTTPException(status_code=403, detail="Forbidden")
        
    ReqUser = aliased(User)
    AppUser = aliased(User)
    RejUser = aliased(User)
    
    stmt = (
        select(
            RefundHistory,
            ReqUser.name.label("requested_by_name"),
            AppUser.name.label("approved_by_name"),
            RejUser.name.label("rejected_by_name")
        )
        .outerjoin(ReqUser, RefundHistory.requested_by == ReqUser.id)
        .outerjoin(AppUser, RefundHistory.approved_by == AppUser.id)
        .outerjoin(RejUser, RefundHistory.rejected_by == RejUser.id)
        .filter(RefundHistory.booking_id == bid)
        .order_by(RefundHistory.requested_at.desc())
    )
    
    res = await db.execute(stmt)
    rows = res.all()
    
    history_list = []
    for r, req_name, app_name, rej_name in rows:
        history_list.append({
            "id": str(r.id),
            "booking_id": str(r.booking_id),
            "booking_reference": r.booking_reference,
            "customer_name": r.customer_name,
            "refund_amount": float(r.refund_amount),
            "refund_method": r.refund_method,
            "refund_reason": r.refund_reason,
            "refund_type": r.refund_type,
            "status": r.status,
            "amount_paid_before": float(r.amount_paid_before) if r.amount_paid_before is not None else None,
            "amount_paid_after": float(r.amount_paid_after) if r.amount_paid_after is not None else None,
            "balance_before": float(r.balance_before) if r.balance_before is not None else None,
            "balance_after": float(r.balance_after) if r.balance_after is not None else None,
            "payment_status_before": r.payment_status_before,
            "payment_status_after": r.payment_status_after,
            "requested_by": str(r.requested_by),
            "requested_by_name": req_name or "Unknown",
            "approved_by": str(r.approved_by) if r.approved_by else None,
            "approved_by_name": app_name,
            "rejected_by": str(r.rejected_by) if r.rejected_by else None,
            "rejected_by_name": rej_name,
            "review_remarks": r.review_remarks,
            "decision_reason": r.decision_reason,
            "failure_reason": r.failure_reason,
            "failure_code": r.failure_code,
            "failed_at": r.failed_at.isoformat() if r.failed_at else None,
            "requested_at": r.requested_at.isoformat() if r.requested_at else None,
            "processed_at": r.processed_at.isoformat() if r.processed_at else None,
        })
    return history_list


@router.get("/hall-bookings/{booking_id}/transactions", tags=["hall-bookings"])
async def get_booking_transactions(
    booking_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await HallService.get_booking_transactions(db=db, booking_id=booking_id, temple_id=temple_id)


@router.get("/hall-bookings/{booking_id}/audit-trail", tags=["hall-bookings"])
async def get_booking_audit_trail(
    booking_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
):
    return await HallService.get_booking_audit_trail(db=db, booking_id=booking_id, temple_id=temple_id)

