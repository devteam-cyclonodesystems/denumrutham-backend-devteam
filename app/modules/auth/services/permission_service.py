"""
Permission Service — System-level permission checking with in-memory caching.

Uses system_role_id on the User model as the SINGLE source of truth for
platform-level permissions (not the legacy User.role string column).

Caching strategy (Fix #3):
  Phase 1: TTL-based in-memory dict (current)
  Phase 2: Redis-backed cache (future)
"""
import logging
import time
from typing import List, Optional, Set
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload

from app.models.domain import User
from app.models.system_rbac import SystemRole, SystemPermission, SystemRolePermission
from app.core.exceptions import ForbiddenError

logger = logging.getLogger(__name__)

# ── In-memory permission cache (Fix #3) ────────────────────────────────
# Structure: { user_id_str: (expiry_timestamp, set_of_permission_keys) }
_PERMISSION_CACHE: dict[str, tuple[float, Set[str]]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


def _cache_get(user_id: UUID) -> Optional[Set[str]]:
    """Return cached permission set if still valid, else None."""
    key = str(user_id)
    entry = _PERMISSION_CACHE.get(key)
    if entry and entry[0] > time.time():
        return entry[1]
    # Expired or missing — evict
    _PERMISSION_CACHE.pop(key, None)
    return None


def _cache_set(user_id: UUID, perms: Set[str]):
    """Store permission set with TTL."""
    _PERMISSION_CACHE[str(user_id)] = (time.time() + _CACHE_TTL_SECONDS, perms)


def invalidate_user_cache(user_id: UUID):
    """Evict a user's cached permissions (call after role changes)."""
    _PERMISSION_CACHE.pop(str(user_id), None)


def invalidate_all_cache():
    """Clear entire permission cache (call after seed/bulk changes)."""
    _PERMISSION_CACHE.clear()


class PermissionService:
    """System-level permission evaluation engine."""

    # ── Sensitive permissions (Fix #6) ────────────────────────────────
    # These can ONLY be assigned to SUPER_ADMIN system role.
    SENSITIVE_PERMISSIONS = frozenset({
        "APPROVE_TEMPLE",
        "REJECT_TEMPLE",
        "MANAGE_ROLES",
        "MANAGE_USERS",
        "DELETE_TEMPLE",
        "VIEW_ADMIN_DASHBOARD",
    })

    @staticmethod
    async def _load_permissions(db: AsyncSession, user_id: UUID) -> Set[str]:
        """
        Load all system-level permission keys for a user from DB.

        Uses system_role_id as single source of truth (Fix #1).
        Falls back to User.role string ONLY if system_role_id is NULL
        (for un-backfilled users during migration transition).
        """
        result = await db.execute(
            select(User)
            .options(
                joinedload(User.system_role)
                .joinedload(SystemRole.permissions)
                .joinedload(SystemRolePermission.permission)
            )
            .filter(User.id == user_id, User.is_active == True)
        )
        user = result.unique().scalars().first()
        if not user:
            return set()

        # ── System Role Mapping ─────────────────────────────────────────────
        # Primary authority for platform-level permissions.
        if user.system_role:
            if user.system_role.name == "SUPER_ADMIN":
                return {"__ALL__"}

            perm_keys = set()
            for rp in user.system_role.permissions:
                if rp.permission:
                    perm_keys.add(rp.permission.key)
            return perm_keys

        # Migration safe-check: if user has no system_role assigned yet
        if user.role in ("SUPERADMIN", "SUPER_ADMIN"):
            # During migration, we may still see these. But seeding handles the backfill.
            pass

        # No system role assigned — no system-level permissions
        logger.warning(
            "User %s has no system_role_id assigned (role=%s). "
            "Run seed_system_rbac to backfill.",
            user_id, user.role,
        )
        return set()

    @staticmethod
    async def has_permission(
        db: AsyncSession, user_id: UUID, permission_key: str
    ) -> bool:
        """
        Check if a user has a specific system-level permission.

        Returns True if:
        - User is SUPER_ADMIN (bypass all checks)
        - User's system role includes the requested permission
        """
        # Check cache first
        cached = _cache_get(user_id)
        if cached is not None:
            return "__ALL__" in cached or permission_key in cached

        # Load from DB and cache
        perms = await PermissionService._load_permissions(db, user_id)
        _cache_set(user_id, perms)

        allowed = "__ALL__" in perms or permission_key in perms
        logger.info(
            "Permission check: user=%s, permission=%s, result=%s",
            user_id, permission_key, allowed
        )
        return allowed

    @staticmethod
    async def require_permission(
        db: AsyncSession, user_id: UUID, permission_key: str
    ):
        """Raise ForbiddenError if user lacks the specified permission."""
        if not await PermissionService.has_permission(db, user_id, permission_key):
            raise ForbiddenError(f"Permission denied: {permission_key}")

    @staticmethod
    async def get_user_permissions(
        db: AsyncSession, user_id: UUID
    ) -> List[str]:
        """Return all system-level permission keys for a user."""
        cached = _cache_get(user_id)
        if cached is not None:
            if "__ALL__" in cached:
                # Resolve ALL to actual permission keys
                result = await db.execute(select(SystemPermission.key))
                return [row[0] for row in result.all()]
            return list(cached)

        perms = await PermissionService._load_permissions(db, user_id)
        _cache_set(user_id, perms)

        if "__ALL__" in perms:
            result = await db.execute(select(SystemPermission.key))
            return [row[0] for row in result.all()]

        return list(perms)

    @staticmethod
    async def validate_permission_assignment(
        db: AsyncSession, role_name: str, permission_key: str
    ):
        """
        Prevent sensitive permissions from being assigned to non-SUPER_ADMIN roles.
        (Fix #6 — Role escalation protection)
        """
        if permission_key in PermissionService.SENSITIVE_PERMISSIONS:
            if role_name != "SUPER_ADMIN":
                raise ForbiddenError(
                    f"Permission '{permission_key}' can only be assigned to SUPER_ADMIN"
                )
