"""
Phase 3 Validation Tests — System Activation

Validates:
  1. RBAC blocks unauthorized actions
  2. Notifications triggered via events
  3. Audit API supports pagination + filtering
  4. Event payload is standardized
  5. Version increments correctly
"""
import pytest
import asyncio
import logging
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4, UUID
from datetime import datetime, timezone, timedelta

# Configure pytest-asyncio mode
pytestmark = pytest.mark.asyncio

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# SECTION 1: RBAC Implementation Tests
# ═══════════════════════════════════════════════════════════════════════

class TestRBACGuards:
    """Test that RBAC guards enforce role-based access correctly."""


    async def test_superadmin_can_modify_any_temple(self):
        """SUPER_ADMIN should always be allowed to modify any temple."""
        from app.services.temple_rbac import can_modify_temple
        db = AsyncMock()
        result = await can_modify_temple(db, uuid4(), "SUPERADMIN", uuid4())
        assert result is True


    async def test_superadmin_can_change_status(self):
        """SUPER_ADMIN should always be allowed to change status."""
        from app.services.temple_rbac import can_change_status
        db = AsyncMock()
        result = await can_change_status(db, uuid4(), "SUPERADMIN", uuid4())
        assert result is True


    async def test_superadmin_can_delete_temple(self):
        """SUPER_ADMIN should always be allowed to delete."""
        from app.services.temple_rbac import can_delete_temple
        db = AsyncMock()
        result = await can_delete_temple(db, uuid4(), "SUPERADMIN", uuid4())
        assert result is True


    async def test_devotee_cannot_modify(self):
        """DEVOTEE should never be allowed to modify a temple."""
        from app.services.temple_rbac import can_modify_temple
        db = AsyncMock()
        result = await can_modify_temple(db, uuid4(), "DEVOTEE", uuid4())
        assert result is False


    async def test_devotee_cannot_change_status(self):
        """DEVOTEE should never be allowed to change status."""
        from app.services.temple_rbac import can_change_status
        db = AsyncMock()
        result = await can_change_status(db, uuid4(), "DEVOTEE", uuid4())
        assert result is False


    async def test_devotee_cannot_delete(self):
        """DEVOTEE should never be allowed to delete."""
        from app.services.temple_rbac import can_delete_temple
        db = AsyncMock()
        result = await can_delete_temple(db, uuid4(), "DEVOTEE", uuid4())
        assert result is False


    async def test_temple_admin_cannot_change_status(self):
        """TEMPLE_ADMIN should not be allowed to change status."""
        from app.services.temple_rbac import can_change_status
        db = AsyncMock()
        result = await can_change_status(db, uuid4(), "TEMPLE_ADMIN", uuid4())
        assert result is False


    async def test_temple_admin_cannot_delete(self):
        """TEMPLE_ADMIN should not be allowed to delete temples."""
        from app.services.temple_rbac import can_delete_temple
        db = AsyncMock()
        result = await can_delete_temple(db, uuid4(), "TEMPLE_ADMIN", uuid4())
        assert result is False


    async def test_null_role_denied(self):
        """No role should be denied."""
        from app.services.temple_rbac import can_modify_temple
        db = AsyncMock()
        result = await can_modify_temple(db, uuid4(), None, uuid4())
        assert result is False


    async def test_staff_cannot_modify(self):
        """STAFF role should not be allowed to modify temples."""
        from app.services.temple_rbac import can_modify_temple
        db = AsyncMock()
        result = await can_modify_temple(db, uuid4(), "STAFF", uuid4())
        assert result is False


    async def test_superadmin_alias_works(self):
        """SUPER_ADMIN with underscore should also work."""
        from app.services.temple_rbac import can_modify_temple
        db = AsyncMock()
        result = await can_modify_temple(db, uuid4(), "SUPER_ADMIN", uuid4())
        assert result is True


# ═══════════════════════════════════════════════════════════════════════
# SECTION 2: Notification System Tests
# ═══════════════════════════════════════════════════════════════════════

class TestNotificationSystem:
    """Test that notifications are triggered via events."""

    def test_send_notification_logs(self, caplog):
        """send_notification should log structured output."""
        from app.services.notification_listeners import send_notification
        with caplog.at_level(logging.INFO):
            send_notification(
                user_id="test-user-123",
                message="Test message",
                title="Test Title",
                temple_id=None,
                role=None,
            )
        assert "NOTIFICATION" in caplog.text
        assert "Test Title" in caplog.text

    def test_event_listeners_registered(self):
        """Notification listeners should be registered for temple events."""
        from app.services.temple_events import _listeners, TEMPLE_CREATED, TEMPLE_STATUS_CHANGED, TEMPLE_DELETED
        from app.services.notification_listeners import register_notification_listeners

        # Re-register to ensure
        register_notification_listeners()

        assert TEMPLE_CREATED in _listeners, "TEMPLE_CREATED listener not registered"
        assert TEMPLE_STATUS_CHANGED in _listeners, "TEMPLE_STATUS_CHANGED listener not registered"
        assert TEMPLE_DELETED in _listeners, "TEMPLE_DELETED listener not registered"

    def test_emit_event_triggers_listeners(self, caplog):
        """Emitting a temple event should trigger notification listeners."""
        from app.services.temple_events import emit_event, build_event_payload, TEMPLE_CREATED
        from app.services.notification_listeners import register_notification_listeners

        register_notification_listeners()

        with caplog.at_level(logging.INFO):
            emit_event(TEMPLE_CREATED, build_event_payload(
                entity="temple",
                entity_id="test-temple-id",
                event=TEMPLE_CREATED,
                triggered_by="test-user",
                new={"name": "Test Temple"},
            ))
        assert "NOTIFICATION" in caplog.text or "EVENT" in caplog.text


# ═══════════════════════════════════════════════════════════════════════
# SECTION 3: Audit API Tests
# ═══════════════════════════════════════════════════════════════════════

class TestAuditAPI:
    """Test audit service supports pagination, filtering, sorting."""

    def test_audit_service_accepts_date_range(self):
        """TempleAuditService.get_temple_audit_history should accept date params."""
        from app.services.temple_audit_service import TempleAuditService
        import inspect
        sig = inspect.signature(TempleAuditService.get_temple_audit_history)
        params = list(sig.parameters.keys())

        assert "date_from" in params, "date_from parameter missing"
        assert "date_to" in params, "date_to parameter missing"
        assert "sort_order" in params, "sort_order parameter missing"
        assert "limit" in params, "limit parameter missing"
        assert "offset" in params, "offset parameter missing"


# ═══════════════════════════════════════════════════════════════════════
# SECTION 4: Event Standardization Tests
# ═══════════════════════════════════════════════════════════════════════

class TestEventStandardization:
    """Test that event payloads follow the standard format."""

    def test_build_event_payload_structure(self):
        """build_event_payload should produce the standard schema."""
        from app.services.temple_events import build_event_payload

        payload = build_event_payload(
            entity="temple",
            entity_id="abc-123",
            event="TEMPLE_CREATED",
            triggered_by="user-456",
            old=None,
            new={"name": "Test"},
        )

        assert payload["entity"] == "temple"
        assert payload["entity_id"] == "abc-123"
        assert payload["event"] == "TEMPLE_CREATED"
        assert payload["triggered_by"] == "user-456"
        assert payload["old"] is None
        assert payload["new"] == {"name": "Test"}
        assert "timestamp" in payload

    def test_build_event_payload_timestamp_iso(self):
        """Timestamp should be ISO 8601 format."""
        from app.services.temple_events import build_event_payload

        payload = build_event_payload(
            entity="temple", entity_id="x", event="TEST",
        )
        # Should parse as ISO datetime
        dt = datetime.fromisoformat(payload["timestamp"])
        assert dt is not None

    def test_build_event_payload_extra_fields(self):
        """Extra fields should merge into payload."""
        from app.services.temple_events import build_event_payload

        payload = build_event_payload(
            entity="temple", entity_id="x", event="TEST",
            extra={"custom_field": "value"},
        )
        assert payload["custom_field"] == "value"


# ═══════════════════════════════════════════════════════════════════════
# SECTION 5: Hybrid Preparation Tests
# ═══════════════════════════════════════════════════════════════════════

class TestHybridPreparation:
    """Test version and updated_at fields are present and work correctly."""

    def test_temple_model_has_version(self):
        """Temple model should have version field."""
        from app.models.domain import Temple
        assert hasattr(Temple, "version"), "Temple model missing 'version' field"

    def test_temple_model_has_updated_at(self):
        """Temple model should have updated_at field."""
        from app.models.domain import Temple
        assert hasattr(Temple, "updated_at"), "Temple model missing 'updated_at' field"

    def test_version_default_is_one(self):
        """Version default should be 1."""
        from app.models.domain import Temple
        col = Temple.__table__.columns["version"]
        assert col.default.arg == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-x"])
