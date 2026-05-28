"""
RBAC API Endpoints
Roles, Permissions, Role-Permission mappings, User-Role assignments.
All endpoints require ADMIN role.
"""
from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_active_admin, get_current_user
from app.schemas.domain import TokenData
from app.schemas.rbac import (
    RoleCreate, RoleUpdate, RoleResponse,
    PermissionCreate, PermissionResponse,
    RolePermissionCreate, RolePermissionResponse,
    UserRoleCreate, UserRoleResponse,
    RolePermissionsResponse, PermissionEntry,
)
from app.services.rbac_service import RbacService

router = APIRouter()

# ─── Roles ─────────────────────────────────────────────

@router.get("/roles", response_model=List[RoleResponse])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_active_admin),
):
    return await RbacService.list_roles(db, current_user.temple_id)


@router.post("/roles", response_model=RoleResponse, status_code=201)
async def create_role(
    role_in: RoleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_active_admin),
):
    return await RbacService.create_role(db, current_user.temple_id, role_in)


@router.put("/roles/{role_id}", response_model=RoleResponse)
async def update_role(
    role_id: str,
    role_in: RoleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_active_admin),
):
    return await RbacService.update_role(db, current_user.temple_id, role_id, role_in)


@router.delete("/roles/{role_id}", status_code=204)
async def delete_role(
    role_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_active_admin),
):
    await RbacService.delete_role(db, current_user.temple_id, role_id)


# ─── Permissions ────────────────────────────────────────

@router.get("/permissions", response_model=List[PermissionResponse])
async def list_permissions(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_active_admin),
):
    return await RbacService.list_permissions(db, current_user.temple_id)


@router.post("/permissions", response_model=PermissionResponse, status_code=201)
async def create_permission(
    perm_in: PermissionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_active_admin),
):
    return await RbacService.create_permission(db, current_user.temple_id, perm_in)


# ─── Role-Permission Mapping ───────────────────────────

@router.get("/roles/{role_id}/permissions", response_model=RolePermissionsResponse)
async def get_role_permissions(
    role_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_active_admin),
):
    role, entries = await RbacService.get_role_permissions(db, current_user.temple_id, role_id)
    return RolePermissionsResponse(role_id=role.id, role_name=role.name, permissions=entries)


@router.post("/roles/{role_id}/permissions", response_model=List[RolePermissionResponse], status_code=201)
async def assign_permissions_to_role(
    role_id: str,
    assignments: List[RolePermissionCreate],
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_active_admin),
):
    return await RbacService.assign_permissions_to_role(db, current_user.temple_id, role_id, assignments)


# ─── User-Role Assignment ──────────────────────────────

@router.get("/user-roles", response_model=List[UserRoleResponse])
async def list_user_roles(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_active_admin),
):
    return await RbacService.list_user_roles(db, current_user.temple_id)


@router.post("/user-roles", response_model=UserRoleResponse, status_code=201)
async def assign_user_role(
    assignment: UserRoleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_active_admin),
):
    return await RbacService.assign_user_role(db, current_user.temple_id, assignment)


@router.delete("/user-roles/{user_role_id}", status_code=204)
async def remove_user_role(
    user_role_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_active_admin),
):
    await RbacService.remove_user_role(db, current_user.temple_id, user_role_id)


# ─── Current User Permissions (used by frontend) ──────

@router.get("/my-permissions/", response_model=List[PermissionEntry])
async def get_my_permissions(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """Return the merged permission set for the current user's roles."""
    return await RbacService.get_my_permissions(db, current_user.sub, current_user.role)
