"""
Temple Event Hooks — Standardized event dispatch system.

Phase 3: Events now use a standardized payload format and support
notification listeners. All events include entity, entity_id,
event type, old/new values, triggered_by, and timestamp.

Usage:
    from app.services.temple_events import emit_event, build_event_payload

    emit_event("TEMPLE_STATUS_CHANGED", build_event_payload(
        entity="temple",
        entity_id=str(temple.id),
        event="TEMPLE_STATUS_CHANGED",
        old={"status": "PENDING"},
        new={"status": "APPROVED"},
        triggered_by=str(user_id),
    ))

Future extensions can register listeners via register_listener().
"""
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Internal listener registry — keyed by event name
_listeners: Dict[str, List[Callable]] = {}


def build_event_payload(
    entity: str,
    entity_id: str,
    event: str,
    triggered_by: str = "SYSTEM",
    old: Optional[Dict[str, Any]] = None,
    new: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build a standardized event payload.

    Standard format:
    {
        "entity": "temple",
        "entity_id": "uuid-string",
        "event": "TEMPLE_STATUS_CHANGED",
        "old": {"status": "PENDING"},
        "new": {"status": "APPROVED"},
        "triggered_by": "user-uuid-string",
        "timestamp": "2026-05-03T12:00:00+00:00"
    }
    """
    payload = {
        "entity": entity,
        "entity_id": entity_id,
        "event": event,
        "old": old,
        "new": new,
        "triggered_by": triggered_by,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    # Merge any extra fields (backward compat for handlers that expect them)
    if extra:
        payload.update(extra)
    return payload


def register_listener(event_name: str, callback: Callable[[str, dict], None]) -> None:
    """
    Register a callback for a specific event.

    Args:
        event_name: Event identifier (e.g. "TEMPLE_STATUS_CHANGED")
        callback: Function(event_name, payload) to invoke when event fires
    """
    if event_name not in _listeners:
        _listeners[event_name] = []
    _listeners[event_name].append(callback)
    logger.debug("Registered listener for event: %s", event_name)


def emit_event(event_name: str, payload: Dict[str, Any]) -> None:
    """
    Emit an internal event.

    - Logs the event at INFO level
    - Dispatches to any registered listeners (including notification listeners)
    - Non-blocking: listener failures are logged but don't propagate

    Args:
        event_name: Event identifier
        payload: Standardized event payload (see build_event_payload)
    """
    logger.info(
        "EVENT [%s] entity=%s entity_id=%s triggered_by=%s",
        event_name,
        payload.get("entity", "unknown"),
        payload.get("entity_id", "unknown"),
        payload.get("triggered_by", "SYSTEM"),
    )

    # Dispatch to registered listeners (if any)
    for listener in _listeners.get(event_name, []):
        try:
            listener(event_name, payload)
        except Exception as e:
            logger.warning(
                "Listener failed for event %s: %s (non-critical)",
                event_name, e,
            )


# ── Predefined Event Names (constants) ───────────────────────────────
TEMPLE_CREATED = "TEMPLE_CREATED"
TEMPLE_STATUS_CHANGED = "TEMPLE_STATUS_CHANGED"
TEMPLE_DELETED = "TEMPLE_DELETED"
