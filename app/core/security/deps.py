from fastapi import Depends, HTTPException, status, Request
import logging
logger = logging.getLogger(__name__)
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timezone # Added for iat check
from app.core.config import settings
from app.core.database import get_db
from app.schemas.domain import TokenData
from sqlalchemy import inspect

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")

async def get_current_user(request: Request, token: str = Depends(oauth2_scheme)) -> TokenData:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.ALGORITHM])
        token_data = TokenData(
            sub=payload.get("sub"),
            temple_id=payload.get("temple_id"),
            role=payload.get("role"),
            username=payload.get("username", ""),
            security_version=payload.get("security_version"),
            iat=payload.get("iat")
        )
    except (JWTError, ValidationError):
        # We can't easily distinguish expired from invalid here without more complex logic, 
        # but the standard detail "Token invalid or expired" is correct.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session has expired or is invalid. Please login again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Phase 2: Advanced Security Hardening
    if token_data.temple_id:
        db_gen = get_db()
        db = await anext(db_gen)
        try:
            from app.models.domain import Temple
            from app.services.tenant_policy import TenantPolicy, OperationalCapability
            
            temple_uuid = UUID(token_data.temple_id)
            result = await db.execute(select(Temple).filter(Temple.id == temple_uuid))
            temple = result.scalars().first()
            
            if not temple:
                raise HTTPException(status_code=404, detail="Temple context invalid")

            # 1. Security Version Check
            if token_data.security_version is not None:
                if temple.security_version > token_data.security_version:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Session invalidated by administrative action. Please login again.",
                    )

            # 2. Issued-At (iat) Validation
            if token_data.iat is not None and temple.last_security_event_at:
                # Convert iat (unix timestamp) to datetime
                iat_dt = datetime.fromtimestamp(token_data.iat, tz=timezone.utc)
                if iat_dt < temple.last_security_event_at:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Session expired due to security update. Please login again.",
                    )

            # 3. Operational State Policy Enforcement (CAN_LOGIN)
            await TenantPolicy.enforce(
                db=db,
                temple_id=temple_uuid,
                capability=OperationalCapability.CAN_LOGIN,
                user_role=token_data.role
            )
            
            # 4. Force Password Change Enforcement (Phase 5)
            if token_data.force_password_change:
                allowed_paths = [
                    f"{settings.API_V1_STR}/auth/reset-password-force",
                    f"{settings.API_V1_STR}/auth/logout"
                ]
                if request.url.path not in allowed_paths:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Password reset required before accessing this resource."
                    )
            
        finally:
            await db.close()

    return token_data

async def get_current_active_admin(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    if current_user.role.upper().replace("_", "") != "SUPERADMIN" and current_user.role.upper() != "ADMIN":
        raise HTTPException(status_code=400, detail="Not enough permissions")
    return current_user

async def get_current_superadmin(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    """Only allows authenticated SUPERADMIN users."""
    if current_user.role.upper().replace("_", "") != "SUPERADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="SuperAdmin access required"
        )
    return current_user

async def get_current_devotee(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    if current_user.role != "DEVOTEE":
        raise HTTPException(status_code=403, detail="Devotee access required")
    return current_user


async def get_current_temple_manager(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    """Only allows TEMPLE_MANAGER, ADMIN, or SUPERADMIN users."""
    if current_user.role.upper().replace("_", "") != "SUPERADMIN" and current_user.role.upper() not in ("TEMPLE_MANAGER", "ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Temple Manager access required"
        )
    return current_user


async def get_current_staff(current_user: TokenData = Depends(get_current_user)) -> TokenData:
    """Only allows STAFF, TEMPLE_MANAGER, ADMIN, or SUPERADMIN users."""
    if current_user.role.upper().replace("_", "") != "SUPERADMIN" and current_user.role.upper() not in ("STAFF", "TEMPLE_MANAGER", "ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Staff access required"
        )
    return current_user


async def get_accessible_temple_ids(
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Optional[List[UUID]]:
    """
    Return list of temple IDs accessible to the current user.
    Returns None for SUPERADMIN (= access to all temples).
    Returns a list of UUIDs for other roles (filtered by user_temples mapping).
    """
    if current_user.role.upper().replace("_", "") == "SUPERADMIN":
        return None  # None signals "access all"

    from app.models.domain import UserTemple

    user_uuid = UUID(current_user.sub) if current_user.sub else None
    if not user_uuid:
        return []

    result = await db.execute(
        select(UserTemple.temple_id).filter(UserTemple.user_id == user_uuid)
    )
    temple_ids = [row[0] for row in result.all()]

    # If user has a temple_id in their JWT but it's not in mapping,
    # still include it (backward compat for direct temple_id assignment)
    if current_user.temple_id:
        try:
            jwt_tid = UUID(current_user.temple_id)
            if jwt_tid not in temple_ids:
                temple_ids.append(jwt_tid)
        except (ValueError, TypeError):
            pass

    return temple_ids

async def get_current_temple_id(
    current_user: TokenData = Depends(get_current_user)
) -> str:
    """Strictly enforces that a temple_id is present in the token/session."""
    if not current_user.temple_id:
        raise HTTPException(
            status_code=400, 
            detail="Temple context required. Please select a temple."
        )
    return current_user.temple_id


def require_permission(resource_key: str, required_access: str = 'read'):
    """Existing tenant-scoped permission guard (unchanged)."""
    async def permission_checker(
        current_user: TokenData = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
        temple_id: str = Depends(get_current_temple_id)
    ):
        if current_user.role.upper().replace("_", "") in ("SUPERADMIN", "TEMPLEMANAGER", "ADMIN"):
            return current_user
        
        # Phase 7: Block pending users from operational permissions
        if current_user.user_status == "PENDING_APPROVAL":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is awaiting manager approval. Access to operational modules is restricted."
            )

        user_uuid = UUID(current_user.sub)
        temple_uuid = UUID(temple_id)
        
        from app.modules.auth.services.rbac_service import RBACService
        has_perm = await RBACService.has_permission(db, user_uuid, temple_uuid, resource_key, required_access)
        if not has_perm:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied for {resource_key} with access {required_access}"
            )
        return current_user

    return permission_checker


# ═══════════════════════════════════════════════════════════════════════
# NEW: System-Level Permission Guard
# ═══════════════════════════════════════════════════════════════════════

def require_system_permission(permission_key: str):
    """
    FastAPI dependency that enforces a system-level permission.

    Uses system_role_id as the single source of truth.
    Replaces hardcoded role string checks like:
        if current_user.role == "SUPERADMIN"

    Usage:
        @router.post("/admin/approve-temple/{id}")
        async def approve(
            current_user: TokenData = Depends(require_system_permission("APPROVE_TEMPLE")),
            ...
        ):
    """
    async def checker(
        current_user: TokenData = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> TokenData:
        # Phase 7: Block pending users from system permissions
        if current_user.user_status == "PENDING_APPROVAL":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is awaiting manager approval. Administrative access is restricted."
            )

        from app.services.permission_service import PermissionService
        user_uuid = UUID(current_user.sub)
        has_perm = await PermissionService.has_permission(db, user_uuid, permission_key)
        
        logger.info(
            "AUDIT: RBAC Check: user_id=%s, role=%s, permission=%s, allowed=%s",
            user_uuid, current_user.role, permission_key, has_perm
        )

        if not has_perm:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission_key}",
            )
        return current_user

    return checker


# ═══════════════════════════════════════════════════════════════════════
# NEW: Tenant Isolation Filter (Fix #4)
# ═══════════════════════════════════════════════════════════════════════

def apply_tenant_filter(query, current_user: TokenData, model):
    """
    Centralized tenant isolation enforcement.

    Applies WHERE model.temple_id = current_user.temple_id for all
    non-SUPERADMIN users. SUPERADMIN bypasses the filter.

    Usage in services:
        query = select(Employee).filter(Employee.is_active == True)
        query = apply_tenant_filter(query, current_user, Employee)
        result = await db.execute(query)
    """
    if current_user.role.upper().replace("_", "") == "SUPERADMIN":
        return query  # SUPERADMIN bypasses tenant filter

    if not current_user.temple_id:
        raise HTTPException(
            status_code=400,
            detail="Temple context required for this operation."
        )

    temple_uuid = UUID(current_user.temple_id)
    return query.filter(model.temple_id == temple_uuid)


def apply_soft_delete_filter(query, model):
    """
    Automatically filters out records marked as deleted (is_active=False).
    """
    if hasattr(model, "is_active"):
        return query.filter(model.is_active == True)
    return query
