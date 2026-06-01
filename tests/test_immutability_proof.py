import pytest
import uuid
import zipfile
import io
import json
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.future import select

from tests.conftest import TestSessionLocal, TEMPLE_ID
from app.modules.audit.models.audit_models import ImmutableActivityLog, ActivityOutbox
from app.modules.audit.services.activity_log_processor import ActivityLogProcessor
from app.modules.audit.services.chain_verification_service import ChainVerificationService
from app.modules.audit.services.activity_log_query_service import ActivityLogQueryService

@pytest.mark.asyncio
async def test_orm_immutability_enforcement(setup_database):
    """Verify that ORM-level updates and deletes on ImmutableActivityLog are blocked."""
    async with TestSessionLocal() as db:
        # Create a single log entry manually
        log = ImmutableActivityLog(
            id=uuid.uuid4(),
            temple_id=TEMPLE_ID,
            temple_code="DEMO",
            tenant_name="Demo Temple",
            module_name="INVENTORY",
            entity_name="Item",
            entity_id="ITEM-1",
            action_type="CREATE",
            action_category="INVENTORY_OPERATION",
            description="Item created",
            previous_hash="0" * 64,
            current_hash="abc",
            audit_chain_index=1,
            ip_address="127.0.0.1",
            correlation_id=uuid.uuid4(),
            performed_by_user_id=uuid.uuid4(),
            performed_by_name="Admin",
            performed_by_role="SUPERADMIN"
        )
        db.add(log)
        await db.commit()

    async with TestSessionLocal() as db:
        res = await db.execute(select(ImmutableActivityLog).filter(ImmutableActivityLog.entity_id == "ITEM-1"))
        stored_log = res.scalar_one()

        # Attempt to modify
        stored_log.description = "Altered description"
        with pytest.raises(PermissionError) as exc_info:
            await db.commit()
        assert "Mutation Denied: Activity log entries are strictly immutable." in str(exc_info.value)
        await db.rollback()

    async with TestSessionLocal() as db:
        res = await db.execute(select(ImmutableActivityLog).filter(ImmutableActivityLog.entity_id == "ITEM-1"))
        stored_log = res.scalar_one()

        # Attempt to delete
        await db.delete(stored_log)
        with pytest.raises(PermissionError) as exc_info:
            await db.commit()
        assert "Mutation Denied: Activity log entries are strictly immutable." in str(exc_info.value)
        await db.rollback()


@pytest.mark.asyncio
async def test_evidence_package_validation(setup_database):
    """Verify that generated evidence packages are valid ZIP archives containing the manifest, logs, and report."""
    async with TestSessionLocal() as db:
        # Clean existing logs
        await db.execute(text("DELETE FROM immutable_activity_logs"))
        
        # Seed 3 sequential logs to form a chain
        prev_hash = "0" * 64
        for idx in range(1, 4):
            log_id = uuid.uuid4()
            created_utc = datetime.now(timezone.utc)
            after_val = {"step": idx}
            curr_hash = ActivityLogProcessor.calculate_log_hash(
                log_id=log_id,
                temple_id=TEMPLE_ID,
                action_type="TEST_OP",
                created_utc=created_utc,
                after_value=after_val,
                prev_hash=prev_hash
            )
            log = ImmutableActivityLog(
                id=log_id,
                temple_id=TEMPLE_ID,
                temple_code="DEMO",
                tenant_name="Demo Temple",
                module_name="BOOKINGS",
                entity_name="ArchanaBooking",
                entity_id=f"B-{idx}",
                action_type="TEST_OP",
                action_category="TEST",
                description=f"Log step {idx}",
                after_value=after_val,
                previous_hash=prev_hash,
                current_hash=curr_hash,
                audit_chain_index=idx,
                ip_address="127.0.0.1",
                correlation_id=uuid.uuid4(),
                created_utc=created_utc,
                performed_by_user_id=uuid.uuid4(),
                performed_by_name="Admin",
                performed_by_role="SUPERADMIN"
            )
            db.add(log)
            prev_hash = curr_hash
        await db.commit()

    async with TestSessionLocal() as db:
        # Generate evidence package
        zip_bytes = await ActivityLogQueryService.generate_evidence_package(
            db=db,
            temple_id=TEMPLE_ID,
            investigator_name="Judge Cooper",
            module_name="BOOKINGS"
        )
        assert len(zip_bytes) > 0

        # Load ZIP and check contents
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zip_file:
            namelist = zip_file.namelist()
            assert "activity_logs.json" in namelist
            assert "chain_verification_report.txt" in namelist
            assert "evidence_manifest.json" in namelist

            # Read and parse evidence_manifest.json
            manifest = json.loads(zip_file.read("evidence_manifest.json").decode())
            assert manifest["investigator"] == "Judge Cooper"
            assert manifest["record_count"] == 3
            assert manifest["chain_integrity_verified"] is True

            # Read and check report details
            report_text = zip_file.read("chain_verification_report.txt").decode()
            assert "VERIFIED" in report_text or "PASS" in report_text or "verified" in report_text.lower()
            assert "Judge Cooper" in report_text


@pytest.mark.asyncio
async def test_backup_restore_integrity_validation(setup_database):
    """Verify that exporting logs, restoring them to a fresh DB instance, and verifying the chain succeeds."""
    logs_backup = []

    async with TestSessionLocal() as db:
        # Clean existing logs
        await db.execute(text("DELETE FROM immutable_activity_logs"))
        
        # Seed 3 sequential logs to form a chain
        prev_hash = "0" * 64
        for idx in range(1, 4):
            log_id = uuid.uuid4()
            user_uuid = uuid.uuid4()
            created_utc = datetime.now(timezone.utc)
            after_val = {"step": idx}
            curr_hash = ActivityLogProcessor.calculate_log_hash(
                log_id=log_id,
                temple_id=TEMPLE_ID,
                action_type="TEST_OP",
                created_utc=created_utc,
                after_value=after_val,
                prev_hash=prev_hash
            )
            log = ImmutableActivityLog(
                id=log_id,
                temple_id=TEMPLE_ID,
                temple_code="DEMO",
                tenant_name="Demo Temple",
                module_name="BOOKINGS",
                entity_name="ArchanaBooking",
                entity_id=f"B-{idx}",
                action_type="TEST_OP",
                action_category="TEST",
                description=f"Log step {idx}",
                after_value=after_val,
                previous_hash=prev_hash,
                current_hash=curr_hash,
                audit_chain_index=idx,
                ip_address="127.0.0.1",
                correlation_id=uuid.uuid4(),
                created_utc=created_utc,
                performed_by_user_id=user_uuid,
                performed_by_name="Admin",
                performed_by_role="SUPERADMIN"
            )
            db.add(log)
            
            # Back up attributes to simulate export dump
            logs_backup.append({
                "id": log_id,
                "temple_id": TEMPLE_ID,
                "temple_code": "DEMO",
                "tenant_name": "Demo Temple",
                "module_name": "BOOKINGS",
                "entity_name": "ArchanaBooking",
                "entity_id": f"B-{idx}",
                "action_type": "TEST_OP",
                "action_category": "TEST",
                "description": f"Log step {idx}",
                "after_value": after_val,
                "previous_hash": prev_hash,
                "current_hash": curr_hash,
                "audit_chain_index": idx,
                "ip_address": "127.0.0.1",
                "correlation_id": uuid.uuid4(),
                "created_utc": created_utc,
                "performed_by_user_id": user_uuid,
                "performed_by_name": "Admin",
                "performed_by_role": "SUPERADMIN"
            })
            prev_hash = curr_hash
        await db.commit()

    async with TestSessionLocal() as db:
        # Run verify to verify baseline is fine
        verify_res = await ChainVerificationService.verify_audit_chain(db, TEMPLE_ID)
        assert verify_res["verified"] is True

        # SIMULATE WIPE/RESTORE: Wipe out DB records via raw SQL bypass
        await db.execute(text("DELETE FROM immutable_activity_logs"))
        await db.commit()

        # Confirm count is zero
        res_count = await db.execute(select(ImmutableActivityLog))
        assert len(res_count.scalars().all()) == 0

        # Restore from backup
        for backup_log in logs_backup:
            restored = ImmutableActivityLog(**backup_log)
            db.add(restored)
        await db.commit()

    async with TestSessionLocal() as db:
        # Re-verify restored chain
        restore_verify_res = await ChainVerificationService.verify_audit_chain(db, TEMPLE_ID)
        assert restore_verify_res["verified"] is True
        assert restore_verify_res["total_logs"] == 3
        assert restore_verify_res["status"] == "PASS"


@pytest.mark.asyncio
async def test_audit_governance_apis(client):
    """Test the newly introduced audit governance and monitoring endpoints."""
    from app.core.security import create_access_token
    
    # Generate a token with SUPERADMIN role to bypass tenant RBAC guards
    token = create_access_token(
        subject=str(uuid.uuid4()),
        temple_id=str(TEMPLE_ID),
        role="SUPERADMIN",
        username="superadmin"
    )
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Config GET & PUT
    resp = await client.get("/api/v1/audit-logs/governance/config", headers=headers)
    assert resp.status_code == 200, resp.text
    config_data = resp.json()
    assert config_data["retention_days"] == 365

    # Change config
    config_data["retention_days"] = 180
    resp_put = await client.put("/api/v1/audit-logs/governance/config", json=config_data, headers=headers)
    assert resp_put.status_code == 200, resp_put.text
    assert resp_put.json()["retention_days"] == 180

    # 2. Verify POST (triggers manual integrity verification)
    resp_verify = await client.post("/api/v1/audit-logs/governance/verify", headers=headers)
    assert resp_verify.status_code == 200, resp_verify.text
    verify_json = resp_verify.json()
    assert "status" in verify_json
    assert "total_logs" in verify_json

    # 3. Reports history GET
    resp_reports = await client.get("/api/v1/audit-logs/governance/reports", headers=headers)
    assert resp_reports.status_code == 200, resp_reports.text
    reports_list = resp_reports.json()
    assert len(reports_list) >= 1

    # 4. Monitoring metrics GET
    resp_metrics = await client.get("/api/v1/audit-logs/monitoring/metrics", headers=headers)
    assert resp_metrics.status_code == 200, resp_metrics.text
    metrics_json = resp_metrics.json()
    assert "queue_size" in metrics_json
    assert "processing_rate" in metrics_json

    # 5. Export POST
    resp_export = await client.post(
        "/api/v1/audit-logs/governance/export",
        json={"investigator_name": "Auditor Holmes", "module_name": "BOOKINGS"},
        headers=headers
    )
    assert resp_export.status_code == 200, resp_export.text
    assert resp_export.headers["content-type"] == "application/zip"
    assert len(resp_export.content) > 0


