"""
Sync Engine — Server-side sync processing for hybrid offline mode.

Phase 4: Implements pull (server -> client) and push (client -> server)
with strict version-based conflict detection and server-wins resolution.

INVARIANTS:
  - All updates are atomic (SELECT FOR UPDATE + version increment)
  - Audit trail is preserved for every sync mutation
  - RBAC is validated per-operation
  - State machine transitions are enforced (status changes BLOCKED offline)
  - No auto-merge — server always wins on conflict
"""
import logging
from datetime import datetime, timezone
from uuid import UUID
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.domain import Temple, TempleProfile, utcnow
from app.services.temple_rbac import can_modify_temple
from app.services.audit_service import AuditService
from app.services.tenant_policy import TenantPolicy, OperationalCapability

logger = logging.getLogger("tms.sync_engine")

# Fields that are SAFE to update via offline sync
SAFE_SYNC_FIELDS = {
    "name", "location", "state", "address_line_1", "address_line_2",
    "district", "pincode", "contact_number", "alternate_contact",
    "email", "description",
}

# Fields that are BLOCKED from offline sync (require online operations)
BLOCKED_SYNC_FIELDS = {"status", "is_active", "deleted_at", "version", "updated_at"}


def _temple_to_dict(temple: Temple, profile: Optional[TempleProfile] = None) -> dict:
    """Serialize a temple + profile to a sync-safe dictionary."""
    return {
        "id": str(temple.id),
        "name": temple.name,
        "domain": temple.domain,
        "location": temple.location or "",
        "state": temple.state or "",
        "address_line_1": temple.address_line_1 or "",
        "address_line_2": temple.address_line_2 or "",
        "district": temple.district or "",
        "pincode": temple.pincode or "",
        "contact_number": temple.contact_number or "",
        "alternate_contact": temple.alternate_contact or "",
        "email": temple.email or "",
        "description": temple.description or "",
        "status": temple.status or "APPROVED",
        "is_active": temple.is_active,
        "version": temple.version or 1,
        "updated_at": temple.updated_at.isoformat() if temple.updated_at else None,
        "image_url": profile.image_url if profile else "",
    }


class SyncEngine:
    """Server-side sync engine for hybrid offline mode."""

    # ── PULL: Server -> Client ────────────────────────────────────────

    @staticmethod
    async def pull_changes(
        db: AsyncSession,
        since: datetime,
        limit: int = 100,
    ) -> dict:
        """
        Return all temple records updated after `since`.

        The client stores the returned `server_time` and uses it
        The client stores the returned `server_time` and uses it
        as `since` in the next pull request.
        """
        # Phase 5: Filter out temples that cannot sync based on operational state
        # Note: In a real multi-tenant setup, since would be scoped to one temple.
        # This implementation pulls all updated temples, so we must filter results.
        
        query = select(Temple).filter(Temple.updated_at > since)
        result = await db.execute(query)
        temples = result.scalars().all()

        items = []
        for temple in temples:
            # Check CAN_SYNC capability
            if await TenantPolicy.has_capability(db, temple.id, OperationalCapability.CAN_SYNC):
                profile_result = await db.execute(
                    select(TempleProfile).filter(TempleProfile.temple_id == temple.id)
                )
                profile = profile_result.scalars().first()
                items.append(_temple_to_dict(temple, profile))

        server_time = datetime.now(timezone.utc).isoformat()

        return {
            "temples": items,
            "count": len(items),
            "since": since.isoformat(),
            "server_time": server_time,
            "has_more": len(items) >= limit,
        }

    # ── PUSH: Client -> Server (batch) ────────────────────────────────

    @staticmethod
    async def push_changes(
        db: AsyncSession,
        updates: list,
        user_id: Optional[UUID] = None,
        user_role: Optional[str] = None,
    ) -> dict:
        """
        Process a batch of offline changes from the client.

        Each update is processed independently using savepoints.
        Failed items do NOT block successful ones.
        """
        results = []
        applied = 0
        conflicts = 0
        errors = 0

        for update in updates:
            item_id = update.id
            client_version = update.version
            changes = update.changes
            local_change_id = update.local_change_id

            try:
                result_item = await SyncEngine._process_single_update(
                    db=db,
                    temple_id_str=item_id,
                    client_version=client_version,
                    changes=changes,
                    user_id=user_id,
                    user_role=user_role,
                    local_change_id=local_change_id,
                )
                results.append(result_item)

                if result_item["status"] == "applied":
                    applied += 1
                elif result_item["status"] == "conflict":
                    conflicts += 1
                else:
                    errors += 1

            except Exception as e:
                logger.error(
                    "Sync push error for temple %s: %s",
                    item_id, str(e), exc_info=True,
                )
                results.append({
                    "id": item_id,
                    "status": "error",
                    "message": str(e),
                    "local_change_id": local_change_id,
                })
                errors += 1

        # Commit all successful updates
        if applied > 0:
            await db.commit()

        server_time = datetime.now(timezone.utc).isoformat()

        return {
            "results": results,
            "applied": applied,
            "conflicts": conflicts,
            "errors": errors,
            "server_time": server_time,
        }

    # ── Single update processor (savepoint-based) ─────────────────────

    @staticmethod
    async def _process_single_update(
        db: AsyncSession,
        temple_id_str: str,
        client_version: int,
        changes: dict,
        user_id: Optional[UUID],
        user_role: Optional[str],
        local_change_id: Optional[str],
    ) -> dict:
        """
        Process a single sync update using a savepoint for per-item safety.

        The caller's session already has an active transaction (from FastAPI's
        get_db dependency), so we use begin_nested() to create a savepoint.
        If this item fails, only the savepoint rolls back.
        """
        try:
            tid = UUID(temple_id_str)
        except ValueError:
            return {
                "id": temple_id_str,
                "status": "error",
                "message": "Invalid temple ID format",
                "local_change_id": local_change_id,
            }

        # ── Filter to safe fields only ────────────────────────────────
        blocked_fields = [f for f in changes if f in BLOCKED_SYNC_FIELDS]
        if blocked_fields:
            return {
                "id": temple_id_str,
                "status": "error",
                "message": f"Offline sync blocked for fields: {blocked_fields}. "
                           f"Status changes and deletes require online operation.",
                "local_change_id": local_change_id,
            }

        safe_changes = {k: v for k, v in changes.items() if k in SAFE_SYNC_FIELDS}
        if not safe_changes:
            return {
                "id": temple_id_str,
                "status": "error",
                "message": "No valid fields to update",
                "local_change_id": local_change_id,
            }

        # ── RBAC check ────────────────────────────────────────────────
        if not await can_modify_temple(db, user_id, user_role, tid):
            return {
                "id": temple_id_str,
                "status": "error",
                "message": "Not authorized to modify this temple",
                "local_change_id": local_change_id,
            }

        # ── Savepoint with row-level lock ─────────────────────────────
        async with db.begin_nested():
            result = await db.execute(
                select(Temple)
                .filter(Temple.id == tid)
                .with_for_update()
            )
            temple = result.scalars().first()
            
            if not temple:
                return {
                    "id": temple_id_str,
                    "status": "error",
                    "message": "Temple not found or permanently deleted",
                    "local_change_id": local_change_id,
                }

            # ── OPERATIONAL STATE ENFORCEMENT ─────────────────────────
            # Check CAN_WRITE capability (blocks PUSH if suspended, read-only, quarantined, etc.)
            try:
                await TenantPolicy.enforce(
                    db=db, 
                    temple_id=tid, 
                    capability=OperationalCapability.CAN_WRITE,
                    user_role=user_role
                )
            except HTTPException as e:
                return {
                    "id": temple_id_str,
                    "status": "error",
                    "message": f"Cloud push blocked: {e.detail}",
                    "local_change_id": local_change_id,
                }

            server_version = temple.version or 1

            # ── CONFLICT DETECTION ────────────────────────────────────
            if client_version < server_version:
                profile_result = await db.execute(
                    select(TempleProfile).filter(TempleProfile.temple_id == tid)
                )
                profile = profile_result.scalars().first()

                logger.info(
                    "Sync conflict: temple=%s client_v=%d server_v=%d",
                    temple_id_str, client_version, server_version,
                )
                return {
                    "id": temple_id_str,
                    "status": "conflict",
                    "message": f"Version conflict: client={client_version}, server={server_version}",
                    "server_version": server_version,
                    "server_data": _temple_to_dict(temple, profile),
                    "client_data": changes,
                    "local_change_id": local_change_id,
                }

            # ── APPLY UPDATE ──────────────────────────────────────────
            old_values = {}
            for field, value in safe_changes.items():
                if hasattr(temple, field):
                    old_values[field] = getattr(temple, field)
                    setattr(temple, field, value)

            # Atomic version increment
            temple.version = server_version + 1
            temple.updated_at = utcnow()

            # Sync TempleProfile if applicable
            profile_result = await db.execute(
                select(TempleProfile).filter(TempleProfile.temple_id == tid)
            )
            profile = profile_result.scalars().first()
            if profile:
                profile_fields = {
                    "location", "state", "district",
                    "contact_number", "email", "description",
                }
                for field in profile_fields & set(safe_changes.keys()):
                    if hasattr(profile, field):
                        setattr(profile, field, safe_changes[field])

            # ── Audit record ──────────────────────────────────────────
            await AuditService.log_action(
                db=db,
                temple_id=tid,
                user_id=user_id,
                role=user_role,
                module_name="temples",
                action="sync_update",
                action_type="update",
                entity_id=temple_id_str,
                old_value=old_values,
                new_value=safe_changes,
                details=f"Sync push: v{server_version}->v{server_version + 1}",
            )

        # Savepoint released
        logger.info(
            "Sync applied: temple=%s v%d->v%d",
            temple_id_str, server_version, server_version + 1,
        )

        return {
            "id": temple_id_str,
            "status": "applied",
            "message": f"Updated successfully (v{server_version + 1})",
            "server_version": server_version + 1,
            "local_change_id": local_change_id,
        }
