"""
Onboarding Service — Temple registration + approval workflow.

Staging table approach:
  1. register_temple() → writes to temple_requests + user_requests
  2. approve_temple() → atomically promotes to production temples + users
  3. reject_temple() → marks staging records as REJECTED

All critical actions are audit-logged. Notifications are dispatched
for registration, approval, and rejection events (Fix #10).
"""
import logging
import uuid as uuid_mod
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, Date
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert
from fastapi import HTTPException

from app.modules.auth.models.auth_models import User, UserTemple
from app.modules.temple_management.models.temple_models import Temple, TempleProfile, TempleStatusAudit
from app.modules.governance.models.governance_models import TempleDomainHistory
from app.modules.billing.models.billing_models import TempleCodeSequence
from app.models.onboarding import TempleRequest, UserRequest
from app.models.system_rbac import SystemRole
from app.core.security import get_password_hash
from app.services.audit_service import AuditService
from app.services.temple_events import emit_event, build_event_payload, TEMPLE_CREATED, TEMPLE_STATUS_CHANGED

logger = logging.getLogger(__name__)


class OnboardingService:
    """Handles the full temple onboarding lifecycle."""

    @staticmethod
    async def register_temple(
        db: AsyncSession,
        temple_name: str,
        domain: str,
        manager_name: str,
        manager_email: Optional[str],
        manager_phone: Optional[str],
        password: str,
        contact: str = "",
        alt_contact: str = "",
        address: str = "",
        state: str = "",
        district: str = "",
        pincode: str = "",
        temple_email: str = "",
    ) -> dict:
        """
        Create staging records for temple registration.

        Does NOT create production records — manager cannot login
        until Super Admin approves.
        """
        # Safeguard #3: Input Normalization
        if manager_email:
            manager_email = manager_email.strip().lower()
        if domain:
            domain = domain.strip().lower()

        # Safeguard #4: Strict Validation (Detailed Reporting)
        missing_fields = []
        if not temple_name:
            missing_fields.append("temple_name")
        if not domain:
            missing_fields.append("domain")
        if not contact:
            missing_fields.append("temple_contact")
        if not address:
            missing_fields.append("address")
        if not state:
            missing_fields.append("state")
        if not pincode:
            missing_fields.append("pincode")
        if not manager_email:
            missing_fields.append("email (manager_email)")

        if missing_fields:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required fields: {', '.join(missing_fields)}"
            )

        # ── Normalize domain ──────────────────────────────────────────
        domain = domain.strip().lower()

        try:
            # ── Domain uniqueness: check production temples (Fix #2 / Fix PART 1.5) ──────
            existing_temple = await db.execute(
                select(Temple).filter(Temple.domain == domain)
            )
            if existing_temple.scalars().first():
                raise HTTPException(
                    status_code=400,
                    detail=f"Domain '{domain}' is already registered to an existing temple"
                )

            # ── Domain validation regex (Phase 2) ─────────────────────────
            import re
            if not re.match(r"^[a-z0-9-]{3,50}$", domain):
                raise HTTPException(
                    status_code=400,
                    detail="Domain must be 3-50 characters, lowercase alphanumeric and hyphens only"
                )

            # ── Domain uniqueness: check pending/approved requests ────────
            existing_request = await db.execute(
                select(TempleRequest).filter(
                    TempleRequest.domain == domain,
                    TempleRequest.status.in_(["PENDING", "APPROVED"]),
                )
            )
            if existing_request.scalars().first():
                raise HTTPException(
                    status_code=400,
                    detail=f"Domain '{domain}' already has a pending or approved registration"
                )

            # ── Email/phone uniqueness: check production users ────────────
            login_id = manager_email or manager_phone
            if not login_id:
                raise HTTPException(
                    status_code=400,
                    detail="Manager email or phone number is required"
                )

            if manager_email:
                dup_email = await db.execute(
                    select(User).filter(User.email == manager_email, User.is_active == True)
                )
                if dup_email.scalars().first():
                    raise HTTPException(status_code=400, detail="Email already registered")

            if manager_phone:
                dup_phone = await db.execute(
                    select(User).filter(User.phone == manager_phone, User.is_active == True)
                )
                if dup_phone.scalars().first():
                    raise HTTPException(status_code=400, detail="Phone number already registered")

            # ── Email/phone uniqueness: check pending user_requests ───────
            if manager_email:
                dup_req_email = await db.execute(
                    select(UserRequest).filter(
                        UserRequest.email == manager_email,
                        UserRequest.status == "PENDING",
                    )
                )
                if dup_req_email.scalars().first():
                    raise HTTPException(
                        status_code=400,
                        detail="Email already has a pending registration"
                    )

            if manager_phone:
                dup_req_phone = await db.execute(
                    select(UserRequest).filter(
                        UserRequest.phone == manager_phone,
                        UserRequest.status == "PENDING",
                    )
                )
                if dup_req_phone.scalars().first():
                    raise HTTPException(
                        status_code=400,
                        detail="Phone number already has a pending registration"
                    )

            # ── Hash password ─────────────────────────────────────────────
            password_hash = get_password_hash(password)

            # ── Create staging records ────────────────────────────────────
            temple_request = TempleRequest(
                temple_name=temple_name.strip(),
                domain=domain,
                contact=contact,
                alt_contact=alt_contact,
                address=address,
                state=state,
                district=district,
                pincode=pincode,
                email=temple_email,
                status="PENDING", # Fix PART 1.4
            )
            db.add(temple_request)

            # Fix PART 1.1 / 1.2: Flush before FK usage
            await db.flush()

            user_request = UserRequest(
                name=manager_name,
                email=manager_email,
                phone=manager_phone,
                password_hash=password_hash,
                role="TEMPLE_ADMIN",
                temple_request_id=temple_request.id,
                status="PENDING", # Fix PART 1.4
            )
            db.add(user_request)
            await db.flush()

            # ── Audit log (Fix #7) ────────────────────────────────────────
            await AuditService.log_action(
                db=db,
                temple_id=None,  # System-level action, no temple context production yet
                user_id=None,
                role=None,
                module_name="onboarding",
                action="TEMPLE_REGISTRATION_REQUESTED",
                action_type="CREATE",
                entity_id=str(temple_request.id),
                new_value={
                    "temple_name": temple_name,
                    "domain": domain,
                    "manager_name": manager_name,
                    "manager_email": manager_email,
                    "manager_phone": manager_phone,
                },
                details=f"Temple '{temple_name}' registration requested by {manager_name}",
            )

            await db.commit()

            logger.info(
                "Temple registration requested: %s (domain=%s) by %s",
                temple_name, domain, manager_name,
            )

            return {
                "message": "Temple registration submitted. Awaiting Super Admin approval.",
                "request_id": str(temple_request.id),
                "temple_name": temple_name,
                "domain": domain,
                "status": "PENDING",
            }

        except IntegrityError as e:
            await db.rollback()
            logger.error(f"Registration failed (IntegrityError): {str(e)}") # Fix PART 1.6
            raise HTTPException(status_code=400, detail="Domain, email, or phone already exists")
        except HTTPException:
            await db.rollback()
            raise
        except Exception as e:
            await db.rollback()
            logger.error(f"Registration failed (Unexpected): {str(e)}") # Fix PART 1.6
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}") # Fix PART 1.1 (temp debug)

    # ── Check Domain Availability ─────────────────────────────────────
    @staticmethod
    async def is_domain_available(db: AsyncSession, domain: str) -> bool:
        """Check if a domain is available for registration."""
        domain = domain.strip().lower()

        # Check production temples
        existing_temple = await db.execute(
            select(Temple).filter(Temple.domain == domain)
        )
        if existing_temple.scalars().first():
            return False

        # Check pending/approved requests
        existing_request = await db.execute(
            select(TempleRequest).filter(
                TempleRequest.domain == domain,
                TempleRequest.status.in_(["PENDING", "APPROVED"]),
            )
        )
        if existing_request.scalars().first():
            return False

        return True

    # ── List Pending Requests ─────────────────────────────────────────
    @staticmethod
    async def list_pending_requests(db: AsyncSession) -> dict:
        """Return all PENDING temple requests with manager info."""
        logger.info("Fetching all PENDING temple registration requests")
        
        try:
            query = (
                select(TempleRequest, UserRequest)
                .outerjoin(UserRequest, UserRequest.temple_request_id == TempleRequest.id)
                .where(TempleRequest.status == "PENDING")
                .order_by(TempleRequest.created_at.desc())
            )
            result = await db.execute(query)
            rows = result.all()
            
            logger.info(f"Fetched {len(rows)} pending onboarding requests")

            items = []
            for req, user_req in rows:
                items.append({
                    "id": str(req.id),
                    "temple_name": req.temple_name,
                    "domain": req.domain,
                    "contact": req.contact or "",
                    "alt_contact": req.alt_contact or "",
                    "address": req.address or "",
                    "state": req.state or "",
                    "district": req.district or "",
                    "pincode": req.pincode or "",
                    "email": req.email or "",
                    "status": req.status,
                    "rejection_reason": req.rejection_reason,
                    "created_at": req.created_at,
                    "manager_name": user_req.name if user_req else None,
                    "manager_email": user_req.email if user_req else None,
                    "manager_phone": user_req.phone if user_req else None,
                })

            return {
                "requests": items,
                "count": len(items)
            }
        except Exception:
            logger.exception("Error occurred in list_pending_requests")
            raise


    # ── List All Requests (with status filter) ────────────────────────
    @staticmethod
    async def list_all_requests(
        db: AsyncSession, status_filter: Optional[str] = None
    ) -> dict:
        """Return temple requests with optional status filter."""
        logger.info(f"Fetching temple requests with filter: {status_filter}")
        
        try:
            query = (
                select(TempleRequest, UserRequest)
                .outerjoin(UserRequest, UserRequest.temple_request_id == TempleRequest.id)
                .order_by(TempleRequest.created_at.desc())
            )
            if status_filter:
                filter_val = status_filter.upper().strip()
                query = query.where(TempleRequest.status == filter_val)

            result = await db.execute(query)
            rows = result.all()
            
            logger.info(f"Fetched {len(rows)} onboarding requests")

            items = []
            for req, user_req in rows:
                items.append({
                    "id": str(req.id),
                    "temple_name": req.temple_name,
                    "domain": req.domain,
                    "contact": req.contact or "",
                    "alt_contact": req.alt_contact or "",
                    "address": req.address or "",
                    "state": req.state or "",
                    "district": req.district or "",
                    "pincode": req.pincode or "",
                    "email": req.email or "",
                    "status": req.status,
                    "rejection_reason": req.rejection_reason,
                    "created_at": req.created_at,
                    "manager_name": user_req.name if user_req else None,
                    "manager_email": user_req.email if user_req else None,
                    "manager_phone": user_req.phone if user_req else None,
                })

            return {
                "requests": items,
                "count": len(items)
            }
        except Exception:
            logger.exception("Error occurred in list_all_requests")
            raise


    # ── Get Single Request ────────────────────────────────────────────
    @staticmethod
    async def get_request(db: AsyncSession, request_id: UUID) -> dict:
        """Get a single temple request with manager details."""
        result = await db.execute(
            select(TempleRequest).filter(TempleRequest.id == request_id)
        )
        req = result.scalars().first()
        if not req:
            raise HTTPException(status_code=404, detail="Temple request not found")

        ur_result = await db.execute(
            select(UserRequest).filter(UserRequest.temple_request_id == req.id)
        )
        user_req = ur_result.scalars().first()

        return {
            "id": str(req.id),
            "temple_name": req.temple_name,
            "domain": req.domain,
            "contact": req.contact or "",
            "alt_contact": req.alt_contact or "",
            "address": req.address or "",
            "state": req.state or "",
            "district": req.district or "",
            "pincode": req.pincode or "",
            "email": req.email or "",
            "status": req.status,
            "rejection_reason": req.rejection_reason,
            "created_at": req.created_at,
            "manager_name": user_req.name if user_req else None,
            "manager_email": user_req.email if user_req else None,
            "manager_phone": user_req.phone if user_req else None,
        }

    # ── Safe temple_code Generation (Concurrency Fix #1) ──────────────
    @staticmethod
    async def _generate_temple_code_safely(db: AsyncSession) -> str:
        """
        Generates a unique temple_code (TMP-YYYYMMDD-XXX) in a race-free manner.
        Uses UPSERT + SELECT FOR UPDATE on temple_code_sequences.
        """
        today = datetime.now().date()
        date_str = today.strftime("%Y%m%d")

        # Ensure daily sequence row exists (Atomic UPSERT)
        from sqlalchemy.dialects.postgresql import insert
        stmt = insert(TempleCodeSequence).values(
            date=today, last_val=0
        ).on_conflict_do_nothing()
        await db.execute(stmt)

        # Lock and increment
        stmt = select(TempleCodeSequence).filter(
            TempleCodeSequence.date == today
        ).with_for_update()
        result = await db.execute(stmt)
        seq = result.scalar_one()

        while True:
            seq.last_val += 1
            code = f"TMP-{date_str}-{str(seq.last_val).zfill(3)}"
            # Verify code is not already in use by a production temple (Fix code collision)
            chk = await db.execute(select(Temple).filter(Temple.temple_code == code))
            if not chk.scalars().first():
                return code

    # ── Domain Resolution with History Fallback (Hardening #2) ────────
    @staticmethod
    async def resolve_domain(db: AsyncSession, domain: str) -> Optional[Temple]:
        """
        Lookup temple by domain. 
        Fallback: check TempleDomainHistory if not found in primary domain field.
        """
        domain = domain.strip().lower()
        # 1. Direct match
        stmt = select(Temple).filter(Temple.domain == domain, Temple.is_active == True)
        result = await db.execute(stmt)
        temple = result.scalars().first()
        if temple:
            return temple

        # 2. History fallback
        stmt = select(TempleDomainHistory).filter(TempleDomainHistory.old_domain == domain)
        history_result = await db.execute(stmt)
        history = history_result.scalars().first()
        if history:
            # Resolve to current temple
            stmt = select(Temple).filter(Temple.id == history.temple_id, Temple.is_active == True)
            result = await db.execute(stmt)
            return result.scalars().first()

        return None

    # ── Approve Temple ────────────────────────────────────────────────
    @staticmethod
    async def approve_temple(
        db: AsyncSession, request_id: UUID, approver_id: UUID
    ) -> dict:
        """
        Atomically promote staging records → production records.
        """
        # PHASE 2: CONTROLLER VALIDATION — fetch early to validate existence
        # Uses with_for_update() to prevent race conditions during promotion
        result = await db.execute(
            select(TempleRequest).filter(TempleRequest.id == request_id).with_for_update()
        )
        temple_req = result.scalars().first()
        
        if not temple_req:
            logger.error(f"Approval failed: Temple request {request_id} not found")
            raise HTTPException(status_code=404, detail="Temple request not found")

        if temple_req.status != "PENDING":
            raise HTTPException(
                status_code=400,
                detail=f"Request already {temple_req.status.lower()}"
            )

        # PHASE 5: COMMIT SAFETY — wrap entire promotion in a transaction block
        try:
            # Check if we are already in a transaction (fixed the 500 error cause)
            if not db.in_transaction():
                tx = await db.begin()
            else:
                tx = None

            # 2. Fetch user request
            ur_result = await db.execute(
                select(UserRequest).filter(
                    UserRequest.temple_request_id == request_id,
                    UserRequest.status == "PENDING",
                )
            )
            user_req = ur_result.scalars().first()
            if not user_req:
                raise HTTPException(
                    status_code=400,
                    detail="No pending user request found for this temple request"
                )

            # 3. Lookup TEMPLE_ADMIN system role
            role_result = await db.execute(
                select(SystemRole).filter(SystemRole.name == "TEMPLE_ADMIN")
            )
            temple_admin_role = role_result.scalars().first()

            # --- Phase 2: Generate temple_code (Concurrency-Safe #1) ---
            temple_code = await OnboardingService._generate_temple_code_safely(db)

            # Resolve canonical state_id and district_id from state_master and district_master
            state_id = None
            district_id = None
            
            from app.modules.temple_management.models.temple_models import StateMaster, DistrictMaster
            from sqlalchemy import func
            
            if temple_req.state:
                state_stmt = select(StateMaster).filter(func.lower(StateMaster.name) == func.lower(temple_req.state.strip()))
                state_res = await db.execute(state_stmt)
                state_obj = state_res.scalars().first()
                if state_obj:
                    state_id = state_obj.id
                    
            if temple_req.district:
                dist_name = temple_req.district.strip()
                if dist_name.lower() == "trivandrum":
                    dist_name = "Thiruvananthapuram"
                
                if state_id:
                    dist_stmt = select(DistrictMaster).filter(
                        func.lower(DistrictMaster.name) == func.lower(dist_name),
                        DistrictMaster.state_id == state_id
                    )
                else:
                    dist_stmt = select(DistrictMaster).filter(func.lower(DistrictMaster.name) == func.lower(dist_name))
                    
                dist_res = await db.execute(dist_stmt)
                dist_obj = dist_res.scalars().first()
                if dist_obj:
                    district_id = dist_obj.id

            # 4. Create production Temple
            # PHASE 3: UPDATE OPERATION VALIDATION
            temple = Temple(
                name=temple_req.temple_name,
                domain=temple_req.domain,
                temple_code=temple_code,
                contact_number=temple_req.contact or "",
                alternate_contact=temple_req.alt_contact or "",
                address_line_1=temple_req.address or "",
                state=temple_req.state or "",
                district=temple_req.district or "",
                state_id=state_id,
                district_id=district_id,
                pincode=temple_req.pincode or "",
                email=temple_req.email or "",
                status="APPROVED",
                is_active=True,
                approved_at=datetime.now(timezone.utc), # Explicit validation field
                approved_by=approver_id,                # Explicit validation field
            )
            db.add(temple)
            await db.flush()
            
            # Insert audit record
            audit = TempleStatusAudit(
                temple_id=temple.id,
                old_status="PENDING",
                new_status="APPROVED",
                changed_by=approver_id,
                reason="Approved via onboarding flow"
            )
            db.add(audit)

            try:
                await db.flush()
            except IntegrityError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Domain '{temple_req.domain}' or code '{temple_code}' conflict during approval"
                )

            # 5. Create TempleProfile
            profile = TempleProfile(
                temple_id=temple.id,
                location=temple_req.address or "",
                district=temple_req.district or "",
                state=temple_req.state or "",
                contact_number=temple_req.contact or "",
                email=temple_req.email or "",
            )
            db.add(profile)

            # 6. Create production User — determine login_id
            login_id = user_req.email or user_req.phone
            user = User(
                user_id=login_id,
                name=user_req.name,
                email=user_req.email,
                phone=user_req.phone,
                password_hash=user_req.password_hash,
                role="TEMPLE_MANAGER",
                system_role_id=temple_admin_role.id if temple_admin_role else None,
                status="ACTIVE",
                temple_id=temple.id,
            )
            db.add(user)

            try:
                await db.flush()
            except IntegrityError:
                raise HTTPException(
                    status_code=400,
                    detail="User email or phone already registered (conflict during approval)"
                )

            # 7. Set temple.created_by
            temple.created_by = user.id

            # 8. Create UserTemple mapping
            mapping = UserTemple(
                user_id=user.id,
                temple_id=temple.id,
                role="TEMPLE_MANAGER",
            )
            db.add(mapping)

            # Seed default roles & permissions (Mandatory Change 1)
            from app.services.staff_service import StaffService
            await StaffService.seed_default_temple_roles(db, temple.id)
            
            # Map manager user to the default Manager role
            from app.models.rbac import Role, UserRole
            role_res = await db.execute(
                select(Role).filter(Role.temple_id == temple.id, Role.name == "Manager")
            )
            manager_role = role_res.scalars().first()
            if manager_role:
                ur = UserRole(
                    user_id=user.id,
                    role_id=manager_role.id,
                    temple_id=temple.id
                )
                db.add(ur)

            # 9. Mark staging records as APPROVED
            temple_req.status = "APPROVED"
            temple_req.reviewed_by = approver_id
            temple_req.reviewed_at = datetime.now(timezone.utc)

            user_req.status = "APPROVED"

            # 10. Audit log
            await AuditService.log_action(
                db=db,
                temple_id=temple.id,
                user_id=approver_id,
                role="SUPER_ADMIN",
                module_name="onboarding",
                action="TEMPLE_APPROVED",
                action_type="APPROVE",
                entity_id=str(temple.id),
                new_value={
                    "temple_name": temple.name,
                    "domain": temple.domain,
                    "temple_code": temple_code,
                    "manager_user_id": str(user.id),
                    "request_id": str(request_id),
                },
                details=f"Temple '{temple.name}' approved and created with code {temple_code}",
            )

            await db.flush()

            # 11. Dispatch notification
            try:
                from app.services.notification_service import NotificationService
                await NotificationService._stage_notification(
                    db=db,
                    temple_id=temple.id,
                    title="Temple Registration Approved",
                    message=f"Your temple '{temple.name}' has been approved. You can now log in.",
                    user_id=user.id,
                )
            except Exception as e:
                logger.warning("Notification dispatch failed (non-critical): %s", e)

            # Commit if we started the transaction
            if tx:
                await tx.commit()
            else:
                await db.commit()

        except Exception as e:
            if not db.in_transaction():
                 await db.rollback()
            logger.error(f"Approval transaction failed: {str(e)}")
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(status_code=500, detail=f"Approval failed: {str(e)}")
        logger.info(
            "Temple approved: %s (domain=%s, temple_id=%s) by approver %s",
            temple.name, temple.domain, temple.id, approver_id,
        )

        # Event hooks — standardized payloads
        emit_event(TEMPLE_CREATED, build_event_payload(
            entity="temple",
            entity_id=str(temple.id),
            event=TEMPLE_CREATED,
            triggered_by=str(approver_id),
            old=None,
            new={
                "name": temple.name,
                "domain": temple.domain,
                "temple_code": temple_code,
            },
        ))
        emit_event(TEMPLE_STATUS_CHANGED, build_event_payload(
            entity="temple",
            entity_id=str(temple.id),
            event=TEMPLE_STATUS_CHANGED,
            triggered_by=str(approver_id),
            old={"status": "PENDING"},
            new={"status": "APPROVED"},
        ))

        return {
            "message": f"Temple '{temple.name}' approved and created",
            "temple_id": str(temple.id),
            "temple_code": temple_code,
            "user_id": str(user.id),
            "domain": temple.domain,
            "status": "APPROVED",
        }

    # ── Reject Temple ─────────────────────────────────────────────────
    @staticmethod
    async def reject_temple(
        db: AsyncSession,
        request_id: UUID,
        approver_id: UUID,
        rejection_reason: str,
    ) -> dict:
        """
        Reject a pending temple request.
        """
        if not rejection_reason or len(rejection_reason) < 10:
            raise HTTPException(status_code=400, detail="Rejection reason must be at least 10 characters")

        try:
            if not db.in_transaction():
                tx = await db.begin()
            else:
                tx = None

            # 1. Fetch temple request
            result = await db.execute(
                select(TempleRequest).filter(TempleRequest.id == request_id).with_for_update()
            )
            temple_req = result.scalars().first()
            if not temple_req:
                raise HTTPException(status_code=404, detail="Temple request not found")

            if temple_req.status != "PENDING":
                raise HTTPException(
                    status_code=400,
                    detail=f"Request already {temple_req.status.lower()}"
                )

            # 2. Mark as REJECTED
            temple_req.status = "REJECTED"
            temple_req.rejection_reason = rejection_reason
            temple_req.reviewed_by = approver_id
            temple_req.reviewed_at = datetime.now(timezone.utc)
            
            # --- Phase 1: Critical Fixes ---
            temple_req.rejected_by = approver_id
            temple_req.rejected_at = datetime.now(timezone.utc)

            # 3. Mark user request as REJECTED
            ur_result = await db.execute(
                select(UserRequest).filter(
                    UserRequest.temple_request_id == request_id,
                    UserRequest.status == "PENDING",
                )
            )
            user_req = ur_result.scalars().first()
            if user_req:
                user_req.status = "REJECTED"

            # 4. Audit log (Fix #7)
            await AuditService.log_action(
                db=db,
                temple_id=None,  # System-level action
                user_id=approver_id,
                role="SUPER_ADMIN",
                module_name="onboarding",
                action="TEMPLE_REJECTED",
                action_type="REJECT",
                entity_id=str(request_id),
                new_value={
                    "temple_name": temple_req.temple_name,
                    "domain": temple_req.domain,
                    "rejection_reason": rejection_reason,
                    "rejected_by": str(approver_id),
                    "rejected_at": temple_req.rejected_at.isoformat(),
                },
                details=f"Temple '{temple_req.temple_name}' rejected: {rejection_reason}",
            )

            if tx:
                await tx.commit()
            else:
                await db.commit()

        except Exception as e:
            if not db.in_transaction():
                await db.rollback()
            logger.error(f"Rejection transaction failed: {str(e)}")
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(status_code=500, detail=f"Rejection failed: {str(e)}")

        logger.info(
            "Temple rejected: %s (domain=%s) by approver %s — reason: %s",
            temple_req.temple_name, temple_req.domain, approver_id, rejection_reason,
        )

        return {
            "message": f"Temple '{temple_req.temple_name}' rejected",
            "request_id": str(request_id),
            "status": "REJECTED",
            "rejection_reason": rejection_reason,
        }

