"""
Temple RBAC Guards — Real permission enforcement for temple mutations.

Phase 3: Activated guards. No longer permissive placeholders.

Roles:
  - SUPER_ADMIN → full access to all temples
  - TEMPLE_ADMIN / TEMPLE_MANAGER → modify own temple only (via UserTemple mapping)
  - DEVOTEE → read-only, all mutation guards return False
  - STAFF → cannot modify temples

Guards are async because TEMPLE_ADMIN ownership requires a DB lookup.
"""
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger(__name__)


# ── Role Constants ────────────────────────────────────────────────────
class TempleRole:
    SUPER_ADMIN = "SUPER_ADMIN"
    TEMPLE_ADMIN = "TEMPLE_ADMIN"
    TEMPLE_MANAGER = "TEMPLE_MANAGER"
    DEVOTEE = "DEVOTEE"
    STAFF = "STAFF"

    # All role strings that are treated as SUPER_ADMIN
    SUPERADMIN_ALIASES = {"SUPER_ADMIN", "SUPERADMIN"}

    # Roles allowed to own/manage a temple
    TEMPLE_OWNER_ROLES = {"TEMPLE_ADMIN", "TEMPLE_MANAGER", "ADMIN"}


def _is_superadmin(role: Optional[str]) -> bool:
    """Check if a role string represents a SUPER_ADMIN."""
    if not role:
        return False
    normalized = role.upper().replace("_", "")
    return normalized == "SUPERADMIN"


def _is_devotee(role: Optional[str]) -> bool:
    """Check if a role string represents a DEVOTEE."""
    if not role:
        return False
    return role.upper() == "DEVOTEE"


async def _user_owns_temple(
    db: AsyncSession, user_id: UUID, temple_id: UUID
) -> bool:
    """
    Check if a user has an active UserTemple mapping for the given temple.
    This is the ownership proof for TEMPLE_ADMIN / TEMPLE_MANAGER roles.
    """
    from app.models.domain import UserTemple

    result = await db.execute(
        select(UserTemple).filter(
            UserTemple.user_id == user_id,
            UserTemple.temple_id == temple_id,
            UserTemple.is_active == True,
        )
    )
    return result.scalars().first() is not None


# ── Guard Functions (Enforced) ────────────────────────────────────────

async def can_modify_temple(
    db: AsyncSession,
    user_id: Optional[UUID],
    user_role: Optional[str],
    temple_id: Optional[UUID],
) -> bool:
    """
    Check if a user can modify a temple's core data.

    Rules:
      - SUPER_ADMIN → always allowed
      - TEMPLE_ADMIN / TEMPLE_MANAGER → only if they own the temple
      - DEVOTEE / STAFF / None → never allowed

    Args:
        db: Database session (required for ownership lookup)
        user_id: The acting user's UUID
        user_role: The user's system role string
        temple_id: The target temple UUID
    """
    # SUPER_ADMIN: full access
    if _is_superadmin(user_role):
        logger.debug(
            "RBAC: can_modify_temple(user=%s, role=%s, temple=%s) -> True (SUPER_ADMIN)",
            user_id, user_role, temple_id,
        )
        return True

    # DEVOTEE: read-only, never allowed
    if _is_devotee(user_role):
        logger.info(
            "RBAC DENIED: can_modify_temple(user=%s, role=%s, temple=%s) -> False (DEVOTEE)",
            user_id, user_role, temple_id,
        )
        return False

    # No user_id or temple_id → deny
    if not user_id or not temple_id:
        logger.info(
            "RBAC DENIED: can_modify_temple -> False (missing user_id or temple_id)"
        )
        return False

    # TEMPLE_ADMIN / TEMPLE_MANAGER: check ownership
    if user_role and user_role.upper() in TempleRole.TEMPLE_OWNER_ROLES:
        owns = await _user_owns_temple(db, user_id, temple_id)
        logger.debug(
            "RBAC: can_modify_temple(user=%s, role=%s, temple=%s) -> %s (ownership check)",
            user_id, user_role, temple_id, owns,
        )
        return owns

    # All other roles: deny
    logger.info(
        "RBAC DENIED: can_modify_temple(user=%s, role=%s, temple=%s) -> False (insufficient role)",
        user_id, user_role, temple_id,
    )
    return False


async def can_change_status(
    db: AsyncSession,
    user_id: Optional[UUID],
    user_role: Optional[str],
    temple_id: Optional[UUID],
) -> bool:
    """
    Check if a user can change a temple's approval status.

    Rules:
      - SUPER_ADMIN → always allowed
      - All other roles → never allowed (status changes are admin-only)

    Args:
        db: Database session
        user_id: The acting user's UUID
        user_role: The user's system role string
        temple_id: The target temple UUID
    """
    if _is_superadmin(user_role):
        logger.debug(
            "RBAC: can_change_status(user=%s, role=%s, temple=%s) -> True (SUPER_ADMIN)",
            user_id, user_role, temple_id,
        )
        return True

    logger.info(
        "RBAC DENIED: can_change_status(user=%s, role=%s, temple=%s) -> False",
        user_id, user_role, temple_id,
    )
    return False


async def can_delete_temple(
    db: AsyncSession,
    user_id: Optional[UUID],
    user_role: Optional[str],
    temple_id: Optional[UUID],
) -> bool:
    """
    Check if a user can soft-delete a temple.

    Rules:
      - SUPER_ADMIN → always allowed
      - All other roles → never allowed (deletion is admin-only)

    Args:
        db: Database session
        user_id: The acting user's UUID
        user_role: The user's system role string
        temple_id: The target temple UUID
    """
    if _is_superadmin(user_role):
        logger.debug(
            "RBAC: can_delete_temple(user=%s, role=%s, temple=%s) -> True (SUPER_ADMIN)",
            user_id, user_role, temple_id,
        )
        return True

    logger.info(
        "RBAC DENIED: can_delete_temple(user=%s, role=%s, temple=%s) -> False",
        user_id, user_role, temple_id,
    )
    return False
