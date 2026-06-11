import re
import unicodedata
from uuid import UUID, uuid4
from typing import List, Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException

from sqlalchemy import func
from app.models.domain import User, Temple, TempleProfile, TempleStatusAudit, TempleOwnershipHistory, Subscription, SubscriptionEvent, TempleClaimRequest, OperationalStateAudit, AuditLog
from app.schemas.domain import TempleCreateFull, TempleUpdateFull
from app.core.security import create_access_token
from app.services.temple_rbac import can_modify_temple, can_change_status, can_delete_temple
from app.services.operational_state_service import OperationalStateService
from app.modules.governance.models.operational_states import TempleOperationalState
from app.services.broadcast_service import BroadcastService
from app.services.temple_events import emit_event, TEMPLE_CREATED, TEMPLE_STATUS_CHANGED, build_event_payload

def slugify(text: str) -> str:
    """Generate a URL-safe slug from a temple name."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")


class SuperAdminService:
    @staticmethod
    async def get_all_temples(db: AsyncSession, include_inactive: bool) -> Tuple[List[dict], int]:
        query = select(Temple)
        if not include_inactive:
            query = query.filter(Temple.status == "APPROVED", Temple.is_active == True)

        result = await db.execute(query.order_by(Temple.name))
        temples = result.scalars().all()

        items = []
        for temple in temples:
            profile_result = await db.execute(
                select(TempleProfile).filter(TempleProfile.temple_id == temple.id)
            )
            profile = profile_result.scalars().first()

            items.append({
                "id": str(temple.id),
                "name": temple.name,
                "domain": temple.domain,
                "location": temple.location or (profile.location if profile else ""),
                "state": temple.state or (profile.state if profile else ""),
                "address_line_1": temple.address_line_1 or "",
                "address_line_2": temple.address_line_2 or "",
                "district": temple.district or (profile.district if profile else ""),
                "pincode": temple.pincode or "",
                "contact_number": temple.contact_number or (profile.contact_number if profile else ""),
                "alternate_contact": temple.alternate_contact or "",
                "email": temple.email or (profile.email if profile else ""),
                "description": temple.description or (profile.description if profile else ""),
                "image_url": profile.image_url if profile else "",
                "status": temple.status or "APPROVED",
                "version": temple.version or 1,
                "updated_at": temple.updated_at.isoformat() if temple.updated_at else None,
            })

        return items, len(items)

    @staticmethod
    async def select_temple(db: AsyncSession, temple_id: str, sub: str, username: str) -> str:
        try:
            tid = UUID(temple_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid temple_id format")

        result = await db.execute(select(Temple).filter(Temple.id == tid, Temple.is_active == True))
        temple = result.scalars().first()
        if not temple:
            raise HTTPException(status_code=404, detail="Temple not found")

        # Re-issue the token with temple_id and security_version
        new_token = create_access_token(
            subject=sub,
            temple_id=str(temple.id),
            role="SUPERADMIN",
            username=username or "",
            security_version=temple.security_version,
            temple_management_mode=temple.management_mode,
            subscription_plan=temple.subscription_plan,
        )
        return new_token

    @staticmethod
    async def reset_context(sub: str, username: str) -> str:
        new_token = create_access_token(
            subject=sub,
            temple_id=None,
            role="SUPERADMIN",
            username=username or "",
        )
        return new_token

    @staticmethod
    async def create_temple(db: AsyncSession, body: TempleCreateFull, current_user_sub: Optional[str]) -> dict:
        existing = await db.execute(select(Temple).filter(Temple.name.ilike(body.name.strip())))
        if existing.scalars().first():
            raise HTTPException(status_code=400, detail="A temple with this name already exists")

        domain_slug = slugify(body.name.strip())
        domain_check = await db.execute(select(Temple).filter(Temple.domain == domain_slug))
        if domain_check.scalars().first():
            import uuid as uuid_mod
            domain_slug = f"{domain_slug}-{str(uuid_mod.uuid4())[:6]}"

        created_by = None
        if current_user_sub:
            try:
                created_by = UUID(current_user_sub)
            except (ValueError, TypeError):
                pass

        temple = Temple(
            name=body.name.strip(),
            domain=domain_slug,
            location=body.location or "",
            state=body.state or "",
            address_line_1=body.address_line_1 or "",
            address_line_2=body.address_line_2 or "",
            district=body.district or "",
            pincode=body.pincode or "",
            contact_number=body.contact_number or "",
            alternate_contact=body.alternate_contact or "",
            email=body.email or "",
            description=body.description or "",
            status=body.status or "APPROVED",
            created_by=created_by,
            management_mode=body.management_mode or "SELF_MANAGED",
            directory_status=body.directory_status or "ACTIVE",
            subscription_plan=body.subscription_plan or "SELF_MANAGED_PRO",
        )
        db.add(temple)
        await db.flush()

        # Audit: log initial ownership history
        history = TempleOwnershipHistory(
            id=uuid4(),
            temple_id=temple.id,
            previous_management_mode=None,
            new_management_mode=temple.management_mode,
            previous_subscription_plan=None,
            new_subscription_plan=temple.subscription_plan,
            changed_by=created_by,
            reason="Initial temple registration",
        )
        db.add(history)

        # Audit: record initial status assignment
        initial_status = body.status or "APPROVED"
        audit = TempleStatusAudit(
            temple_id=temple.id,
            old_status="NEW",
            new_status=initial_status,
            changed_by=created_by,
            reason="Temple created via SuperAdmin"
        )
        db.add(audit)

        profile = TempleProfile(
            temple_id=temple.id,
            location=body.location or "",
            district=body.district or "",
            state=body.state or "",
            contact_number=body.contact_number or "",
            email=body.email or "",
            description=body.description or "",
        )
        db.add(profile)
        
        # Seed default roles & permissions (Mandatory Change 1)
        from app.services.staff_service import StaffService
        await StaffService.seed_default_temple_roles(db, temple.id)

        from app.modules.audit.services.audit_service import AuditService
        await AuditService.log_action(
            db=db,
            temple_id=temple.id,
            user_id=created_by,
            role="SUPERADMIN",
            module_name="Governance",
            action="TEMPLE_CREATED",
            action_type="CREATE",
            entity_id=str(temple.id),
            new_value={"name": temple.name, "domain": temple.domain, "status": initial_status},
            details=f"Temple '{temple.name}' created by Super Admin"
        )
        
        await db.commit()
        await db.refresh(temple)

        # Event hook — standardized payload
        emit_event(TEMPLE_CREATED, build_event_payload(
            entity="temple",
            entity_id=str(temple.id),
            event=TEMPLE_CREATED,
            triggered_by=str(created_by) if created_by else "SYSTEM",
            old=None,
            new={
                "name": temple.name,
                "domain": temple.domain,
                "status": initial_status,
            },
        ))

        return {
            "id": str(temple.id),
            "name": temple.name,
            "domain": temple.domain,
            "location": temple.location or "",
            "state": temple.state or "",
            "address_line_1": temple.address_line_1 or "",
            "address_line_2": temple.address_line_2 or "",
            "district": temple.district or "",
            "pincode": temple.pincode or "",
            "contact_number": temple.contact_number or "",
            "alternate_contact": temple.alternate_contact or "",
            "email": temple.email or "",
            "description": temple.description or "",
            "image_url": "",
            "status": temple.status or "APPROVED",
            "version": temple.version or 1,
            "updated_at": temple.updated_at.isoformat() if temple.updated_at else None,
        }

    @staticmethod
    async def update_temple(db: AsyncSession, temple_id: str, body: TempleUpdateFull, updated_by: str = None, user_role: str = None) -> dict:
        try:
            tid = UUID(temple_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid temple_id format")

        # RBAC enforcement
        updated_by_uuid = None
        if updated_by:
            try:
                updated_by_uuid = UUID(updated_by)
            except (ValueError, TypeError):
                pass
        if not await can_modify_temple(db, updated_by_uuid, user_role, tid):
            raise HTTPException(status_code=403, detail="Not authorized to modify this temple")

        # Phase 4: Row-level lock — prevents concurrent lost updates
        # This method is called within ApprovalExecutor's transaction (db.begin()),
        # so the lock is held until that outer transaction commits.
        result = await db.execute(
            select(Temple)
            .filter(Temple.id == tid, Temple.is_active == True)
            .with_for_update()
        )
        temple = result.scalars().first()
        if not temple:
            raise HTTPException(status_code=404, detail="Temple not found")

        if body.name is not None:
            dup = await db.execute(
                select(Temple).filter(Temple.name.ilike(body.name.strip()), Temple.id != tid)
            )
            if dup.scalars().first():
                raise HTTPException(status_code=400, detail="A temple with this name already exists")
            
            old_domain = temple.domain
            temple.name = body.name.strip()
            temple.domain = slugify(body.name.strip())
            
            if old_domain != temple.domain:
                from app.models.domain import TempleDomainHistory
                history = TempleDomainHistory(
                    temple_id=temple.id,
                    old_domain=old_domain,
                    new_domain=temple.domain
                )
                db.add(history)

        field_map = {
            "location": body.location, "state": body.state, "address_line_1": body.address_line_1,
            "address_line_2": body.address_line_2, "district": body.district, "pincode": body.pincode,
            "contact_number": body.contact_number, "alternate_contact": body.alternate_contact,
            "email": body.email, "description": body.description,
        }

        for field, value in field_map.items():
            if value is not None:
                setattr(temple, field, value)

        # Check for management mode or subscription plan updates to log to TempleOwnershipHistory
        mode_changed = body.management_mode is not None and body.management_mode != temple.management_mode
        plan_changed = body.subscription_plan is not None and body.subscription_plan != temple.subscription_plan
        status_changed = body.directory_status is not None and body.directory_status != temple.directory_status

        if mode_changed or plan_changed or status_changed:
            prev_mode = temple.management_mode
            prev_plan = temple.subscription_plan
            
            # Apply changes
            if body.management_mode is not None:
                temple.management_mode = body.management_mode
            if body.subscription_plan is not None:
                temple.subscription_plan = body.subscription_plan
            if body.directory_status is not None:
                temple.directory_status = body.directory_status
                
            # Log audit entry to TempleOwnershipHistory
            history = TempleOwnershipHistory(
                id=uuid4(),
                temple_id=temple.id,
                previous_management_mode=prev_mode,
                new_management_mode=temple.management_mode,
                previous_subscription_plan=prev_plan,
                new_subscription_plan=temple.subscription_plan,
                changed_by=updated_by_uuid,
                reason=f"Administrative updates: mode_changed={mode_changed}, plan_changed={plan_changed}, status_changed={status_changed}",
            )
            db.add(history)

        # Phase 3: Hybrid preparation — increment version on every update
        from app.models.domain import utcnow as _utcnow
        temple.version = (temple.version or 1) + 1
        temple.updated_at = _utcnow()

        if body.status is not None:
            if body.status not in ("APPROVED", "REJECTED", "PENDING"):
                raise HTTPException(status_code=400, detail="Status must be 'APPROVED', 'REJECTED', or 'PENDING'")
            
            # RBAC enforcement for status changes
            if not await can_change_status(db, updated_by_uuid, user_role, tid):
                raise HTTPException(status_code=403, detail="Not authorized to change temple status")
            
            # State machine enforcement
            VALID_TRANSITIONS = {
                "PENDING": ["APPROVED", "REJECTED"],
                "APPROVED": [],
                "REJECTED": []
            }
            current_status = temple.status or "PENDING"
            if body.status != current_status:
                if body.status not in VALID_TRANSITIONS.get(current_status, []):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid status transition: {current_status} \u2192 {body.status}"
                    )
                old_status = current_status
                temple.status = body.status
                
                # Audit trail — changed_by is now always populated
                audit = TempleStatusAudit(
                    temple_id=temple.id,
                    old_status=old_status,
                    new_status=body.status,
                    changed_by=updated_by_uuid,
                    reason="Status changed via SuperAdmin update"
                )
                db.add(audit)
                
                # Event hook — standardized payload
                emit_event(TEMPLE_STATUS_CHANGED, build_event_payload(
                    entity="temple",
                    entity_id=str(temple.id),
                    event=TEMPLE_STATUS_CHANGED,
                    triggered_by=str(updated_by_uuid) if updated_by_uuid else "SYSTEM",
                    old={"status": old_status},
                    new={"status": body.status},
                ))

        profile_result = await db.execute(select(TempleProfile).filter(TempleProfile.temple_id == tid))
        profile = profile_result.scalars().first()
        if profile:
            if body.location is not None: profile.location = body.location
            if body.state is not None: profile.state = body.state
            if body.district is not None: profile.district = body.district
            if body.contact_number is not None: profile.contact_number = body.contact_number
            if body.email is not None: profile.email = body.email
            if body.description is not None: profile.description = body.description

        from app.modules.audit.services.audit_service import AuditService
        await AuditService.log_action(
            db=db,
            temple_id=temple.id,
            user_id=updated_by_uuid,
            role=user_role or "SUPERADMIN",
            module_name="Governance",
            action="TEMPLE_UPDATED",
            action_type="UPDATE",
            entity_id=str(temple.id),
            new_value={"name": temple.name, "domain": temple.domain, "status": temple.status},
            details=f"Temple '{temple.name}' updated by Admin/SuperAdmin"
        )

        await db.flush()

        profile_result = await db.execute(select(TempleProfile).filter(TempleProfile.temple_id == tid))
        profile = profile_result.scalars().first()

        return {
            "id": str(temple.id), "name": temple.name, "domain": temple.domain,
            "location": temple.location or "", "state": temple.state or "",
            "address_line_1": temple.address_line_1 or "", "address_line_2": temple.address_line_2 or "",
            "district": temple.district or "", "pincode": temple.pincode or "",
            "contact_number": temple.contact_number or "", "alternate_contact": temple.alternate_contact or "",
            "email": temple.email or "", "description": temple.description or "",
            "image_url": profile.image_url if profile else "", "status": temple.status or "APPROVED",
            "version": temple.version,
            "updated_at": temple.updated_at.isoformat() if temple.updated_at else None,
        }

        # Phase 5: Differentiated Deactivation
        # Graceful administrative disable using the State Engine
        await OperationalStateService.transition_to(
            db=db,
            temple_id=tid,
            new_state=TempleOperationalState.DEACTIVATED,
            changed_by=deleted_by_uuid,
            reason="Graceful administrative deactivation"
        )

        return {"detail": "Temple has been gracefully deactivated.", "id": str(tid)}

    @staticmethod
    async def suspend_temple(db: AsyncSession, temple_id: str, suspended_by: str = None, reason: str = "Emergency administrative lock") -> dict:
        """
        Emergency administrative lock. Sets state to 'SUSPENDED'.
        Phase 5 Hardening: Immediate access termination and sync freeze.
        """
        try:
            tid = UUID(temple_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid temple_id format")

        suspended_by_uuid = None
        if suspended_by:
            try: suspended_by_uuid = UUID(suspended_by)
            except: pass

        # Phase 9: Safeguards - Prevent self-suspension (if applicable)
        # In this system, SuperAdmins are global, but we check if they are currently tied to this temple context.
        # (Implementation detail: usually handled by UI, but backend should enforce boundaries)

        await OperationalStateService.transition_to(
            db=db,
            temple_id=tid,
            new_state=TempleOperationalState.SUSPENDED,
            changed_by=suspended_by_uuid,
            reason=reason
        )

        from app.modules.audit.services.audit_service import AuditService
        await AuditService.log_action(
            db=db,
            temple_id=tid,
            user_id=suspended_by_uuid,
            role="SUPERADMIN",
            module_name="Governance",
            action="TEMPLE_SUSPENDED",
            action_type="UPDATE",
            entity_id=str(tid),
            details=f"Temple suspended: {reason}"
        )

        return {"detail": "Temple has been placed under emergency suspension.", "id": str(tid)}

    @staticmethod
    async def reactivate_temple(db: AsyncSession, temple_id: str, activated_by: str = None, reason: str = "Administrative reactivation") -> dict:
        """
        Phase 7: Safe Reactivation Pipeline.
        1. Validate sync consistency (implicitly handled by version increment in transition)
        2. Transition state back to ACTIVE
        3. Force re-login to ensure fresh security context
        """
        try:
            tid = UUID(temple_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid temple_id format")

        activated_by_uuid = None
        if activated_by:
            try: activated_by_uuid = UUID(activated_by)
            except: pass

        # 1. State transition (handles audit and is_active flag)
        await OperationalStateService.transition_to(
            db=db,
            temple_id=tid,
            new_state=TempleOperationalState.ACTIVE,
            changed_by=activated_by_uuid,
            reason=reason
        )

        from app.modules.audit.services.audit_service import AuditService
        await AuditService.log_action(
            db=db,
            temple_id=tid,
            user_id=activated_by_uuid,
            role="SUPERADMIN",
            module_name="Governance",
            action="TEMPLE_REACTIVATED",
            action_type="UPDATE",
            entity_id=str(tid),
            details=f"Temple reactivated: {reason}"
        )
        
        # 2. Pipeline requirement: invalidate stale sessions upon reactivation
        # This ensures all users start with a clean security context.
        await SuperAdminService.force_logout_all_users(db, temple_id, triggered_by=activated_by)

        return {"detail": "Temple reactivation pipeline completed successfully.", "id": str(tid)}

    @staticmethod
    async def force_logout_all_users(db: AsyncSession, temple_id: str, triggered_by: str = None) -> dict:
        """
        Phase 2: Enterprise Security Hardening.
        Invalidates all sessions by incrementing security_version AND updating last_security_event_at.
        """
        try:
            tid = UUID(temple_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid temple_id format")

        triggered_by_uuid = None
        if triggered_by:
            try: triggered_by_uuid = UUID(triggered_by)
            except: pass

        from app.models.domain import utcnow

        async with db.begin_nested():
            result = await db.execute(select(Temple).filter(Temple.id == tid).with_for_update())
            temple = result.scalars().first()
            if not temple:
                raise HTTPException(status_code=404, detail="Temple not found")

            # Increment version for stateless invalidation
            temple.security_version += 1
            # Set timestamp for iat-based invalidation
            temple.last_security_event_at = utcnow()
            
            # Record security event in audit logs
            from app.models.domain import SecurityAuditEvent
            event = SecurityAuditEvent(
                temple_id=temple.id,
                user_id=triggered_by_uuid,
                event_type="FORCE_LOGOUT",
                severity="INFO",
                details={"new_version": temple.security_version, "timestamp": temple.last_security_event_at.isoformat()}
            )
            db.add(event)

            from app.modules.audit.services.audit_service import AuditService
            await AuditService.log_action(
                db=db,
                temple_id=temple.id,
                user_id=triggered_by_uuid,
                role="SUPERADMIN",
                module_name="Governance",
                action="FORCE_LOGOUT_ALL_USERS",
                action_type="UPDATE",
                entity_id=str(temple.id),
                details=f"Forced logout for all users of temple {temple.name}"
            )

        await db.commit()

        # Trigger real-time disconnect
        await BroadcastService.force_logout_tenant(tid, reason="Global security reset triggered by administrator.")

        return {"detail": "Force logout triggered. All sessions invalidated.", "security_version": temple.security_version}

    @staticmethod
    async def get_dashboard_stats(db: AsyncSession) -> dict:
        """Global stats for SuperAdmin dashboard."""
        temple_count_res = await db.execute(select(func.count(Temple.id)).filter(Temple.is_active == True))
        total_temples = temple_count_res.scalar() or 0

        staff_stats_res = await db.execute(
            select(User.status, func.count(User.id))
            .filter(User.role == "STAFF", User.is_active == True)
            .group_by(User.status)
        )
        staff_stats = {row[0]: row[1] for row in staff_stats_res.all()}
        
        return {
            "total_temples": total_temples,
            "total_staff": sum(staff_stats.values()),
            "active_staff": staff_stats.get("ACTIVE", 0),
            "suspended_staff": staff_stats.get("SUSPENDED", 0),
            "pending_approval_staff": staff_stats.get("PENDING_APPROVAL", 0)
        }

    @staticmethod
    async def get_governance_timeline(
        db: AsyncSession,
        temple_id: UUID,
        page: int = 1,
        page_size: int = 50,
        event_type: Optional[str] = None
    ) -> Tuple[List[dict], int]:
        """
        Aggregates chronological governance timeline events for a temple.
        Revisions implemented:
          1. Separates OWNERSHIP category.
          2. Adds source_table and source_id reference metadata.
          3. Implements INFO, WARNING, CRITICAL severity levels.
          4. Supports paginated chunks to avoid unbounded returns.
        """
        # 1. Verify Temple existence
        result = await db.execute(select(Temple).filter(Temple.id == temple_id))
        temple = result.scalars().first()
        if not temple:
            raise HTTPException(status_code=404, detail="Temple not found")

        events = []

        # 2. Fetch TempleOwnershipHistory
        ownership_stmt = select(TempleOwnershipHistory).filter(TempleOwnershipHistory.temple_id == temple_id)
        ownership_res = await db.execute(ownership_stmt)
        for row in ownership_res.scalars().all():
            events.append({
                "id": str(row.id),
                "event_type": "OWNERSHIP",
                "timestamp": row.changed_at.isoformat() if row.changed_at else None,
                "title": "Management Mode / Plan Changed",
                "description": f"Mode: {row.previous_management_mode or 'None'} → {row.new_management_mode}. Plan: {row.previous_subscription_plan or 'None'} → {row.new_subscription_plan}.",
                "severity": "INFO",
                "changed_by": str(row.changed_by) if row.changed_by else None,
                "reason": row.reason,
                "source_table": "temple_ownership_history",
                "source_id": str(row.id),
                "metadata": {
                    "previous_management_mode": row.previous_management_mode,
                    "new_management_mode": row.new_management_mode,
                    "previous_subscription_plan": row.previous_subscription_plan,
                    "new_subscription_plan": row.new_subscription_plan
                }
            })

        # 3. Fetch Subscription & Events
        sub_stmt = select(Subscription).filter(Subscription.temple_id == temple_id)
        sub_res = await db.execute(sub_stmt)
        sub = sub_res.scalars().first()
        if sub:
            sub_events_stmt = select(SubscriptionEvent).filter(SubscriptionEvent.subscription_id == sub.id)
            sub_events_res = await db.execute(sub_events_stmt)
            for row in sub_events_res.scalars().all():
                status_transition = f" ({row.previous_status} → {row.new_status})" if row.previous_status or row.new_status else ""
                
                # Determine Severity
                severity = "INFO"
                if row.new_status in ("CANCELLED", "EXPIRED"):
                    severity = "CRITICAL"
                elif row.new_status == "PAST_DUE" or "warning" in (row.event_name or "").lower():
                    severity = "WARNING"
                
                events.append({
                    "id": str(row.id),
                    "event_type": "BILLING",
                    "timestamp": row.received_at.isoformat() if row.received_at else None,
                    "title": f"Billing: {row.event_name}",
                    "description": f"Subscription status updated{status_transition}.",
                    "severity": severity,
                    "changed_by": "SYSTEM / Webhook",
                    "reason": None,
                    "source_table": "subscription_events",
                    "source_id": str(row.id),
                    "metadata": {
                        "event_name": row.event_name,
                        "previous_status": row.previous_status,
                        "new_status": row.new_status,
                        "payload_snapshot": row.payload_snapshot
                    }
                })

        # 4. Fetch Claim Requests & Reviews
        claim_stmt = select(TempleClaimRequest).filter(TempleClaimRequest.temple_id == temple_id)
        claim_res = await db.execute(claim_stmt)
        for row in claim_res.scalars().all():
            # Submission Event
            events.append({
                "id": f"{row.id}-submitted",
                "event_type": "CLAIMS",
                "timestamp": row.created_at.isoformat() if row.created_at else None,
                "title": "Temple Claim Requested",
                "description": f"Claim requested for target mode {row.target_management_mode} and plan {row.target_subscription_plan}.",
                "severity": "INFO",
                "changed_by": str(row.claimant_id),
                "reason": row.claimant_notes,
                "source_table": "temple_claim_requests",
                "source_id": str(row.id),
                "metadata": {
                    "target_management_mode": row.target_management_mode,
                    "target_subscription_plan": row.target_subscription_plan,
                    "claimant_notes": row.claimant_notes
                }
            })
            
            # Review Event (if status APPROVED/REJECTED)
            if row.status in ("APPROVED", "REJECTED"):
                severity = "INFO" if row.status == "APPROVED" else "WARNING"
                desc = (
                    f"Claim approved by administrator." if row.status == "APPROVED"
                    else f"Claim rejected. Reason: {row.rejection_reason or 'No reason provided'}."
                )
                events.append({
                    "id": f"{row.id}-reviewed",
                    "event_type": "CLAIMS",
                    "timestamp": row.reviewed_at.isoformat() if row.reviewed_at else (row.updated_at.isoformat() if row.updated_at else None),
                    "title": f"Temple Claim {row.status.capitalize()}",
                    "description": desc,
                    "severity": severity,
                    "changed_by": str(row.reviewed_by) if row.reviewed_by else None,
                    "reason": row.rejection_reason,
                    "source_table": "temple_claim_requests",
                    "source_id": str(row.id),
                    "metadata": {
                        "status": row.status,
                        "rejection_reason": row.rejection_reason,
                        "target_management_mode": row.target_management_mode,
                        "target_subscription_plan": row.target_subscription_plan
                    }
                })

        # 5. Fetch Website Review cycles from AuditLog
        website_audit_stmt = select(AuditLog).filter(
            AuditLog.temple_id == temple_id,
            AuditLog.module_name == "digital_experience",
            AuditLog.action.in_(["SUBMIT_WEBSITE_REVIEW", "APPROVE_WEBSITE_REVIEW", "REJECT_WEBSITE_REVIEW"])
        )
        website_audit_res = await db.execute(website_audit_stmt)
        for row in website_audit_res.scalars().all():
            title = "Website Draft Submitted"
            severity = "INFO"
            if row.action == "APPROVE_WEBSITE_REVIEW":
                title = "Website Draft Approved"
            elif row.action == "REJECT_WEBSITE_REVIEW":
                title = "Website Draft Rejected"
                severity = "WARNING"
                
            events.append({
                "id": str(row.id),
                "event_type": "WEBSITE",
                "timestamp": row.created_at.isoformat() if row.created_at else None,
                "title": title,
                "description": row.details or f"Website action {row.action} executed.",
                "severity": severity,
                "changed_by": str(row.user_id) if row.user_id else None,
                "reason": row.details,
                "source_table": "audit_logs",
                "source_id": str(row.id),
                "metadata": {
                    "action": row.action,
                    "role": row.role
                }
            })

        # 6. Fetch Operational State Audits
        state_stmt = select(OperationalStateAudit).filter(OperationalStateAudit.temple_id == temple_id)
        state_res = await db.execute(state_stmt)
        for row in state_res.scalars().all():
            old_val = row.old_state.value if row.old_state else "None"
            new_val = row.new_state.value if row.new_state else "None"
            
            # Severity
            severity = "INFO"
            if new_val == "SUSPENDED":
                severity = "CRITICAL"
            elif new_val == "DEACTIVATED":
                severity = "CRITICAL"
            elif new_val == "READ_ONLY":
                severity = "WARNING"
                
            events.append({
                "id": str(row.id),
                "event_type": "GOVERNANCE",
                "timestamp": row.created_at.isoformat() if row.created_at else None,
                "title": "Operational State Transitioned",
                "description": f"Operational state changed from {old_val} to {new_val}.",
                "severity": severity,
                "changed_by": str(row.changed_by) if row.changed_by else None,
                "reason": row.reason,
                "source_table": "operational_state_audits",
                "source_id": str(row.id),
                "metadata": {
                    "old_state": old_val,
                    "new_state": new_val
                }
            })

        # 7. Fetch direct Administrative actions from AuditLog
        gov_audit_stmt = select(AuditLog).filter(
            AuditLog.temple_id == temple_id,
            AuditLog.module_name == "Governance",
            AuditLog.action.in_(["TEMPLE_SUSPENDED", "TEMPLE_REACTIVATED", "FORCE_LOGOUT_ALL_USERS", "TEMPLE_DEACTIVATED", "TEMPLE_UPDATED"])
        )
        gov_audit_res = await db.execute(gov_audit_stmt)
        for row in gov_audit_res.scalars().all():
            title = f"Governance: {row.action}"
            severity = "INFO"
            if row.action == "TEMPLE_SUSPENDED":
                title = "Temple Suspended"
                severity = "CRITICAL"
            elif row.action == "TEMPLE_DEACTIVATED":
                title = "Temple Deactivated"
                severity = "CRITICAL"
            elif row.action == "FORCE_LOGOUT_ALL_USERS":
                title = "Sessions Terminated"
                severity = "CRITICAL"
            elif row.action == "TEMPLE_REACTIVATED":
                title = "Temple Reactivated"
                severity = "INFO"
            elif row.action == "TEMPLE_UPDATED":
                title = "Temple Details Updated"
                severity = "INFO"
                
            events.append({
                "id": str(row.id),
                "event_type": "GOVERNANCE",
                "timestamp": row.created_at.isoformat() if row.created_at else None,
                "title": title,
                "description": row.details or f"Governance action {row.action} executed.",
                "severity": severity,
                "changed_by": str(row.user_id) if row.user_id else None,
                "reason": row.details,
                "source_table": "audit_logs",
                "source_id": str(row.id),
                "metadata": {
                    "action": row.action,
                    "role": row.role
                }
            })

        # 8. Resolve Actor UUIDs
        user_ids = set()
        for e in events:
            if e["changed_by"]:
                try:
                    user_ids.add(UUID(e["changed_by"]))
                except ValueError:
                    pass

        user_map = {}
        if user_ids:
            user_stmt = select(User).filter(User.id.in_(user_ids))
            user_res = await db.execute(user_stmt)
            for u in user_res.scalars().all():
                user_map[str(u.id)] = u.name or u.email or u.user_id

        # Replace changed_by UUID with resolved name
        for e in events:
            cb = e["changed_by"]
            if cb in user_map:
                e["changed_by_name"] = user_map[cb]
            else:
                e["changed_by_name"] = cb or "SYSTEM"

        # 8.5 Filter by event type if requested
        if event_type and event_type.upper() != "ALL":
            events = [e for e in events if e["event_type"] == event_type.upper()]

        # 9. Sort descending by timestamp
        events.sort(key=lambda x: x["timestamp"] or "", reverse=True)

        # 10. Paginate
        total = len(events)
        start = (page - 1) * page_size
        end = start + page_size
        paginated_events = events[start:end]

        return paginated_events, total
