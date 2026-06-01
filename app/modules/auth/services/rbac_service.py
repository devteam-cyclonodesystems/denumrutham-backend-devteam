"""
RBAC Service Layer — contains both the original RbacService (full CRUD for
the admin RBAC management UI) and the hardened RBACService (permission
checking used by the require_permission guard).
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from uuid import UUID
from typing import List, Optional, Tuple
from fastapi import HTTPException

from app.models.rbac import UserRole, Role, RolePermission, Permission
from app.schemas.rbac import (
    RoleCreate, RoleUpdate,
    PermissionCreate,
    RolePermissionCreate,
    UserRoleCreate,
    PermissionEntry,
)


# ═══════════════════════════════════════════════════════════════════════
# RBACService — Permission checker (used by require_permission guard)
# ═══════════════════════════════════════════════════════════════════════

class RBACService:
    """Lightweight permission evaluation for the middleware guard."""

    @staticmethod
    async def get_user_permissions(db: AsyncSession, user_id: UUID, temple_id: UUID) -> List[dict]:
        """Returns all permissions for a user within a specific temple."""
        stmt = (
            select(RolePermission)
            .join(Role, Role.id == RolePermission.role_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .options(joinedload(RolePermission.permission))
            .filter(UserRole.user_id == user_id, UserRole.temple_id == temple_id, Role.is_active == True)
        )
        result = await db.execute(stmt)
        role_permissions = result.scalars().all()

        permissions_list = []
        for rp in role_permissions:
            if rp.access_level != "none":
                permissions_list.append({
                    "resource_type": rp.permission.resource_type,
                    "resource_key": rp.permission.resource_key,
                    "access_level": rp.access_level,
                })
        return permissions_list

    @staticmethod
    async def has_permission(
        db: AsyncSession, user_id: UUID, temple_id: UUID,
        resource_key: str, required_access: str = "read",
    ) -> bool:
        from app.models.domain import User
        user_res = await db.execute(select(User).filter(User.id == user_id))
        user = user_res.scalar_one_or_none()
        if user and user.role in ("SUPERADMIN", "SUPER_ADMIN"):
            return True

        user_perms = await RBACService.get_user_permissions(db, user_id, temple_id)
        
        target_keys = []
        if ":" in resource_key:
            target_keys.append(resource_key)
        else:
            if required_access == "execute":
                target_keys.extend([f"{resource_key}:start_ritual", f"{resource_key}:complete_ritual", f"{resource_key}:execute"])
            elif required_access in ("read", "view"):
                target_keys.extend([f"{resource_key}:view", f"{resource_key}:view_queue", f"{resource_key}:view_stock", f"{resource_key}:view_bookings"])
            elif required_access == "create":
                target_keys.extend([f"{resource_key}:create", f"{resource_key}:create_booking", f"{resource_key}:create_sale", f"{resource_key}:receive_donation"])
            elif required_access == "edit":
                target_keys.extend([f"{resource_key}:edit", f"{resource_key}:edit_booking", f"{resource_key}:adjust_stock", f"{resource_key}:modify_donation"])
            elif required_access == "delete":
                target_keys.extend([f"{resource_key}:delete", f"{resource_key}:cancel_booking"])
            elif required_access == "approve":
                target_keys.extend([f"{resource_key}:approve", f"{resource_key}:approve_requests", f"{resource_key}:approve_booking", f"{resource_key}:approve_corrections"])
            else:
                target_keys.append(f"{resource_key}:{required_access}")
            
            target_keys.append(f"{resource_key}:all")
            target_keys.append(resource_key)

        for p in user_perms:
            r_key = p["resource_key"]
            if r_key in ("all", "all:all"):
                return True
            if r_key in target_keys:
                return True
        return False


# ═══════════════════════════════════════════════════════════════════════
# RbacService — Full CRUD service (used by /rbac admin routes)
# ═══════════════════════════════════════════════════════════════════════

class RbacService:
    """Admin-facing RBAC management — roles, permissions, assignments."""

    # --- Roles -----------------------------------------------------------

    @staticmethod
    async def list_roles(db: AsyncSession, temple_id: str) -> List[Role]:
        result = await db.execute(
            select(Role).filter(Role.temple_id == UUID(temple_id)).order_by(Role.name)
        )
        return result.scalars().all()

    @staticmethod
    async def create_role(db: AsyncSession, temple_id: str, role_in: RoleCreate) -> Role:
        role = Role(temple_id=UUID(temple_id), name=role_in.name, description=role_in.description or "")
        db.add(role)
        await db.commit()
        await db.refresh(role)
        return role

    @staticmethod
    async def update_role(db: AsyncSession, temple_id: str, role_id: str, role_in: RoleUpdate) -> Role:
        result = await db.execute(
            select(Role).filter(Role.id == UUID(role_id), Role.temple_id == UUID(temple_id))
        )
        role = result.scalars().first()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        if role_in.name is not None:
            role.name = role_in.name
        if role_in.description is not None:
            role.description = role_in.description
        if role_in.is_active is not None:
            role.is_active = role_in.is_active
        await db.commit()
        await db.refresh(role)
        return role

    @staticmethod
    async def delete_role(db: AsyncSession, temple_id: str, role_id: str) -> None:
        result = await db.execute(
            select(Role).filter(Role.id == UUID(role_id), Role.temple_id == UUID(temple_id))
        )
        role = result.scalars().first()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")
        await db.delete(role)
        await db.commit()

    @staticmethod
    async def clone_role(db: AsyncSession, temple_id: str, role_id: str, new_name: str, new_description: Optional[str] = None) -> Role:
        # 1. Fetch source role
        result = await db.execute(
            select(Role).filter(Role.id == UUID(role_id), Role.temple_id == UUID(temple_id))
        )
        source_role = result.scalars().first()
        if not source_role:
            raise HTTPException(status_code=404, detail="Source role not found")

        # 2. Check if new role name is already taken in this temple
        existing_result = await db.execute(
            select(Role).filter(Role.temple_id == UUID(temple_id), Role.name == new_name)
        )
        if existing_result.scalars().first():
            raise HTTPException(status_code=400, detail=f"Role with name '{new_name}' already exists")

        # 3. Create cloned role
        cloned_role = Role(
            temple_id=UUID(temple_id),
            name=new_name,
            description=new_description if new_description is not None else f"Cloned from {source_role.name}",
            is_active=source_role.is_active
        )
        db.add(cloned_role)
        await db.flush() # flush to get cloned_role.id

        # 4. Fetch source role permissions
        rp_result = await db.execute(
            select(RolePermission).filter(RolePermission.role_id == source_role.id)
        )
        source_rps = rp_result.scalars().all()

        # 5. Map permissions to cloned role
        for rp in source_rps:
            cloned_rp = RolePermission(
                role_id=cloned_role.id,
                permission_id=rp.permission_id,
                access_level=rp.access_level
            )
            db.add(cloned_rp)

        await db.commit()
        await db.refresh(cloned_role)
        return cloned_role

    # --- Permissions -----------------------------------------------------

    @staticmethod
    async def list_permissions(db: AsyncSession, temple_id: str) -> List[Permission]:
        from sqlalchemy import or_
        result = await db.execute(
            select(Permission).filter(
                or_(Permission.temple_id == None, Permission.temple_id == UUID(temple_id))
            ).order_by(Permission.resource_key)
        )
        return result.scalars().all()

    @staticmethod
    async def create_permission(db: AsyncSession, temple_id: str, perm_in: PermissionCreate) -> Permission:
        perm = Permission(
            temple_id=UUID(temple_id),
            resource_type=perm_in.resource_type,
            resource_key=perm_in.resource_key,
            description=perm_in.description or "",
        )
        db.add(perm)
        await db.commit()
        await db.refresh(perm)
        return perm

    # --- Role-Permission mapping ----------------------------------------

    @staticmethod
    async def get_role_permissions(
        db: AsyncSession, temple_id: str, role_id: str
    ) -> Tuple[Role, List[PermissionEntry]]:
        result = await db.execute(
            select(Role).filter(Role.id == UUID(role_id), Role.temple_id == UUID(temple_id))
        )
        role = result.scalars().first()
        if not role:
            raise HTTPException(status_code=404, detail="Role not found")

        rp_result = await db.execute(
            select(RolePermission)
            .options(joinedload(RolePermission.permission))
            .filter(RolePermission.role_id == role.id)
        )
        rps = rp_result.scalars().all()

        entries = [
            PermissionEntry(
                resource_type=rp.permission.resource_type,
                resource_key=rp.permission.resource_key,
                access_level=rp.access_level,
            )
            for rp in rps if rp.permission
        ]
        return role, entries

    @staticmethod
    async def assign_permissions_to_role(
        db: AsyncSession, temple_id: str, role_id: str, assignments: List[RolePermissionCreate]
    ) -> List[RolePermission]:
        result = await db.execute(
            select(Role).filter(Role.id == UUID(role_id), Role.temple_id == UUID(temple_id))
        )
        if not result.scalars().first():
            raise HTTPException(status_code=404, detail="Role not found")

        # Delete all existing permission assignments for this role first
        from sqlalchemy import delete
        await db.execute(
            delete(RolePermission).where(RolePermission.role_id == UUID(role_id))
        )

        created = []
        for a in assignments:
            rp = RolePermission(
                role_id=UUID(role_id),
                permission_id=a.permission_id,
                access_level=a.access_level or "full",
            )
            db.add(rp)
            created.append(rp)
        await db.commit()
        for rp in created:
            await db.refresh(rp)
        return created

    # --- User-Role assignment -------------------------------------------

    @staticmethod
    async def list_user_roles(db: AsyncSession, temple_id: str) -> List[UserRole]:
        result = await db.execute(
            select(UserRole).filter(UserRole.temple_id == UUID(temple_id))
        )
        return result.scalars().all()

    @staticmethod
    async def assign_user_role(
        db: AsyncSession,
        temple_id: str,
        assignment: UserRoleCreate,
        performer_id: Optional[str] = None,
        performer_role: Optional[str] = None
    ) -> UserRole:
        ur = UserRole(
            user_id=assignment.user_id,
            role_id=assignment.role_id,
            temple_id=UUID(temple_id),
        )
        db.add(ur)
        await db.flush()  # flush to populate ur.id

        from app.modules.audit.services.audit_service import AuditService
        p_uuid = UUID(performer_id) if performer_id else None
        await AuditService.log_action(
            db=db,
            temple_id=UUID(temple_id) if temple_id else None,
            user_id=p_uuid,
            role=performer_role,
            module_name="RBAC",
            action="ROLE_ASSIGNED",
            action_type="UPDATE",
            entity_id=str(ur.id),
            new_value={"user_id": str(assignment.user_id), "role_id": str(assignment.role_id)},
            details=f"Assigned role {assignment.role_id} to user {assignment.user_id}"
        )

        await db.commit()
        await db.refresh(ur)
        return ur

    @staticmethod
    async def remove_user_role(
        db: AsyncSession,
        temple_id: str,
        user_role_id: str,
        performer_id: Optional[str] = None,
        performer_role: Optional[str] = None
    ) -> None:
        result = await db.execute(
            select(UserRole).filter(UserRole.id == UUID(user_role_id), UserRole.temple_id == UUID(temple_id))
        )
        ur = result.scalars().first()
        if not ur:
            raise HTTPException(status_code=404, detail="UserRole not found")

        from app.modules.audit.services.audit_service import AuditService
        p_uuid = UUID(performer_id) if performer_id else None
        await AuditService.log_action(
            db=db,
            temple_id=UUID(temple_id) if temple_id else None,
            user_id=p_uuid,
            role=performer_role,
            module_name="RBAC",
            action="ROLE_REVOKED",
            action_type="UPDATE",
            entity_id=str(ur.id),
            old_value={"user_id": str(ur.user_id), "role_id": str(ur.role_id)},
            details=f"Revoked user-role assignment {user_role_id} (user {ur.user_id}, role {ur.role_id})"
        )

        await db.delete(ur)
        await db.commit()

    # --- Current-user merged permissions (frontend) ---------------------

    @staticmethod
    async def get_my_permissions(db: AsyncSession, sub: str, role: str) -> List[PermissionEntry]:
        """Return merged permissions for the calling user."""
        if role == "SUPERADMIN":
            return [PermissionEntry(resource_type="all", resource_key="all", access_level="full")]

        user_id = UUID(sub)
        # Collect across all temple roles
        result = await db.execute(
            select(RolePermission)
            .join(Role, Role.id == RolePermission.role_id)
            .join(UserRole, UserRole.role_id == Role.id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .options(joinedload(RolePermission.permission))
            .filter(UserRole.user_id == user_id, Role.is_active == True)
        )
        rps = result.scalars().all()
        entries = [
            PermissionEntry(
                resource_type=rp.permission.resource_type,
                resource_key=rp.permission.resource_key,
                access_level=rp.access_level,
            )
            for rp in rps if rp.permission
        ]
        return entries
