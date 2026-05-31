import pytest
import pytest_asyncio
import uuid
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.audit.services.activity_log_service import ActivityLogService
from app.modules.audit.services.activity_log_processor import ActivityLogProcessor
from app.modules.audit.models.audit_models import ActivityOutbox, ImmutableActivityLog
from app.models.domain import Temple

@pytest.mark.asyncio
async def test_activity_logs_pipeline(setup_database):
    # Setup isolated test database session (analogous to get_db/override_get_db)
    from tests.conftest import TestSessionLocal, TEMPLE_ID
    
    async with TestSessionLocal() as db:
        # Verify the seeded Temple is present
        res = await db.execute(select(Temple).filter(Temple.id == TEMPLE_ID))
        temple = res.scalar_one_or_none()
        assert temple is not None, "Seeded Temple not found"
        
        # 1. Test ActivityLogService.emit_event (stages to activity_outbox)
        before_val = {
            "name": "Jane Doe",
            "email": "jane.doe@example.com",
            "phone": "9876543210",
            "password": "supersecurepassword123",
            "cvv": "123",
            "normal_field": "no pii here"
        }
        after_val = {
            "name": "Jane Smith",
            "email": "jane.smith@example.com",
            "phone": "9876500000",
            "password": "newsupersecurepassword456",
            "cvv": "456",
            "normal_field": "updated normal field"
        }
        
        outbox_entry = await ActivityLogService.emit_event(
            db=db,
            temple_id=TEMPLE_ID,
            module_name="BOOKINGS",
            entity_name="Booking",
            entity_id="HB100",
            action_type="UPDATE",
            action_category="BOOKING_MODIFICATION",
            description="Modified hall booking details",
            before_value=before_val,
            after_value=after_val,
            performed_by_user_id=uuid.uuid4(),
            performed_by_name="Manager John",
            performed_by_role="TEMPLE_MANAGER",
            severity="HIGH",
            risk_score=50
        )
        
        # Verify outbox entry properties
        assert outbox_entry.id is not None
        assert outbox_entry.severity == "HIGH"
        assert outbox_entry.risk_score == 50
        
        # Verify secrets redaction
        assert outbox_entry.before_value["password"] == "[REDACTED]"
        assert outbox_entry.before_value["cvv"] == "[REDACTED]"
        assert outbox_entry.after_value["password"] == "[REDACTED]"
        assert outbox_entry.after_value["cvv"] == "[REDACTED]"
        
        # Verify hybrid PII masking
        assert outbox_entry.masked_pii["name"] == "Jane S***"
        assert outbox_entry.masked_pii["email"] == "jan****@example.com"
        assert outbox_entry.masked_pii["phone"] == "98765*****"
        
        # Verify hybrid PII salted hashing
        assert outbox_entry.hashed_pii["name"] == ActivityLogService.hash_pii_value("Jane Smith")
        assert outbox_entry.hashed_pii["email"] == ActivityLogService.hash_pii_value("jane.smith@example.com")
        
        # Commit to save in SQLite mock outbox
        await db.commit()
        
    # Re-open session to process outbox in background
    async with TestSessionLocal() as db:
        # Check outbox count
        outbox_res = await db.execute(select(ActivityOutbox))
        outbox_items = outbox_res.scalars().all()
        assert len(outbox_items) == 1
        
        # 2. Run ActivityLogProcessor.process_outbox
        processed = await ActivityLogProcessor.process_outbox(db)
        assert processed == 1
        
        # Verify outbox is now empty
        outbox_res_after = await db.execute(select(ActivityOutbox))
        assert len(outbox_res_after.scalars().all()) == 0
        
        # Verify immutable log row is created
        log_res = await db.execute(
            select(ImmutableActivityLog).filter(ImmutableActivityLog.entity_id == "HB100")
        )
        log = log_res.scalar_one_or_none()
        assert log is not None
        assert log.audit_chain_index == 1
        assert log.previous_hash == "0" * 64
        assert log.current_hash != ""
        
        # Add another event to test sequential hash chaining
        outbox_entry_2 = await ActivityLogService.emit_event(
            db=db,
            temple_id=TEMPLE_ID,
            module_name="BOOKINGS",
            entity_name="Booking",
            entity_id="HB100",
            action_type="CANCEL",
            action_category="BOOKING_CANCELLATION",
            description="Cancelled hall booking",
            before_value={"status": "CONFIRMED"},
            after_value={"status": "CANCELLED"},
            performed_by_user_id=uuid.uuid4(),
            performed_by_name="Manager John",
            performed_by_role="TEMPLE_MANAGER",
            severity="HIGH",
            risk_score=60
        )
        await db.commit()
        
    async with TestSessionLocal() as db:
        processed_2 = await ActivityLogProcessor.process_outbox(db)
        assert processed_2 == 1
        
        # Query both log records in order of index
        logs_res = await db.execute(
            select(ImmutableActivityLog)
            .filter(ImmutableActivityLog.temple_id == TEMPLE_ID)
            .order_by(ImmutableActivityLog.audit_chain_index.asc())
        )
        logs = logs_res.scalars().all()
        assert len(logs) == 2
        
        log_1, log_2 = logs[0], logs[1]
        
        assert log_1.audit_chain_index == 1
        assert log_2.audit_chain_index == 2
        
        # Verify cryptographic chain linking (blockchain-style)
        assert log_2.previous_hash == log_1.current_hash
        assert log_2.current_hash == ActivityLogProcessor.calculate_log_hash(
            log_id=log_2.id,
            temple_id=log_2.temple_id,
            action_type=log_2.action_type,
            created_utc=log_2.created_utc,
            after_value=log_2.after_value,
            prev_hash=log_2.previous_hash
        )

        # 3. Verify application-level immutability hooks
        # Try to modify log_1
        log_1.description = "Malicious update attempt"
        with pytest.raises(PermissionError) as exc_info:
            await db.commit()
        assert "Mutation Denied: Activity log entries are strictly immutable." in str(exc_info.value)
        await db.rollback()
        
        # Try to delete log_2
        log_to_delete_res = await db.execute(
            select(ImmutableActivityLog).filter(ImmutableActivityLog.audit_chain_index == 2)
        )
        log_to_delete = log_to_delete_res.scalar_one()
        await db.delete(log_to_delete)
        with pytest.raises(PermissionError) as exc_info_del:
            await db.commit()
        assert "Mutation Denied: Activity log entries are strictly immutable." in str(exc_info_del.value)
        await db.rollback()


@pytest.mark.asyncio
async def test_activity_logs_api(client, auth_headers):
    # 1. Dashboard Endpoint
    resp = await client.get("/api/v1/manager/activity-logs/dashboard", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert "today_activities_count" in data
    assert "critical_events_count" in data
    assert "high_severity_events_count" in data
    assert "active_staff_count" in data
    assert "module_distribution" in data
    
    # 2. Timeline Endpoint
    resp_timeline = await client.get("/api/v1/manager/activity-logs/timeline", headers=auth_headers)
    assert resp_timeline.status_code == 200, resp_timeline.text
    resp_json = resp_timeline.json()
    timeline_data = resp_json["data"]
    meta_data = resp_json["meta"]
    assert isinstance(timeline_data, list)
    assert "total_count" in meta_data
    
    # Let's verify that we have at least the processed logs from the previous test or we can extract one ID to run forensic checks on
    items = timeline_data
    if items:
        target_log_id = items[0]["id"]
        
        # 3. Forensic Endpoint
        resp_forensic = await client.get(f"/api/v1/manager/activity-logs/forensic/{target_log_id}", headers=auth_headers)
        assert resp_forensic.status_code == 200, resp_forensic.text
        forensic_data = resp_forensic.json()["data"]
        assert forensic_data["verified"] is True
        assert forensic_data["status"] == "verified"
        
        # 4. Entity timeline
        entity_name = items[0]["entity_name"]
        entity_id = items[0]["entity_id"]
        resp_entity = await client.get(f"/api/v1/manager/activity-logs/entity/{entity_name}/{entity_id}", headers=auth_headers)
        assert resp_entity.status_code == 200, resp_entity.text
        entity_data = resp_entity.json()["data"]
        assert len(entity_data) >= 1

    # 5. Export Endpoint
    resp_export = await client.get("/api/v1/manager/activity-logs/export", headers=auth_headers)
    assert resp_export.status_code == 200
    assert resp_export.headers["content-type"] == "application/zip"
    assert len(resp_export.content) > 0

