"""
Approval Service — full-transaction orchestration.

Every public method owns a SINGLE atomic transaction:
  1. begin()
  2. all service mutations (flush only)
  3. audit log  (flush only)
  4. notifications (flush only)
  5. commit   ← single commit for the entire batch
  6. on ANY error → automatic rollback via context manager

No inner service is allowed to call commit().
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from uuid import UUID
from typing import Optional
from datetime import datetime, timezone
import json
import hashlib

from app.models.domain import ApprovalRequest
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService, NotificationEvent
from app.services.approval_executor import ApprovalExecutor


def _utcnow():
    return datetime.now(timezone.utc)


class ApprovalService:
    # ── Create approval request ─────────────────────────────────────────
    @staticmethod
    async def request_approval(
        db: AsyncSession,
        temple_id: UUID,
        module: str,
        entity_id: Optional[str],
        requested_by: UUID,
        request_payload: dict,
        auto_commit: bool = True,
    ) -> ApprovalRequest:
        """
        Create a new approval request inside a FULL atomic transaction.
        If anything fails the entire transaction rolls back.
        """
        async def _run():
            # ── Guard: block duplicate pending approvals on same entity ──
            dup_stmt = select(ApprovalRequest).filter(
                ApprovalRequest.temple_id == temple_id,
                ApprovalRequest.entity_id == entity_id,
                ApprovalRequest.module == module,
                ApprovalRequest.status == "pending",
            )
            dup_result = await db.execute(dup_stmt)
            if dup_result.scalar_one_or_none():
                raise ValueError(
                    "An active pending approval already exists for this entity."
                )

            # ── 1. Insert approval request ───────────────────────────────
            req = ApprovalRequest(
                temple_id=temple_id,
                module=module,
                entity_id=entity_id,
                requested_by=requested_by,
                request_payload=request_payload,
                status="pending",
            )
            db.add(req)
            await db.flush()  # materialises req.id

            # ── 2. Content hash for tamper detection ─────────────────────
            payload_str = json.dumps(request_payload, sort_keys=True, default=str)
            content_hash = hashlib.sha256(payload_str.encode()).hexdigest()

            # ── 3. Audit log (flush only) ────────────────────────────────
            await AuditService.log_action(
                db=db,
                temple_id=temple_id,
                user_id=requested_by,
                role=None,
                module_name=module,
                action="request_approval",
                action_type="create",
                entity_id=entity_id,
                new_value=request_payload,
                approval_id=req.id,
                content_hash=content_hash,
            )

            # ── 4. Multi-role notifications (flush only) ─────────────────
            await NotificationService.dispatch_event(
                db=db,
                temple_id=temple_id,
                event_type=NotificationEvent.APPROVAL_REQUEST_CREATED,
                title=f"New Approval Required — {module}",
                message=(
                    f"A change request for {module} (entity {entity_id}) "
                    f"has been submitted and is awaiting review."
                ),
                requester_id=requested_by,
            )
            return req

        if auto_commit:
            async with db.begin():
                req = await _run()
            await db.refresh(req)
        else:
            req = await _run()
        return req

    @staticmethod
    async def process_approval(
        db: AsyncSession,
        request_id: UUID,
        reviewer_id: UUID,
        status: str,  # "approved" | "rejected"
        remarks: Optional[str],
    ) -> ApprovalRequest:
        """
        Approve or reject a request inside a FULL atomic transaction.
        On approval the safe executor applies the change within the same
        transaction — if the executor fails, everything rolls back.
        """
        # Ensure a session-level transaction has begun
        if not db.in_transaction():
            await db.begin()

        # We start a savepoint/nested transaction so that if anything fails,
        # we can rollback the business execution, but keep the session transaction
        # active to write the failure metadata.
        nested_tx = await db.begin_nested()
        try:
            # ── Lock the row to prevent concurrent approvals ─────────────
            stmt = (
                select(ApprovalRequest)
                .filter(ApprovalRequest.id == request_id)
                .with_for_update()
            )
            result = await db.execute(stmt)
            req = result.scalar_one_or_none()

            if not req:
                raise ValueError("Approval request not found")
            if req.status != "pending":
                raise ValueError(f"Request is already {req.status}")

            # ── 1. Update approval record ────────────────────────────────
            req.status = status
            req.reviewed_by = reviewer_id
            req.reviewed_at = _utcnow()
            req.remarks = remarks

            # ── 2. If approved → safe execution via domain services ──────
            if status == "approved":
                await ApprovalExecutor.execute_module_action(
                    db, req.module, req.entity_id, req.request_payload,
                    executed_by=str(reviewer_id),
                )
            elif status == "rejected":
                await ApprovalExecutor.execute_module_rejection(
                    db, req.module, req.entity_id, req.request_payload,
                    rejected_by=str(reviewer_id),
                    remarks=remarks,
                )

            # ── 3. Audit log (flush only) ────────────────────────────────
            await AuditService.log_action(
                db=db,
                temple_id=req.temple_id,
                user_id=reviewer_id,
                role=None,
                module_name=req.module,
                action=f"approval_{status}",
                action_type="update",
                entity_id=req.entity_id,
                new_value={"status": status, "remarks": remarks},
                approval_id=req.id,
            )

            # ── 4. Multi-role notifications (flush only) ─────────────────
            event = (
                NotificationEvent.APPROVAL_APPROVED
                if status == "approved"
                else NotificationEvent.APPROVAL_REJECTED
            )
            await NotificationService.dispatch_event(
                db=db,
                temple_id=req.temple_id,
                event_type=event,
                title=f"Approval {status.upper()} — {req.module}",
                message=(
                    f"Request for {req.module} (entity {req.entity_id}) "
                    f"has been {status}."
                    + (f" Remarks: {remarks}" if remarks else "")
                ),
                requester_id=req.requested_by,
            )

            # Commit the savepoint and the session-level transaction
            await nested_tx.commit()
            await db.commit()
            await db.refresh(req)
            return req

        except Exception as e:
            # Rollback the savepoint (this undoes any executor changes and log_action calls)
            await nested_tx.rollback()

            if status == "approved":
                # Start a new savepoint/nested transaction to write the failure state,
                # so if writing the failure state fails, we don't mess up the session transaction.
                failure_tx = await db.begin_nested()
                try:
                    stmt = (
                        select(ApprovalRequest)
                        .filter(ApprovalRequest.id == request_id)
                        .with_for_update()
                    )
                    result = await db.execute(stmt)
                    req_fail = result.scalar_one_or_none()
                    if req_fail:
                        req_fail.status = "execution_failed"
                        req_fail.reviewed_by = reviewer_id
                        req_fail.reviewed_at = _utcnow()
                        req_fail.remarks = f"Execution failed: {str(e)}"
                        
                        # Hall Booking Refund Specific Logic (Phase 20)
                        if req_fail.module == "hall_bookings_refund":
                            from app.modules.bookings.models.booking_models import RefundHistory, HallBooking
                            
                            # 1. Update RefundHistory
                            refund_stmt = select(RefundHistory).filter(
                                RefundHistory.approval_request_id == request_id
                            ).with_for_update()
                            refund_res = await db.execute(refund_stmt)
                            refund_hist = refund_res.scalar_one_or_none()
                            if refund_hist:
                                refund_hist.status = "FAILED"
                                refund_hist.failure_reason = str(e)
                                refund_hist.failure_code = "EXECUTION_EXCEPTION"
                                refund_hist.failed_at = _utcnow()
                                refund_hist.processed_at = _utcnow()
                                refund_hist.approved_by = reviewer_id
                                refund_hist.review_remarks = remarks
                                
                            # 2. Reset booking lock
                            if req_fail.entity_id:
                                booking_stmt = select(HallBooking).filter(
                                    HallBooking.id == UUID(req_fail.entity_id)
                                ).with_for_update()
                                booking_res = await db.execute(booking_stmt)
                                booking = booking_res.scalar_one_or_none()
                                if booking:
                                    booking.refund_status = "NONE"
                                    booking.has_pending_refund = False
                            
                            # 3. Post Audit Event
                            await AuditService.log_action(
                                db=db,
                                temple_id=req_fail.temple_id,
                                user_id=reviewer_id,
                                role=None,
                                module_name=req_fail.module,
                                action="refund_execution_failed",
                                action_type="update",
                                entity_id=req_fail.entity_id,
                                new_value={"status": "execution_failed", "error": str(e)},
                                approval_id=req_fail.id,
                            )
                    await failure_tx.commit()
                except Exception as fe:
                    await failure_tx.rollback()
                    # If this failed, we want the whole transaction to rollback
                    await db.rollback()
                    raise fe

                # Commit the failure changes to the database
                await db.commit()
            else:
                # Rejection failure or similar: rollback session transaction
                await db.rollback()
            raise e
