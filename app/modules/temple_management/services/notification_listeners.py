"""
Temple Notification Listeners — Event-driven notification dispatch.

Phase 3: Structured notification handlers triggered by temple events.
Uses log-based stub (send_notification) — no external services.

Listeners are registered at module import time and fire synchronously
when temple_events.emit_event() is called. The actual notification
persistence happens inside send_notification via a short-lived DB session.
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ── Structured Notification Stub ──────────────────────────────────────

def send_notification(
    user_id: Optional[str],
    message: str,
    title: str = "System Notification",
    temple_id: Optional[str] = None,
    role: Optional[str] = None,
) -> None:
    """
    Structured notification handler (log-based stub).

    Phase 3: Logs the notification in a structured format.
    Future: Replace with real push/email/SMS integration.

    Args:
        user_id: Target user UUID string (None for role-based)
        message: Notification message body
        title: Notification title
        temple_id: Context temple UUID string
        role: Target role for role-based notifications
    """
    logger.info(
        "NOTIFICATION [%s] to=%s role=%s temple=%s | %s",
        title,
        user_id or "BROADCAST",
        role or "ALL",
        temple_id or "SYSTEM",
        message,
    )

    # Persist to DB via background-safe session
    _persist_notification(
        user_id=user_id,
        message=message,
        title=title,
        temple_id=temple_id,
        role=role,
    )


def _persist_notification(
    user_id: Optional[str],
    message: str,
    title: str,
    temple_id: Optional[str],
    role: Optional[str],
) -> None:
    """
    Best-effort DB persistence for notifications.
    Uses a new session to avoid transaction coupling with event emitter.
    Failures are logged but never propagate.
    """
    import asyncio

    async def _async_persist():
        try:
            from uuid import UUID
            from app.core.database import AsyncSessionLocal
            from app.services.notification_service import NotificationService

            # Need a valid temple_id UUID for the Notification model
            if not temple_id:
                logger.debug("Skipping DB persist — no temple_id context")
                return

            async with AsyncSessionLocal() as db:
                tid = UUID(temple_id)
                uid = UUID(user_id) if user_id and user_id != "SYSTEM" else None

                await NotificationService._stage_notification(
                    db=db,
                    temple_id=tid,
                    title=title,
                    message=message,
                    user_id=uid,
                    role=role,
                )
                await db.commit()

        except Exception as e:
            logger.warning(
                "Notification DB persist failed (non-critical): %s", e
            )

    # Fire-and-forget in the current event loop (or skip if no loop)
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_async_persist())
    except RuntimeError:
        # No running event loop — skip async persist, log is sufficient
        logger.debug("No event loop — notification logged only (no DB persist)")


# ── Event Listener Callbacks ──────────────────────────────────────────

def _on_temple_status_changed(event_name: str, payload: Dict[str, Any]) -> None:
    """Handle TEMPLE_STATUS_CHANGED events."""
    temple_id = payload.get("entity_id") or payload.get("temple_id")
    old_status = (payload.get("old") or {}).get("status") or payload.get("old_status", "UNKNOWN")
    new_status = (payload.get("new") or {}).get("status") or payload.get("new_status", "UNKNOWN")
    triggered_by = payload.get("triggered_by", "SYSTEM")

    send_notification(
        user_id=None,
        message=f"Temple status changed from {old_status} to {new_status}",
        title="Temple Status Updated",
        temple_id=temple_id,
        role="SUPERADMIN",
    )

    # Notify the temple admin if the temple was approved/rejected
    if new_status in ("APPROVED", "REJECTED"):
        send_notification(
            user_id=None,
            message=f"Your temple registration has been {new_status.lower()}",
            title=f"Temple {new_status.title()}",
            temple_id=temple_id,
            role="TEMPLE_ADMIN",
        )


def _on_temple_created(event_name: str, payload: Dict[str, Any]) -> None:
    """Handle TEMPLE_CREATED events — notify admin."""
    temple_id = payload.get("entity_id") or payload.get("temple_id")
    temple_name = (payload.get("new") or {}).get("name") or payload.get("name", "Unknown")
    triggered_by = payload.get("triggered_by", "SYSTEM")

    send_notification(
        user_id=None,
        message=f"New temple '{temple_name}' has been created",
        title="New Temple Created",
        temple_id=temple_id,
        role="SUPERADMIN",
    )


def _on_temple_deleted(event_name: str, payload: Dict[str, Any]) -> None:
    """Handle TEMPLE_DELETED events — notify relevant users."""
    temple_id = payload.get("entity_id") or payload.get("temple_id")
    temple_name = (payload.get("old") or {}).get("name") or payload.get("name", "Unknown")
    triggered_by = payload.get("triggered_by", "SYSTEM")

    # Notify superadmins
    send_notification(
        user_id=None,
        message=f"Temple '{temple_name}' has been deactivated",
        title="Temple Deactivated",
        temple_id=temple_id,
        role="SUPERADMIN",
    )

    # Notify temple admins of the affected temple
    send_notification(
        user_id=None,
        message=f"Your temple '{temple_name}' has been deactivated by an administrator",
        title="Temple Deactivated",
        temple_id=temple_id,
        role="TEMPLE_ADMIN",
    )


# ── Register Listeners ────────────────────────────────────────────────

def register_notification_listeners() -> None:
    """
    Register all notification listeners with the temple event system.
    Called once at application startup.
    """
    from app.services.temple_events import (
        register_listener,
        TEMPLE_STATUS_CHANGED,
        TEMPLE_CREATED,
        TEMPLE_DELETED,
    )

    register_listener(TEMPLE_STATUS_CHANGED, _on_temple_status_changed)
    register_listener(TEMPLE_CREATED, _on_temple_created)
    register_listener(TEMPLE_DELETED, _on_temple_deleted)

    logger.info("Phase 3: Notification listeners registered for temple events")
