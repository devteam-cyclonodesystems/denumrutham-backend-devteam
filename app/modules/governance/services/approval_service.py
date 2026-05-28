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
    ) -> ApprovalRequest:
        """
        Create a new approval request inside a FULL atomic transaction.
        If anything fails the entire transaction rolls back.
        """
        async with db.begin():
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

        # ── Transaction committed — safe to read back ────────────────────
        await db.refresh(req)
        return req

    # ── Process (approve / reject) ──────────────────────────────────────
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
        async with db.begin():
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

        # ── Transaction committed ────────────────────────────────────────
        await db.refresh(req)
        return req
