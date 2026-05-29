from pydantic import BaseModel, ConfigDict, UUID4
from typing import Optional, List
from datetime import datetime


# ---------- Role ----------
class RoleCreate(BaseModel):
    name: str
    description: Optional[str] = ""


class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class RoleClone(BaseModel):
    name: str
    description: Optional[str] = None


class RoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    name: str
    description: Optional[str] = ""
    is_active: bool
    created_at: datetime


# ---------- Permission ----------
class PermissionCreate(BaseModel):
    resource_type: str   # 'module' | 'tab' | 'button' | 'feature'
    resource_key: str
    description: Optional[str] = ""


class PermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: Optional[UUID4] = None
    resource_type: str
    resource_key: str
    description: Optional[str] = ""
    created_at: datetime


# ---------- RolePermission ----------
class RolePermissionCreate(BaseModel):
    permission_id: UUID4
    access_level: Optional[str] = "full"  # 'full' | 'read' | 'none'


class RolePermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    role_id: UUID4
    permission_id: UUID4
    access_level: str
    created_at: datetime


# ---------- UserRole ----------
class UserRoleCreate(BaseModel):
    user_id: UUID4
    role_id: UUID4


class UserRoleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    user_id: UUID4
    role_id: UUID4
    temple_id: UUID4
    created_at: datetime


# ---------- Bulk Permission Assignment ----------
class BulkPermissionAssign(BaseModel):
    """Assign multiple permissions to a role at once."""
    role_id: UUID4
    permissions: List[RolePermissionCreate]


# ---------- RBAC Config Response (for frontend) ----------
class PermissionEntry(BaseModel):
    resource_type: str
    resource_key: str
    access_level: str


class RolePermissionsResponse(BaseModel):
    """Full permission set for a role — used by frontend to render the matrix."""
    role_id: UUID4
    role_name: str
    permissions: List[PermissionEntry]
