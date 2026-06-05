import logging
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, or_
from sqlalchemy.orm.attributes import flag_modified
from fastapi import HTTPException

from app.models.domain import User, UserTemple, Temple
from app.core.security import get_password_hash
from app.schemas.staff import StaffCreate, StaffUpdate
from app.modules.audit.services.audit_service import AuditService

logger = logging.getLogger("tms.services.staff_service")

class StaffService:
    @staticmethod
    async def create_staff(db: AsyncSession, staff_in: StaffCreate, temple_id: UUID, creator_id: UUID) -> User:
        # Check uniqueness
        from app.services.registration_service import _detect_email_or_phone
        email, phone = _detect_email_or_phone(staff_in.email_or_phone)
        login_id = email or phone

        filters = [User.user_id == login_id]
        if email:
            filters.append(User.email == email)
        if phone:
            filters.append(User.phone == phone)

        existing = await db.execute(
            select(User).filter(or_(*filters))
        )
        if existing.scalars().first():
            raise HTTPException(status_code=400, detail="User already exists with this email/phone")

        # Create user
        now_str = datetime.now(timezone.utc).isoformat()
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
            force_password_change=True,
            department=staff_in.department,
            shift=staff_in.shift,
            dob=staff_in.dob,
            salary=staff_in.salary,
            photo_url=staff_in.photo_url,
            media_urls=staff_in.media_urls,
            remarks=staff_in.remarks,
            audit_trail=[{
                "event": "Joined",
                "timestamp": now_str,
                "notes": f"Staff account provisioned by administrator. Starting Salary: INR {staff_in.salary or 0.0}."
            }]
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
        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=creator_id,
            role=None,
            module_name="HR_PAYROLL",
            action="STAFF_CREATED",
            action_type="CREATE",
            entity_id=str(user.id),
            new_value={"name": user.name, "role": user.role, "onboarding_method": "ADMIN_CREATED"},
            details=f"Staff {user.name} created by manager."
        )

        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def get_staff_list(db: AsyncSession, temple_id: UUID) -> list[User]:
        result = await db.execute(
            select(User).filter(
                User.temple_id == temple_id, 
                User.role == "STAFF", 
                User.deleted_at.is_(None)
            )
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
        
        # Append to user.audit_trail
        current_audit = list(user.audit_trail) if user.audit_trail else []
        now_str = datetime.now(timezone.utc).isoformat()
        event_name = "Status Changed"
        if status == "ACTIVE":
            event_name = "Reactivated"
        elif status == "SUSPENDED":
            event_name = "Suspended"
        elif status == "RESIGNED":
            event_name = "Resigned"
        elif status == "TERMINATED":
            event_name = "Terminated"
        current_audit.append({
            "event": event_name,
            "timestamp": now_str,
            "notes": f"Status updated from {old_status} to {status}."
        })
        user.audit_trail = current_audit
        flag_modified(user, "audit_trail")

        # Audit log
        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=actor_id,
            role=None,
            module_name="HR_PAYROLL",
            action="STAFF_STATUS_UPDATED",
            action_type="UPDATE",
            entity_id=str(user.id),
            old_value={"status": old_status},
            new_value={"status": status},
            details=f"Staff {user.name} status updated from {old_status} to {status}."
        )
        
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def update_staff(db: AsyncSession, staff_id: UUID, staff_in: StaffUpdate, temple_id: UUID, actor_id: UUID) -> User:
        result = await db.execute(
            select(User).filter(User.id == staff_id, User.temple_id == temple_id)
        )
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="Staff not found")

        # Initialize audit_trail if it's None
        current_audit = list(user.audit_trail) if user.audit_trail else []
        now_str = datetime.now(timezone.utc).isoformat()

        # Track changes for audit log and local audit trail
        updates_made = []

        if staff_in.name is not None and staff_in.name != user.name:
            updates_made.append(f"Name changed from '{user.name}' to '{staff_in.name}'")
            user.name = staff_in.name

        if staff_in.department is not None and staff_in.department != user.department:
            updates_made.append(f"Department changed from '{user.department}' to '{staff_in.department}'")
            user.department = staff_in.department

        if staff_in.shift is not None and staff_in.shift != user.shift:
            updates_made.append(f"Shift changed from '{user.shift}' to '{staff_in.shift}'")
            user.shift = staff_in.shift

        if staff_in.dob is not None and staff_in.dob != user.dob:
            updates_made.append(f"DOB updated")
            user.dob = staff_in.dob

        if staff_in.remarks is not None and staff_in.remarks != user.remarks:
            updates_made.append(f"Remarks updated")
            user.remarks = staff_in.remarks

        if staff_in.photo_url is not None and staff_in.photo_url != user.photo_url:
            updates_made.append(f"Photo updated")
            user.photo_url = staff_in.photo_url

        if staff_in.media_urls is not None and staff_in.media_urls != user.media_urls:
            updates_made.append(f"Media files updated")
            user.media_urls = staff_in.media_urls

        if staff_in.salary is not None and staff_in.salary != user.salary:
            old_sal = user.salary or 0.0
            updates_made.append(f"Salary adjusted from INR {old_sal} to INR {staff_in.salary}")
            current_audit.append({
                "event": "Salary Adjusted",
                "timestamp": now_str,
                "notes": f"Salary updated from INR {old_sal} to INR {staff_in.salary}."
            })
            user.salary = staff_in.salary

        if staff_in.status is not None and staff_in.status != user.status:
            current = user.status
            target = staff_in.status
            
            valid = False
            if current == "ACTIVE":
                if target in ["SUSPENDED", "RESIGNED", "TERMINATED"]:
                    valid = True
            elif current == "SUSPENDED":
                if target in ["ACTIVE", "RESIGNED", "TERMINATED"]:
                    valid = True
            elif current == "RESIGNED":
                if target == "TERMINATED":
                    valid = True
            elif current == "TERMINATED":
                valid = False
                
            if not valid:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid employment status transition from '{current}' to '{target}'"
                )
                
            updates_made.append(f"Employment Status changed from {current} to {target}")
            event_name = "Status Changed"
            if target == "ACTIVE":
                event_name = "Reactivated"
            elif target == "SUSPENDED":
                event_name = "Suspended"
            elif target == "RESIGNED":
                event_name = "Resigned"
            elif target == "TERMINATED":
                event_name = "Terminated"
                
            current_audit.append({
                "event": event_name,
                "timestamp": now_str,
                "notes": f"Employment Status updated from {current} to {target}."
            })
            user.status = target

            # If resigned or terminated, soft-delete from active directory views
            if target in ["TERMINATED", "RESIGNED"]:
                user.deleted_at = datetime.now(timezone.utc)
                user.is_active = False
            else:
                user.deleted_at = None
                user.is_active = True

        if staff_in.availability_status is not None and staff_in.availability_status != user.availability_status:
            old_avail = user.availability_status or "AVAILABLE"
            target_avail = staff_in.availability_status
            
            if target_avail not in ["AVAILABLE", "ON_LEAVE"]:
                raise HTTPException(status_code=400, detail="Invalid availability status")
                
            updates_made.append(f"Availability Status changed from {old_avail} to {target_avail}")
            current_audit.append({
                "event": "Availability Changed",
                "timestamp": now_str,
                "notes": f"Availability updated from {old_avail} to {target_avail}."
            })
            user.availability_status = target_avail

        # If any updates were made, commit and log
        if updates_made:
            user.audit_trail = current_audit
            flag_modified(user, "audit_trail")
            # Create a system audit log entry
            await AuditService.log_action(
                db=db,
                temple_id=temple_id,
                user_id=actor_id,
                role=None,
                module_name="HR_PAYROLL",
                action="STAFF_UPDATED",
                action_type="UPDATE",
                entity_id=str(user.id),
                new_value={"updates": updates_made, "status": user.status},
                details=f"Staff {user.name} details updated: {', '.join(updates_made)}"
            )
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
        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=actor_id,
            role=None,
            module_name="HR_PAYROLL",
            action="STAFF_PASSWORD_RESET",
            action_type="UPDATE",
            entity_id=str(user.id),
            details=f"Staff {user.name} password reset by manager."
        )
        
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def delete_staff(db: AsyncSession, staff_id: UUID, temple_id: UUID, actor_id: UUID) -> dict:
        result = await db.execute(
            select(User).filter(User.id == staff_id, User.temple_id == temple_id)
        )
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="Staff not found")

        # Soft delete
        user.deleted_at = datetime.now(timezone.utc)
        user.status = "TERMINATED"
        user.is_active = False

        # Append to audit trail
        current_audit = list(user.audit_trail) if user.audit_trail else []
        current_audit.append({
            "event": "Terminated",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "notes": "Staff member was released/terminated from the directory."
        })
        user.audit_trail = current_audit
        flag_modified(user, "audit_trail")

        # Audit log
        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=actor_id,
            role=None,
            module_name="HR_PAYROLL",
            action="STAFF_DELETED",
            action_type="DELETE",
            entity_id=str(user.id),
            details=f"Staff {user.name} released from directory."
        )
        
        await db.commit()
        return {"status": "success", "message": f"Staff {user.name} released successfully."}

    @staticmethod
    async def get_staff_counts(db: AsyncSession, temple_id: UUID) -> dict:
        stmt = select(User.status, User.availability_status, func.count(User.id)).filter(
            User.temple_id == temple_id, 
            User.role == "STAFF",
            User.deleted_at.is_(None)
        ).group_by(User.status, User.availability_status)
        result = await db.execute(stmt)
        rows = result.all()
        
        total = 0
        active = 0
        suspended = 0
        on_leave = 0
        
        for status, avail, count in rows:
            total += count
            if status == "ACTIVE":
                active += count
                if avail == "ON_LEAVE":
                    on_leave += count
            elif status == "SUSPENDED":
                suspended += count
                
        return {
            "total": total,
            "active": active,
            "suspended": suspended,
            "on_leave": on_leave
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
        await AuditService.log_action(
            db=db,
            temple_id=user.temple_id,
            user_id=user.id,
            role=None,
            module_name="AUTH",
            action="PASSWORD_CHANGED_FIRST_LOGIN",
            action_type="UPDATE",
            entity_id=str(user.id),
            details="User completed mandatory password reset on first login."
        )
        
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
            ("button", "settings:edit", "Edit Temple Profile Settings"),
            ("tab", "staff:manage_roles", "Manage Staff Roles & Permissions"),
            ("tab", "staff:manage_employees", "Manage Staff Accounts"),
            ("tab", "offerings:view", "View Offerings Module"),
            ("tab", "communication:view", "View Communication Module"),
            ("button", "communication:manage", "Manage Announcements and Activities"),
            ("tab", "activity-logs:view", "View Activity Logs"),
            ("tab", "workflows:view", "View Workflows Dashboard"),
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
