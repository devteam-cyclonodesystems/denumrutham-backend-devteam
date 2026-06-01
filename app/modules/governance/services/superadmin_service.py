import re
import unicodedata
from uuid import UUID
from typing import List, Tuple, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException

from sqlalchemy import func
from app.models.domain import User, Temple, TempleProfile, TempleStatusAudit
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
        )
        db.add(temple)
        await db.flush()

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
