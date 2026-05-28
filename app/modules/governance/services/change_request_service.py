"""
Change Request Service — Field-level change approval system.

All updates by STAFF go into ChangeRequest.
TEMPLE_MANAGER approves → apply change to live table, rejects → discard.
Self-approval is prevented.
"""
import logging
from uuid import UUID
from typing import Optional
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, desc
from fastapi import HTTPException

from app.models.domain import (
    ChangeRequest, Temple, Employee, Hall, InventoryItem, User,
)
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService, NotificationEvent

logger = logging.getLogger(__name__)


# ── Entity model mapping for applying changes ─────────────────────────
ENTITY_MODEL_MAP = {
    "temple": Temple,
    "employee": Employee,
    "hall": Hall,
    "inventory_item": InventoryItem,
}


class ChangeRequestService:
    """Field-level change request CRUD with approval workflow."""

    # ── Create Change Request ─────────────────────────────────────────
    @staticmethod
    async def create_change_request(
        db: AsyncSession,
        temple_id: UUID,
        entity_type: str,
        entity_id: str,
        field_name: str,
        old_value: Optional[str],
        new_value: str,
        requested_by: UUID,
    ) -> ChangeRequest:
        """Create a field-level change request. Used by STAFF for all updates."""
        
        # Validate entity_type
        if entity_type not in ENTITY_MODEL_MAP:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid entity_type: {entity_type}. Allowed: {list(ENTITY_MODEL_MAP.keys())}"
            )

        # Verify entity exists
        model_cls = ENTITY_MODEL_MAP[entity_type]
        try:
            eid = UUID(entity_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid entity_id format")

        entity_result = await db.execute(
            select(model_cls).filter(model_cls.id == eid)
        )
        entity = entity_result.scalars().first()
        if not entity:
            raise HTTPException(status_code=404, detail=f"{entity_type} not found")

        # Verify field exists on the entity
        if not hasattr(entity, field_name):
            raise HTTPException(
                status_code=400,
                detail=f"Field '{field_name}' does not exist on {entity_type}"
            )

        # Get current value if old_value not provided
        if old_value is None:
            current_val = getattr(entity, field_name, None)
            old_value = str(current_val) if current_val is not None else None

        # Check for duplicate pending request
        dup_result = await db.execute(
            select(ChangeRequest).filter(
                ChangeRequest.temple_id == temple_id,
                ChangeRequest.entity_type == entity_type,
                ChangeRequest.entity_id == entity_id,
                ChangeRequest.field_name == field_name,
                ChangeRequest.status == "PENDING",
            )
        )
        if dup_result.scalars().first():
            raise HTTPException(
                status_code=409,
                detail=f"A pending change request already exists for {entity_type}.{field_name}"
            )

        # Create the change request
        cr = ChangeRequest(
            entity_type=entity_type,
            entity_id=entity_id,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            requested_by=requested_by,
            status="PENDING",
            temple_id=temple_id,
            target_version=getattr(entity, 'version', 1),
        )
        db.add(cr)
        await db.flush()

        # Audit log
        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=requested_by,
            role="STAFF",
            module_name="change_request",
            action="create_change_request",
            action_type="create",
            entity_id=entity_id,
            new_value={
                "entity_type": entity_type,
                "field_name": field_name,
                "new_value": new_value,
            },
        )

        # Notify temple managers
        await NotificationService.dispatch_event(
            db=db,
            temple_id=temple_id,
            event_type=NotificationEvent.APPROVAL_REQUEST_CREATED,
            title=f"Change Request — {entity_type}.{field_name}",
            message=f"Staff requested to change {field_name} on {entity_type} ({entity_id})",
            requester_id=requested_by,
        )

        await db.commit()
        await db.refresh(cr)

        logger.info(
            "Change request created: %s.%s on %s by %s",
            entity_type, field_name, entity_id, requested_by,
        )
        return cr

    # ── Create Bulk Change Requests ───────────────────────────────────
    @staticmethod
    async def create_bulk_change_requests(
        db: AsyncSession,
        temple_id: UUID,
        entity_type: str,
        entity_id: str,
        changes: list[dict],
        requested_by: UUID,
    ) -> list[ChangeRequest]:
        """Create multiple change requests for different fields on the same entity."""
        results = []
        for change in changes:
            cr = await ChangeRequestService.create_change_request(
                db=db,
                temple_id=temple_id,
                entity_type=entity_type,
                entity_id=entity_id,
                field_name=change["field_name"],
                old_value=change.get("old_value"),
                new_value=change["new_value"],
                requested_by=requested_by,
            )
            results.append(cr)
        return results

    # ── Approve Change ────────────────────────────────────────────────
    @staticmethod
    async def approve_change(
        db: AsyncSession,
        change_request_id: UUID,
        approved_by: UUID,
        remarks: Optional[str] = None,
    ) -> ChangeRequest:
        """
        Approve a change request and apply the change to the live table.
        Self-approval is prevented.
        """
        # Lock the row
        stmt = (
            select(ChangeRequest)
            .filter(ChangeRequest.id == change_request_id)
            .with_for_update()
        )
        result = await db.execute(stmt)
        cr = result.scalars().first()

        if not cr:
            raise HTTPException(status_code=404, detail="Change request not found")

        if cr.status != "PENDING":
            raise HTTPException(status_code=400, detail=f"Change request is already {cr.status}")

        # ── CRITICAL: Prevent self-approval ──────────────────────────
        if cr.requested_by == approved_by:
            raise HTTPException(
                status_code=403,
                detail="Self-approval is not permitted. A different manager must approve this request."
            )

        # ── Apply the change to the live table ────────────────────────
        entity_type = cr.entity_type
        if entity_type not in ENTITY_MODEL_MAP:
            raise HTTPException(status_code=400, detail=f"Cannot apply change for entity type: {entity_type}")

        model_cls = ENTITY_MODEL_MAP[entity_type]
        entity_result = await db.execute(
            select(model_cls).filter(model_cls.id == UUID(cr.entity_id))
        )
        entity = entity_result.scalars().first()
        if not entity:
            raise HTTPException(status_code=404, detail=f"{entity_type} entity no longer exists")

        # Apply the field change
        old_actual = str(getattr(entity, cr.field_name, None))
        setattr(entity, cr.field_name, cr.new_value)
        
        # Increment version
        if hasattr(entity, 'version'):
            entity.version += 1

        # Update the change request
        cr.status = "APPROVED"
        cr.approved_by = approved_by
        cr.remarks = remarks
        cr.updated_at = datetime.now(timezone.utc)

        # Audit log
        await AuditService.log_action(
            db=db,
            temple_id=cr.temple_id,
            user_id=approved_by,
            role="TEMPLE_MANAGER",
            module_name="change_request",
            action="approve_change",
            action_type="update",
            entity_id=cr.entity_id,
            old_value={"field": cr.field_name, "value": old_actual},
            new_value={"field": cr.field_name, "value": cr.new_value},
        )

        # Notify requester
        await NotificationService.dispatch_event(
            db=db,
            temple_id=cr.temple_id,
            event_type=NotificationEvent.APPROVAL_APPROVED,
            title=f"Change APPROVED — {cr.entity_type}.{cr.field_name}",
            message=f"Your change request for {cr.field_name} has been approved.",
            requester_id=cr.requested_by,
        )

        await db.commit()
        await db.refresh(cr)

        logger.info("Change request %s approved by %s", change_request_id, approved_by)
        return cr

    # ── Reject Change ─────────────────────────────────────────────────
    @staticmethod
    async def reject_change(
        db: AsyncSession,
        change_request_id: UUID,
        rejected_by: UUID,
        remarks: Optional[str] = None,
    ) -> ChangeRequest:
        """Reject a change request — no changes applied to live tables."""
        stmt = (
            select(ChangeRequest)
            .filter(ChangeRequest.id == change_request_id)
            .with_for_update()
        )
        result = await db.execute(stmt)
        cr = result.scalars().first()

        if not cr:
            raise HTTPException(status_code=404, detail="Change request not found")

        if cr.status != "PENDING":
            raise HTTPException(status_code=400, detail=f"Change request is already {cr.status}")

        # Prevent self-rejection by the requester (optional but consistent)
        if cr.requested_by == rejected_by:
            raise HTTPException(
                status_code=403,
                detail="Cannot reject your own request. Use a cancellation flow instead."
            )

        cr.status = "REJECTED"
        cr.approved_by = rejected_by  # 'approved_by' stores the reviewer
        cr.remarks = remarks
        cr.updated_at = datetime.now(timezone.utc)

        # Audit log
        await AuditService.log_action(
            db=db,
            temple_id=cr.temple_id,
            user_id=rejected_by,
            role="TEMPLE_MANAGER",
            module_name="change_request",
            action="reject_change",
            action_type="update",
            entity_id=cr.entity_id,
            new_value={"status": "REJECTED", "remarks": remarks},
        )

        # Notify requester
        await NotificationService.dispatch_event(
            db=db,
            temple_id=cr.temple_id,
            event_type=NotificationEvent.APPROVAL_REJECTED,
            title=f"Change REJECTED — {cr.entity_type}.{cr.field_name}",
            message=f"Your change request for {cr.field_name} has been rejected."
                    + (f" Reason: {remarks}" if remarks else ""),
            requester_id=cr.requested_by,
        )

        await db.commit()
        await db.refresh(cr)

        logger.info("Change request %s rejected by %s", change_request_id, rejected_by)
        return cr

    # ── List Pending Approvals (Manager Dashboard) ────────────────────
    @staticmethod
    async def get_pending_approvals(
        db: AsyncSession,
        temple_id: UUID,
        entity_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ChangeRequest], int]:
        """Get all pending change requests for a temple."""
        base = select(ChangeRequest).filter(
            ChangeRequest.temple_id == temple_id,
            ChangeRequest.status == "PENDING",
        )
        if entity_type:
            base = base.filter(ChangeRequest.entity_type == entity_type)

        # Count
        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_stmt)).scalar() or 0

        # Fetch
        data_stmt = base.order_by(desc(ChangeRequest.created_at)).offset(offset).limit(limit)
        result = await db.execute(data_stmt)
        items = result.scalars().all()

        return items, total

    # ── Get All Change Requests (with filters) ────────────────────────
    @staticmethod
    async def get_change_requests(
        db: AsyncSession,
        temple_id: UUID,
        status: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ChangeRequest], int]:
        """Get change requests with optional filtering."""
        base = select(ChangeRequest).filter(ChangeRequest.temple_id == temple_id)

        if status:
            base = base.filter(ChangeRequest.status == status)
        if entity_type:
            base = base.filter(ChangeRequest.entity_type == entity_type)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await db.execute(count_stmt)).scalar() or 0

        data_stmt = base.order_by(desc(ChangeRequest.created_at)).offset(offset).limit(limit)
        result = await db.execute(data_stmt)
        items = result.scalars().all()

        return items, total
