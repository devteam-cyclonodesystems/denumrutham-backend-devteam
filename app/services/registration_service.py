"""
Registration Service — Unified registration with email/phone detection,
mock OTP, and role-specific flows (DEVOTEE, TEMPLE_MANAGER, STAFF).
"""
import re
import random
import string
import logging
import unicodedata
from datetime import datetime, timezone, timedelta
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException

from app.models.domain import User, Temple, UserTemple, DevoteeProfile, TempleProfile, StaffInvite, TempleStatusAudit
from app.core.security import get_password_hash, async_verify_password, create_access_token
from app.services.audit_service import AuditService
from app.services.temple_events import emit_event, TEMPLE_STATUS_CHANGED

logger = logging.getLogger("tms.services.registration_service")


def _detect_email_or_phone(value: str) -> tuple[str | None, str | None]:
    """Detect whether the value is an email or phone number.
    Returns (email, phone) — one will be None.
    """
    value = value.strip()
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if re.match(email_pattern, value):
        return value, None
    return None, value


def _slugify(text: str) -> str:
    """Generate a URL-safe slug from text."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")


def _generate_otp() -> str:
    """Generate a 6-digit mock OTP."""
    return "".join(random.choices(string.digits, k=6))


# ── Redirect URL mapping ─────────────────────────────────────────────
ROLE_REDIRECT_MAP = {
    "DEVOTEE": "/temples",
    "TEMPLE_MANAGER": "/manager",
    "STAFF": "/manager",
    "SUPER_ADMIN": "/admin/dashboard",
    "SUPERADMIN": "/admin/dashboard",
    "ADMIN": "/manager",
}


class RegistrationService:
    """Handles all registration and OTP flows."""

    # ── Unified Registration ──────────────────────────────────────────
    @staticmethod
    async def register(
        db: AsyncSession,
        email_or_phone: str,
        password: str,
        name: str,
        role: str,
        temple_domain: str | None = None,
        temple_id: str | None = None,
        temple_code: str | None = None,
        confirm_password: str | None = None,
        invite_token: str | None = None,
        onboarding_method: str | None = "INVITE_TOKEN",
    ) -> dict:
        """
        Unified registration with 3 entry roles.
        
        - DEVOTEE: creates user immediately with ACTIVE status
        - TEMPLE_MANAGER: use register_temple_manager() instead
        - STAFF: requires temple_domain, creates user with PENDING status
        """
        if confirm_password and password != confirm_password:
            raise HTTPException(status_code=400, detail="Passwords do not match")
        email, phone = _detect_email_or_phone(email_or_phone)
        login_id = email or phone

        # ── Check uniqueness ──────────────────────────────────────────
        existing = await db.execute(
            select(User).filter(User.user_id == login_id, User.is_active == True)
        )
        if existing.scalars().first():
            raise HTTPException(status_code=400, detail="This email or phone is already registered")

        if email:
            dup_email = await db.execute(select(User).filter(User.email == email))
            if dup_email.scalars().first():
                raise HTTPException(status_code=400, detail="Email already registered")
        if phone:
            dup_phone = await db.execute(select(User).filter(User.phone == phone))
            if dup_phone.scalars().first():
                raise HTTPException(status_code=400, detail="Phone number already registered")

        # ── Role-specific logic ───────────────────────────────────────
        temple_id = None
        user_status = "ACTIVE"
        
        # Default for DEVOTEE is active
        if role == "DEVOTEE":
            user_status = "ACTIVE"
            onboarding_method = "INVITE_TOKEN" # sentinel
        
        elif role == "STAFF":
            # 1. INVITE TOKEN FLOW
            if onboarding_method == "INVITE_TOKEN" or (invite_token and not onboarding_method):
                if not invite_token:
                    raise HTTPException(status_code=403, detail="Staff registration requires a valid invite token")
                
                # Validate Invite
                invite_stmt = select(StaffInvite).filter(
                    StaffInvite.token == invite_token,
                    StaffInvite.email == email,
                    StaffInvite.expires_at > datetime.now(timezone.utc),
                    StaffInvite.is_used == False
                )
                invite_result = await db.execute(invite_stmt)
                invite = invite_result.scalar_one_or_none()
                
                if not invite:
                    raise HTTPException(status_code=403, detail="Invalid or expired invite token")
                
                temple_id = invite.temple_id
                
                # Cross-check temple exists
                temple_result = await db.execute(select(Temple).filter(Temple.id == temple_id, Temple.is_active == True))
                temple = temple_result.scalars().first()
                if not temple:
                    raise HTTPException(status_code=404, detail="Temple linked to invite no longer exists")
                
                user_status = "ACTIVE"
                onboarding_method = "INVITE_TOKEN"
                
                # Mark invite as used
                invite.is_used = True
                invite.used_at = datetime.now(timezone.utc)
            
            # 2. DOMAIN APPROVAL FLOW
            elif onboarding_method == "DOMAIN_APPROVAL":
                if not temple_domain:
                    raise HTTPException(status_code=403, detail="Staff registration via domain requires a temple domain")
                
                temple_stmt = select(Temple).filter(
                    Temple.domain == temple_domain,
                    Temple.status == "APPROVED",
                    Temple.is_active == True
                )
                temple_result = await db.execute(temple_stmt)
                temple = temple_result.scalar_one_or_none()
                
                if not temple:
                    raise HTTPException(
                        status_code=404, 
                        detail="Temple not found or not active. Please check the temple domain."
                    )
                
                # Check for operational state
                if hasattr(temple, 'operational_state') and temple.operational_state != 'ACTIVE':
                    raise HTTPException(
                        status_code=403,
                        detail=f"Temple is currently in {temple.operational_state} mode and cannot accept new registrations."
                    )

                temple_id = temple.id
                user_status = "PENDING_APPROVAL" # Needs manager approval
                onboarding_method = "DOMAIN_APPROVAL"
            
            else:
                raise HTTPException(
                    status_code=403, 
                    detail="Staff registration requires a valid invite token"
                )

        # ── Create User ───────────────────────────────────────────────
        user = User(
            user_id=login_id,
            name=name,
            email=email,
            phone=phone,
            password_hash=get_password_hash(password),
            role=role,
            status=user_status,
            temple_id=temple_id,
            onboarding_method=onboarding_method,
            approval_status="APPROVED" if user_status == "ACTIVE" else "PENDING"
        )
        db.add(user)
        await db.flush()

        # ── Create DevoteeProfile for DEVOTEE role ────────────────────
        if role == "DEVOTEE":
            profile = DevoteeProfile(
                user_id=user.id,
                name=name,
            )
            db.add(profile)

        # ── Create UserTemple mapping for STAFF ───────────────────────
        if role == "STAFF" and temple_id:
            mapping = UserTemple(
                user_id=user.id,
                temple_id=temple_id,
                role="STAFF",
            )
            db.add(mapping)

        await db.commit()
        await db.refresh(user)

        # ── Notifications ─────────────────────────────────────────────
        if role == "STAFF" and onboarding_method == "DOMAIN_APPROVAL":
            from app.services.notification_service import NotificationService, NotificationEvent
            await NotificationService.dispatch_event(
                db=db,
                temple_id=temple_id,
                event_type=NotificationEvent.STAFF_REGISTERED,
                title="New Staff Request",
                message=f"New staff registration request from {user.name} pending approval.",
                requester_id=user.id
            )
            await db.commit()

        logger.info(
            "User registered: %s (role=%s, status=%s)",
            user.user_id, role, user_status,
        )

        return {
            "message": "Registration successful" if user_status == "ACTIVE"
                       else "Registration submitted. Awaiting temple manager approval.",
            "user_id": str(user.id),
            "role": role,
            "status": user_status,
            "temple_id": str(temple_id) if temple_id else None,
            "onboarding_method": onboarding_method
        }

    # ── Temple Manager Registration ───────────────────────────────────
    @staticmethod
    async def register_temple_manager(
        db: AsyncSession,
        email_or_phone: str,
        password: str,
        name: str,
        temple_name: str,
        temple_contact_number: str = "",
        temple_email: str = "",
        temple_location: str = "",
        temple_state: str = "",
        temple_district: str = "",
    ) -> dict:
        """
        Temple registration flow:
        1. Creates Temple record with status=PENDING
        2. Creates User with role=TEMPLE_MANAGER
        3. Creates UserTemple mapping
        4. Requires SUPER_ADMIN approval to activate temple
        """
        email, phone = _detect_email_or_phone(email_or_phone)
        login_id = email or phone

        # ── Uniqueness checks ─────────────────────────────────────────
        existing = await db.execute(select(User).filter(User.user_id == login_id, User.is_active == True))
        if existing.scalars().first():
            raise HTTPException(status_code=400, detail="This email or phone is already registered")

        temple_dup = await db.execute(
            select(Temple).filter(Temple.name.ilike(temple_name.strip()))
        )
        if temple_dup.scalars().first():
            raise HTTPException(status_code=400, detail="A temple with this name already exists")

        # ── Create User (TEMPLE_MANAGER) ──────────────────────────────
        user = User(
            user_id=login_id,
            name=name,
            email=email,
            phone=phone,
            password_hash=get_password_hash(password),
            role="TEMPLE_MANAGER",
            status="ACTIVE",
        )
        db.add(user)
        await db.flush()

        # ── Create Temple (PENDING) ───────────────────────────────────
        domain_slug = _slugify(temple_name.strip())
        domain_check = await db.execute(select(Temple).filter(Temple.domain == domain_slug))
        if domain_check.scalars().first():
            import uuid as uuid_mod
            domain_slug = f"{domain_slug}-{str(uuid_mod.uuid4())[:6]}"

        temple = Temple(
            name=temple_name.strip(),
            domain=domain_slug,
            contact_number=temple_contact_number,
            email=temple_email,
            location=temple_location,
            state=temple_state,
            district=temple_district,
            status="PENDING",  # Requires SUPER_ADMIN approval
            created_by=user.id,
        )
        db.add(temple)
        await db.flush()

        # ── Create TempleProfile ──────────────────────────────────────
        profile = TempleProfile(
            temple_id=temple.id,
            location=temple_location,
            district=temple_district,
            state=temple_state,
            contact_number=temple_contact_number,
            email=temple_email,
        )
        db.add(profile)

        # ── Update user's temple_id and create mapping ────────────────
        user.temple_id = temple.id
        mapping = UserTemple(
            user_id=user.id,
            temple_id=temple.id,
            role="TEMPLE_MANAGER",
        )
        db.add(mapping)

        await db.commit()
        await db.refresh(user)
        await db.refresh(temple)

        logger.info(
            "Temple registered: %s (domain=%s, status=PENDING) by manager %s",
            temple.name, temple.domain, user.user_id,
        )

        return {
            "message": "Temple registration submitted. Awaiting SUPER_ADMIN approval.",
            "user_id": str(user.id),
            "role": "TEMPLE_MANAGER",
            "status": "ACTIVE",
            "temple_id": str(temple.id),
            "temple_status": "PENDING",
        }

    # ── Login with Redirect ───────────────────────────────────────────────
    @staticmethod
    async def login_with_redirect(db: AsyncSession, username: str, password: str) -> dict:
        """Login and return redirect URL based on role."""
        from sqlalchemy.orm import joinedload
        
        # Normalize input: trim and lowercase
        username = username.strip()
        username_lower = username.lower()
        
        logger.info(f"Login attempt for: '{username}'")
        
        result = await db.execute(
            select(User)
            .filter(or_(
                User.user_id == username, 
                User.user_id == username_lower,
                User.email == username,
                User.email == username_lower
            ))
        )
        user = result.scalars().first()

        if not user:
            logger.warning(f"User not found: '{username}' (tried lower: '{username_lower}')")
            raise HTTPException(status_code=400, detail="Incorrect username or password")
        
        matches = await async_verify_password(password, user.password_hash)
        if not matches:
            logger.warning(f"Password mismatch for user: '{user.user_id}'")
            raise HTTPException(status_code=400, detail="Incorrect username or password")

        # Fix #5: Comprehensive login guard
        if not user.is_active:
            raise HTTPException(status_code=403, detail="Your account has been deactivated")

        if user.status == "PENDING":
            raise HTTPException(status_code=403, detail="Your account is pending verification")

        if user.status == "REJECTED":
            raise HTTPException(status_code=403, detail="Your registration request was rejected")

        if user.status == "DISABLED":
            raise HTTPException(status_code=403, detail="Your account has been disabled")

        if user.status == "SUSPENDED":
            raise HTTPException(status_code=403, detail="Your account has been suspended")

        temple_management_mode = None
        subscription_plan = None
        # Check temple approval status — block login if temple not approved
        if user.temple_id:
            temple_result = await db.execute(
                select(Temple).filter(Temple.id == user.temple_id)
            )
            temple = temple_result.scalars().first()
            if temple:
                temple_management_mode = temple.management_mode
                subscription_plan = temple.subscription_plan
            if temple and temple.status != "APPROVED":
                if temple.status == "PENDING":
                    raise HTTPException(
                        status_code=403,
                        detail="Your temple registration is pending approval"
                    )
                elif temple.status == "REJECTED":
                    raise HTTPException(
                        status_code=403,
                        detail="Your temple registration was rejected"
                    )
                else:
                    raise HTTPException(
                        status_code=403,
                        detail="Temple is not active"
                    )

        access_token = create_access_token(
            subject=user.id,
            temple_id=str(user.temple_id) if user.temple_id else None,
            role=user.role,
            username=user.user_id,
            user_status=user.status,
            security_version=getattr(user, 'security_version', None),
            force_password_change=getattr(user, 'force_password_change', False),
            temple_management_mode=temple_management_mode,
            subscription_plan=subscription_plan
        )

        # ── Role-based Redirect Logic (Refined) ───────────────────────
        redirect_url = "/"
        if user.system_role:
            if user.system_role.name == "SUPER_ADMIN":
                redirect_url = "/admin/dashboard"
            elif user.system_role.name in ("TEMPLE_ADMIN", "STAFF"):
                redirect_url = "/manager"
            elif user.system_role.name == "DEVOTEE":
                redirect_url = "/temples"
        else:
            # Fallback to legacy role-string mapping
            redirect_url = ROLE_REDIRECT_MAP.get(user.role, "/")

        # ── Access Shell Redirect ─────────────────────────────────────
        if user.status == "PENDING_APPROVAL":
            redirect_url = "/pending-approval"

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "role": user.role,
            "redirect_url": redirect_url,
            "user_status": user.status,
            "temple_id": str(user.temple_id) if user.temple_id else None,
            "force_password_change": getattr(user, 'force_password_change', False),
            "user_id": str(user.id),
        }

    # ── OTP Flow (Mock) ──────────────────────────────────────────────
    @staticmethod
    async def request_otp(db: AsyncSession, email_or_phone: str) -> dict:
        """Generate and store a mock OTP for verification."""
        email, phone = _detect_email_or_phone(email_or_phone)
        login_id = email or phone

        result = await db.execute(select(User).filter(User.user_id == login_id, User.is_active == True))
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        otp = _generate_otp()
        user.otp_code = otp
        user.otp_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        await db.commit()

        logger.info("OTP generated for %s: %s (mock - visible in logs only)", login_id, otp)

        return {
            "message": "OTP sent successfully",
            "otp_mock": otp,  # Only in development — remove in actual production
            "expires_in_minutes": 5,
        }

    @staticmethod
    async def verify_otp(db: AsyncSession, email_or_phone: str, otp_code: str) -> dict:
        """Verify the OTP code."""
        email, phone = _detect_email_or_phone(email_or_phone)
        login_id = email or phone

        result = await db.execute(select(User).filter(User.user_id == login_id, User.is_active == True))
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if not user.otp_code:
            raise HTTPException(status_code=400, detail="No OTP was requested")

        if user.otp_expires_at and user.otp_expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=400, detail="OTP has expired")

        if user.otp_code != otp_code:
            raise HTTPException(status_code=400, detail="Invalid OTP code")

        # Clear OTP after successful verification
        user.otp_code = None
        user.otp_expires_at = None
        await db.commit()

        temple_management_mode = None
        subscription_plan = None
        if user.temple_id:
            temple_result = await db.execute(
                select(Temple).filter(Temple.id == user.temple_id)
            )
            temple = temple_result.scalars().first()
            if temple:
                temple_management_mode = temple.management_mode
                subscription_plan = temple.subscription_plan

        # Generate access token
        access_token = create_access_token(
            subject=user.id,
            temple_id=str(user.temple_id) if user.temple_id else None,
            role=user.role,
            username=user.user_id,
            temple_management_mode=temple_management_mode,
            subscription_plan=subscription_plan
        )

        return {
            "message": "OTP verified successfully",
            "access_token": access_token,
            "token_type": "bearer",
            "verified": True,
        }

    # ── Staff Approval (by TEMPLE_MANAGER) ────────────────────────────
    @staticmethod
    async def approve_staff(
        db: AsyncSession,
        staff_user_id: UUID,
        approver_id: UUID,
        temple_id: UUID,
    ) -> dict:
        """Approve a pending staff registration."""
        result = await db.execute(
            select(User).filter(
                User.id == staff_user_id,
                User.role == "STAFF",
                User.status == "PENDING_APPROVAL",
                User.temple_id == temple_id
            )
        )
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="Pending staff user not found")

        # Ensure approver is not the same user
        if staff_user_id == approver_id:
            raise HTTPException(status_code=400, detail="Cannot approve your own registration")

        user.status = "ACTIVE"
        user.approval_status = "APPROVED"
        user.approved_by = approver_id
        user.approved_at = datetime.now(timezone.utc)
        
        # Add to UserTemple mapping if not exists
        mapping_stmt = select(UserTemple).filter_by(user_id=user.id, temple_id=temple_id)
        mapping_result = await db.execute(mapping_stmt)
        if not mapping_result.scalars().first():
            mapping = UserTemple(
                user_id=user.id,
                temple_id=temple_id,
                role="STAFF",
            )
            db.add(mapping)

        # Audit Log
        from app.modules.audit.services.audit_service import AuditService
        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=approver_id,
            role=None,
            module_name="HR_PAYROLL",
            action="STAFF_APPROVED",
            action_type="UPDATE",
            entity_id=str(user.id),
            new_value={"status": "ACTIVE", "approval_status": "APPROVED"},
            details=f"Staff {user.name} approved by manager."
        )

        await db.commit()

        logger.info("Staff %s approved by %s", staff_user_id, approver_id)

        return {
            "message": "Staff registration approved",
            "user_id": str(user.id),
            "status": "ACTIVE",
        }

    @staticmethod
    async def reject_staff(
        db: AsyncSession,
        staff_user_id: UUID,
        rejector_id: UUID,
        temple_id: UUID,
        reason: str = "Registration rejected by manager"
    ) -> dict:
        """Reject a pending staff registration."""
        result = await db.execute(
            select(User).filter(
                User.id == staff_user_id,
                User.role == "STAFF",
                User.status == "PENDING_APPROVAL",
                User.temple_id == temple_id
            )
        )
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="Pending staff user not found")

        user.status = "REJECTED"
        user.approval_status = "REJECTED"
        user.rejected_by = rejector_id
        user.rejected_at = datetime.now(timezone.utc)
        user.rejection_reason = reason

        # Audit Log
        from app.modules.audit.services.audit_service import AuditService
        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=rejector_id,
            role=None,
            module_name="HR_PAYROLL",
            action="STAFF_REJECTED",
            action_type="UPDATE",
            entity_id=str(user.id),
            new_value={"status": "REJECTED", "approval_status": "REJECTED", "reason": reason},
            details=f"Staff {user.name} rejected by manager."
        )

        await db.commit()

        return {
            "message": "Staff registration rejected",
            "user_id": str(user.id),
            "status": "REJECTED",
        }

    # ── Temple Approval (by SUPER_ADMIN) ──────────────────────────────
    @staticmethod
    async def approve_temple(db: AsyncSession, temple_id: UUID, approver_id: UUID) -> dict:
        """Approve a pending temple registration.
        
        Phase 4: Full atomic transaction with row-level lock and version increment.
        """
        try:
            # Phase 1 Fix: Handle existing transaction from get_db
            if not db.in_transaction():
                tx = await db.begin()
            else:
                tx = None

            result = await db.execute(
                select(Temple).filter(Temple.id == temple_id).with_for_update()
            )
            temple = result.scalars().first()
            if not temple:
                raise HTTPException(status_code=404, detail="Pending temple not found")

            VALID_TRANSITIONS = {
                "PENDING": ["APPROVED", "REJECTED"],
                "APPROVED": [],
                "REJECTED": []
            }
            
            current_status = temple.status or "PENDING"
            if "APPROVED" not in VALID_TRANSITIONS.get(current_status, []):
                raise Exception("Invalid status transition")

            temple.status = "APPROVED"
            
            # Phase 1 Hardening: Explicit approval audit fields
            temple.approved_at = datetime.now(timezone.utc)
            temple.approved_by = approver_id
            
            # Phase 4: Atomic version increment under row lock
            temple.version = (temple.version or 1) + 1
            temple.updated_at = datetime.now(timezone.utc)
            
            # Insert audit record
            audit = TempleStatusAudit(
                temple_id=temple.id,
                old_status=current_status,
                new_status="APPROVED",
                changed_by=approver_id,
                reason="Approved via registration flow"
            )
            db.add(audit)

            # Centralized Audit Log Integration
            from app.modules.audit.services.audit_service import AuditService
            await AuditService.log_action(
                db=db,
                temple_id=temple.id,
                user_id=approver_id,
                role="SUPER_ADMIN",
                module_name="TEMPLE_MANAGEMENT",
                action="TEMPLE_STATUS_CHANGED",
                action_type="UPDATE",
                entity_id=str(temple.id),
                old_value={"status": current_status},
                new_value={"status": "APPROVED"},
                details=f"Temple '{temple.name}' status approved by super admin."
            )

            if tx:
                await tx.commit()
            else:
                await db.commit()

        except Exception as e:
            if not db.in_transaction():
                await db.rollback()
            logger.error(f"Legacy approval failed: {str(e)}")
            if isinstance(e, HTTPException):
                raise
            raise HTTPException(status_code=500, detail=f"Approval failed: {str(e)}")

        logger.info("Temple %s approved by %s", temple.name, approver_id)

        # Event hook
        emit_event(TEMPLE_STATUS_CHANGED, {
            "temple_id": str(temple.id),
            "old_status": current_status,
            "new_status": "APPROVED",
            "changed_by": str(approver_id),
        })

        return {
            "message": f"Temple '{temple.name}' approved",
            "temple_id": str(temple.id),
            "status": "APPROVED",
        }

    @staticmethod
    async def reject_temple(db: AsyncSession, temple_id: UUID, approver_id: UUID) -> dict:
        """Reject a pending temple registration.
        
        Phase 4: Full atomic transaction with row-level lock and version increment.
        """
        async with db.begin_nested():
            result = await db.execute(
                select(Temple).filter(Temple.id == temple_id).with_for_update()
            )
            temple = result.scalars().first()
            if not temple:
                raise HTTPException(status_code=404, detail="Pending temple not found")

            VALID_TRANSITIONS = {
                "PENDING": ["APPROVED", "REJECTED"],
                "APPROVED": [],
                "REJECTED": []
            }
            
            current_status = temple.status or "PENDING"
            if "REJECTED" not in VALID_TRANSITIONS.get(current_status, []):
                raise Exception("Invalid status transition")

            temple.status = "REJECTED"
            
            # Phase 4: Atomic version increment under row lock
            from app.models.domain import utcnow
            temple.version = (temple.version or 1) + 1
            temple.updated_at = utcnow()
            
            # Insert audit record
            audit = TempleStatusAudit(
                temple_id=temple.id,
                old_status=current_status,
                new_status="REJECTED",
                changed_by=approver_id,
                reason="Rejected via registration flow"
            )
            db.add(audit)

            # Centralized Audit Log Integration
            from app.modules.audit.services.audit_service import AuditService
            await AuditService.log_action(
                db=db,
                temple_id=temple.id,
                user_id=approver_id,
                role="SUPER_ADMIN",
                module_name="TEMPLE_MANAGEMENT",
                action="TEMPLE_STATUS_CHANGED",
                action_type="UPDATE",
                entity_id=str(temple.id),
                old_value={"status": current_status},
                new_value={"status": "REJECTED"},
                details=f"Temple '{temple.name}' status rejected by super admin."
            )
        await db.commit()

        # Event hook
        emit_event(TEMPLE_STATUS_CHANGED, {
            "temple_id": str(temple.id),
            "old_status": current_status,
            "new_status": "REJECTED",
            "changed_by": str(approver_id),
        })

        return {
            "message": f"Temple '{temple.name}' rejected",
            "temple_id": str(temple.id),
            "status": "REJECTED",
        }

    # ── List Pending Staff (for TEMPLE_MANAGER) ───────────────────────
    @staticmethod
    async def list_pending_staff(db: AsyncSession, temple_id: UUID) -> list:
        """List all pending staff registrations for a temple."""
        result = await db.execute(
            select(User).filter(
                User.temple_id == temple_id,
                User.role == "STAFF",
                User.status == "PENDING_APPROVAL",
            )
        )
        users = result.scalars().all()
        return [
            {
                "id": str(u.id),
                "name": u.name,
                "email": u.email,
                "phone": u.phone,
                "role": u.role,
                "status": u.status,
                "onboarding_method": u.onboarding_method,
                "created_at": u.created_at,
            }
            for u in users
        ]

    # ── List Pending Temples (for SUPER_ADMIN) ────────────────────────
    @staticmethod
    async def list_pending_temples(db: AsyncSession) -> list:
        """List all pending temple registrations."""
        result = await db.execute(
            select(Temple).filter(Temple.status == "PENDING").order_by(Temple.created_at.desc())
        )
        temples = result.scalars().all()
        return [
            {
                "id": str(t.id),
                "name": t.name,
                "domain": t.domain,
                "contact_number": t.contact_number,
                "email": t.email,
                "status": t.status,
                "created_at": t.created_at,
            }
            for t in temples
        ]
