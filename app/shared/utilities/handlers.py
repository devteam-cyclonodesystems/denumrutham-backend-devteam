"""
Event Handlers for Temple Management System.

Phase 3: Updated handlers for backward compatibility with standardized
event payloads. Handlers extract fields from both old-style and new
standardized payload format.
"""
import logging
from typing import Any, Dict

from app.events.dispatcher import EventDispatcher
from app.services.notification_service import NotificationService, NotificationEvent
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


# ── Payload helpers for backward compat with standardized format ──────

def _get_field(payload: Dict[str, Any], key: str, nested_key: str = None, nested_section: str = None) -> Any:
    """
    Extract a field from either old-style or standardized payload.
    Standardized: payload["new"]["status"] or payload["old"]["status"]
    Old-style: payload["status"] or payload["new_status"]
    """
    # Direct key first
    if key in payload:
        return payload[key]
    # Try nested section (e.g., payload["new"]["status"])
    if nested_section and nested_key:
        section = payload.get(nested_section) or {}
        if nested_key in section:
            return section[nested_key]
    return None


async def handle_user_registered(payload: Dict[str, Any]):
    login_id = _get_field(payload, "login_id") or _get_field(payload, "entity_id")
    logger.info(f"Notification mock: Welcome email sent to {login_id}")

async def handle_staff_status_changed(payload: Dict[str, Any]):
    status = _get_field(payload, "status", "status", "new") or payload.get("status")
    user_id = _get_field(payload, "user_id") or _get_field(payload, "entity_id")
    temple_id = _get_field(payload, "temple_id")
    logger.info(f"Notification mock: Staff {user_id} was {status} at temple {temple_id}")
    
    # Real Notification Dispatch
    if temple_id:
        async with AsyncSessionLocal() as db:
            await NotificationService._stage_notification(
                db=db,
                temple_id=temple_id,
                title=f"Staff Registration {status}",
                message=f"Your staff registration was {status}.",
                user_id=user_id,
            )
            await db.commit()

async def handle_temple_status_changed(payload: Dict[str, Any]):
    """Handle TEMPLE_STATUS_CHANGED — extract from standardized or old payload."""
    new_status = _get_field(payload, "new_status", "status", "new")
    old_status = _get_field(payload, "old_status", "status", "old")
    temple_id = _get_field(payload, "temple_id") or _get_field(payload, "entity_id")
    temple_name = _get_field(payload, "temple_name") or _get_field(payload, "name", "name", "new")
    triggered_by = _get_field(payload, "triggered_by") or _get_field(payload, "changed_by")
    
    logger.info(
        "Notification: Temple %s status changed %s -> %s (by %s)",
        temple_id, old_status, new_status, triggered_by
    )

async def handle_change_request_processed(payload: Dict[str, Any]):
    status = _get_field(payload, "status", "status", "new") or payload.get("status")
    temple_id = _get_field(payload, "temple_id")
    request_id = _get_field(payload, "request_id") or _get_field(payload, "entity_id")
    requested_by = _get_field(payload, "requested_by") or _get_field(payload, "triggered_by")
    
    event_type = NotificationEvent.APPROVAL_APPROVED if status == "APPROVED" else NotificationEvent.APPROVAL_REJECTED
    
    if temple_id:
        async with AsyncSessionLocal() as db:
            await NotificationService.dispatch_event(
                db=db,
                temple_id=temple_id,
                event_type=event_type,
                title=f"Change Request {status}",
                message=f"Change request {request_id} has been {status}.",
                requester_id=requested_by
            )
            await db.commit()

async def handle_booking_confirmed(payload: Dict[str, Any]):
    booking_id = _get_field(payload, "booking_id") or _get_field(payload, "entity_id")
    logger.info(f"Notification mock: SMS sent to devotee for booking {booking_id}")

# Register Handlers
EventDispatcher.register("USER_REGISTERED", handle_user_registered)
EventDispatcher.register("STAFF_STATUS_CHANGED", handle_staff_status_changed)
EventDispatcher.register("TEMPLE_STATUS_CHANGED", handle_temple_status_changed)
EventDispatcher.register("CHANGE_REQUEST_PROCESSED", handle_change_request_processed)
EventDispatcher.register("BOOKING_CONFIRMED", handle_booking_confirmed)
