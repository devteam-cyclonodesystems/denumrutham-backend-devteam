import logging
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, or_
from fastapi import HTTPException

from app.models.domain import User, UserTemple, AuditLog, Temple
from app.core.security import get_password_hash
from app.schemas.staff import StaffCreate, StaffUpdate

logger = logging.getLogger("tms.services.staff_service")

class StaffService:
    @staticmethod
    async def create_staff(db: AsyncSession, staff_in: StaffCreate, temple_id: UUID, creator_id: UUID) -> User:
        # Check uniqueness
        from app.services.registration_service import _detect_email_or_phone
        email, phone = _detect_email_or_phone(staff_in.email_or_phone)
        login_id = email or phone

        existing = await db.execute(
            select(User).filter(or_(User.user_id == login_id, User.email == email, User.phone == phone))
        )
        if existing.scalars().first():
            raise HTTPException(status_code=400, detail="User already exists with this email/phone")

        # Create user
        user = User(
            user_id=login_id,
            name=staff_in.name,
            email=email,
            phone=phone,
            password_hash=get_password_hash(staff_in.temporary_password),
            role="STAFF",
            status="ACTIVE",
            temple_id=temple_id,
            onboarding_method="ADMIN_CREATED",
            approval_status="APPROVED",
            force_password_change=True
        )
        db.add(user)
        await db.flush()

        # Add to UserTemple mapping
        mapping = UserTemple(
            user_id=user.id,
            temple_id=temple_id,
            role="STAFF",
        )
        db.add(mapping)

        # Assign Role (if role_id is provided)
        if hasattr(staff_in, 'role_id') and staff_in.role_id:
            from app.models.rbac import UserRole
            ur = UserRole(
                user_id=user.id,
                role_id=staff_in.role_id,
                temple_id=temple_id
            )
            db.add(ur)

        # Audit log
        audit = AuditLog(
            temple_id=temple_id,
            user_id=creator_id,
            action="STAFF_CREATED",
            action_type="CREATE",
            entity_id=str(user.id),
            new_value={"name": user.name, "role": user.role, "onboarding_method": "ADMIN_CREATED"},
            details=f"Staff {user.name} created by manager."
        )
        db.add(audit)

        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def get_staff_list(db: AsyncSession, temple_id: UUID) -> list[User]:
        result = await db.execute(
            select(User).filter(User.temple_id == temple_id, User.role == "STAFF")
        )
        return result.scalars().all()

    @staticmethod
    async def update_staff_status(db: AsyncSession, staff_id: UUID, status: str, temple_id: UUID, actor_id: UUID) -> User:
        result = await db.execute(
            select(User).filter(User.id == staff_id, User.temple_id == temple_id)
        )
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="Staff not found")

        old_status = user.status
        user.status = status
        
        # Audit log
        audit = AuditLog(
            temple_id=temple_id,
            user_id=actor_id,
            action="STAFF_STATUS_UPDATED",
            action_type="UPDATE",
            entity_id=str(user.id),
            old_value={"status": old_status},
            new_value={"status": status},
            details=f"Staff {user.name} status updated from {old_status} to {status}."
        )
        db.add(audit)
        
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def reset_password(db: AsyncSession, staff_id: UUID, new_password: str, temple_id: UUID, actor_id: UUID) -> User:
        result = await db.execute(
            select(User).filter(User.id == staff_id, User.temple_id == temple_id)
        )
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="Staff not found")

        user.password_hash = get_password_hash(new_password)
        user.force_password_change = True
        
        # Audit log
        audit = AuditLog(
            temple_id=temple_id,
            user_id=actor_id,
            action="STAFF_PASSWORD_RESET",
            action_type="UPDATE",
            entity_id=str(user.id),
            details=f"Staff {user.name} password reset by manager."
        )
        db.add(audit)
        
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def get_staff_counts(db: AsyncSession, temple_id: UUID) -> dict:
        stmt = select(User.status, func.count(User.id)).filter(
            User.temple_id == temple_id, User.role == "STAFF"
        ).group_by(User.status)
        result = await db.execute(stmt)
        counts = {row[0]: row[1] for row in result.all()}
        
        # Also need "on leave" from Employee model if linked
        # For now, let's just return what we have from User
        return {
            "total": sum(counts.values()),
            "active": counts.get("ACTIVE", 0),
            "suspended": counts.get("SUSPENDED", 0),
            "on_leave": 0 # placeholder
        }

    @staticmethod
    async def complete_force_password_reset(db: AsyncSession, user_id: UUID, new_password: str) -> dict:
        result = await db.execute(select(User).filter(User.id == user_id))
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.password_hash = get_password_hash(new_password)
        user.force_password_change = False
        
        # Audit log
        audit = AuditLog(
            temple_id=user.temple_id,
            user_id=user.id,
            action="PASSWORD_CHANGED_FIRST_LOGIN",
            action_type="UPDATE",
            entity_id=str(user.id),
            details="User completed mandatory password reset on first login."
        )
        db.add(audit)
        
        await db.commit()
        return {"status": "success", "message": "Password updated"}

    @staticmethod
    async def seed_global_permissions(db: AsyncSession):
        from app.models.rbac import Permission
        
        global_perms = [
            # Archana Module
            ("tab", "archana:view_queue", "View Ritual Queue"),
            ("button", "archana:create_booking", "Create Archana Booking"),
            ("button", "archana:edit_booking", "Edit Archana Booking"),
            ("button", "archana:start_ritual", "Start Ritual Execution"),
            ("button", "archana:complete_ritual", "Complete Ritual Execution"),
            ("button", "archana:issue_refund", "Approve Archana Refund (Sensitive)"),
            ("tab", "archana:manage_services", "Manage Archana Catalog Services"),
            ("button", "archana:daily_closing", "Perform Archana Daily closing (Sensitive)"),
            ("tab", "archana:manage_deities", "Manage Deities Master List"),

            # Inventory Module
            ("tab", "inventory:view_stock", "View Kalavara Stock List"),
            ("button", "inventory:request_materials", "Request Materials for Rituals"),
            ("button", "inventory:approve_requests", "Approve Material Requests (Sensitive)"),
            ("button", "inventory:issue_stock", "Issue Stock to Department (Sensitive)"),
            ("button", "inventory:receive_stock", "Receive New Procurement Stock"),
            ("button", "inventory:create_po", "Create Purchase Orders (Sensitive)"),
            ("tab", "inventory:manage_suppliers", "Manage Suppliers Directory"),
            ("button", "inventory:adjust_stock", "Adjust Inventory Stock Levels (Sensitive)"),
            ("tab", "inventory:view_request_history", "View Material Requests History"),
            ("tab", "inventory:view_purchase_history", "View Procurement Invoices History"),
            ("button", "inventory:create_request", "Create Material Request"),
            ("tab", "inventory:view_request", "View Material Requests"),
            ("button", "inventory:approve_request", "Approve / Reject Material Requests"),
            ("button", "inventory:cancel_request", "Cancel Material Request"),
            ("button", "inventory:return_items", "Return Unused Inventory Items"),

            # Temple Store
            ("button", "store:create_sale", "Create Store Sale / POS Checkout"),
            ("button", "store:issue_refund", "Issue Store Sale Refund (Sensitive)"),
            ("tab", "store:manage_products", "Manage Store Products Catalog"),
            ("tab", "store:manage_categories", "Manage Store Product Categories"),
            ("button", "store:adjust_stock", "Adjust Store Inventory Stock (Sensitive)"),
            ("button", "store:manage_pricing", "Configure Store Product Pricing"),

            # Hall Booking
            ("tab", "hallbooking:view_bookings", "View Hall Bookings"),
            ("button", "hallbooking:create_booking", "Create Hall Booking"),
            ("button", "hallbooking:edit_booking", "Edit Hall Booking Details"),
            ("button", "hallbooking:cancel_booking", "Cancel Hall Booking"),
            ("button", "hallbooking:approve_booking", "Approve Hall Booking Request (Sensitive)"),

            # Donations
            ("button", "donations:receive_donation", "Receive Devotee Donation"),
            ("button", "donations:issue_receipt", "Issue Donation Receipt"),
            ("button", "donations:modify_donation", "Modify Donation Record"),
            ("button", "donations:approve_corrections", "Approve Donation Corrections (Sensitive)"),

            # Finance
            ("report", "finance:view_reports", "View Financial Ledger Reports"),
            ("button", "finance:daily_closing", "Perform Daily closing (Sensitive)"),
            ("button", "finance:approve_expenses", "Approve Operational Expenses (Sensitive)"),
            ("button", "finance:modify_records", "Modify Financial Records (Sensitive)"),

            # Generic Modules
            ("tab", "dashboard:view", "View Manager Dashboard"),
            ("tab", "nss:view", "View NSS Karayogam Member List"),
            ("tab", "nss:manage", "Manage NSS Karayogam Operations"),
            ("tab", "hr_payroll:view", "View Employee Directory & Attendance"),
            ("tab", "hr_payroll:manage", "Manage Payroll & Leaves"),
            ("report", "reports:view", "View System Analytics Reports"),
            ("tab", "governance:view", "View Audits and Approvals Dashboard"),
            ("tab", "governance:manage", "Configure Workflows and Rules"),
            ("tab", "settings:view", "View Temple Profile Settings"),
            ("tab", "settings:manage", "Configure Temple Rules & RBAC Permissions"),
            ("tab", "staff:manage_roles", "Manage Staff Roles & Permissions"),
            ("tab", "staff:manage_employees", "Manage Staff Accounts"),
        ]

        for r_type, r_key, desc in global_perms:
            existing = await db.execute(
                select(Permission).filter(Permission.resource_key == r_key)
            )
            perm = existing.scalar_one_or_none()
            if not perm:
                perm = Permission(
                    temple_id=None,
                    resource_type=r_type,
                    resource_key=r_key,
                    description=desc
                )
                db.add(perm)
            else:
                if perm.resource_type != r_type or perm.description != desc:
                    perm.resource_type = r_type
                    perm.description = desc
                    db.add(perm)
        
        await db.commit()

    @staticmethod
    async def seed_default_temple_roles(db: AsyncSession, temple_id: UUID):
        from app.models.rbac import Role, Permission, RolePermission
        
        templates = {
            "Pujari": [
                "dashboard:view",
                "archana:view_queue",
                "archana:start_ritual",
                "archana:complete_ritual",
                "inventory:view_stock",
                "inventory:request_materials",
                "inventory:view_request_history",
                "inventory:create_request",
                "inventory:view_request",
                "inventory:return_items"
            ],
            "Counter Staff": [
                "dashboard:view",
                "archana:view_queue",
                "archana:create_booking",
                "archana:edit_booking",
                "donations:receive_donation",
                "donations:issue_receipt"
            ],
            "Kalavara Staff": [
                "archana:view_queue",
                "inventory:view_stock",
                "inventory:approve_requests",
                "inventory:issue_stock",
                "inventory:receive_stock",
                "inventory:adjust_stock",
                "inventory:manage_suppliers",
                "inventory:create_po",
                "inventory:view_request",
                "inventory:approve_request",
                "inventory:cancel_request",
                "inventory:return_items"
            ],
            "Store Staff": [
                "store:create_sale",
                "store:manage_products",
                "store:manage_categories"
            ],
            "Accountant": [
                "dashboard:view",
                "finance:view_reports",
                "donations:receive_donation",
                "donations:issue_receipt",
                "reports:view"
            ],
            "Hall Booking Staff": [
                "dashboard:view",
                "hallbooking:view_bookings",
                "hallbooking:create_booking",
                "hallbooking:edit_booking",
                "hallbooking:cancel_booking"
            ],
            "Manager": [
                # Manager has all permissions
            ]
        }

        perms_result = await db.execute(select(Permission))
        perms_map = {p.resource_key: p for p in perms_result.scalars().all()}

        for role_name, allowed_keys in templates.items():
            role_result = await db.execute(
                select(Role).filter(Role.temple_id == temple_id, Role.name == role_name)
            )
            role = role_result.scalars().first()
            if not role:
                role = Role(
                    temple_id=temple_id,
                    name=role_name,
                    description=f"Default template for {role_name}"
                )
                db.add(role)
                await db.flush()
            
            keys_to_assign = allowed_keys if role_name != "Manager" else list(perms_map.keys())
            
            for key in keys_to_assign:
                perm = perms_map.get(key)
                if perm:
                    mapping_result = await db.execute(
                        select(RolePermission).filter(
                            RolePermission.role_id == role.id,
                            RolePermission.permission_id == perm.id
                        )
                    )
                    if not mapping_result.scalars().first():
                        rp = RolePermission(
                            role_id=role.id,
                            permission_id=perm.id,
                            access_level="full"
                        )
                        db.add(rp)
        
        await db.commit()
