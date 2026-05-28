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
        user_perms = await RBACService.get_user_permissions(db, user_id, temple_id)
        for p in user_perms:
            if p["resource_key"] == resource_key:
                if required_access == "full" and p["access_level"] != "full":
                    return False
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

    # --- Permissions -----------------------------------------------------

    @staticmethod
    async def list_permissions(db: AsyncSession, temple_id: str) -> List[Permission]:
        result = await db.execute(
            select(Permission).filter(Permission.temple_id == UUID(temple_id)).order_by(Permission.resource_key)
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
    async def assign_user_role(db: AsyncSession, temple_id: str, assignment: UserRoleCreate) -> UserRole:
        ur = UserRole(
            user_id=assignment.user_id,
            role_id=assignment.role_id,
            temple_id=UUID(temple_id),
        )
        db.add(ur)
        await db.commit()
        await db.refresh(ur)
        return ur

    @staticmethod
    async def remove_user_role(db: AsyncSession, temple_id: str, user_role_id: str) -> None:
        result = await db.execute(
            select(UserRole).filter(UserRole.id == UUID(user_role_id), UserRole.temple_id == UUID(temple_id))
        )
        ur = result.scalars().first()
        if not ur:
            raise HTTPException(status_code=404, detail="UserRole not found")
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
