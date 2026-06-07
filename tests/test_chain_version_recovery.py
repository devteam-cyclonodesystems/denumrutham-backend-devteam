import pytest
import uuid
import json
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.future import select

from app.core.database import AsyncSessionLocal
from app.models.domain import Temple
from app.modules.audit.models.audit_models import (
    ImmutableActivityLog, AuditChainVersion, AuditChainIncident, AuditChainIndexRegistry
)
from app.modules.audit.services.audit_chain_writer import AuditChainWriter
from app.modules.audit.services.activity_log_processor import ActivityLogProcessor
from app.modules.audit.services.chain_verification_service import ChainVerificationService
from app.modules.governance.models.operational_states import TempleOperationalState
from tests.conftest import TestSessionLocal, TEMPLE_ID

@pytest.mark.asyncio
async def test_chain_version_recovery_lifecycle():
    """
    Tests the complete audit chain recovery lifecycle.
    1. Create a corrupted chain with duplicate indices.
    2. Run recovery logic (simulate the recovery script).
    3. Assert:
       - V1 remains completely frozen and unaltered.
       - Incident record exists and is RESOLVED with evidence.
       - Chain Version 1 is SEALED/FAIL.
       - Chain Version 2 is ACTIVE/PASS with parent_terminal_hash link.
       - ChainVerificationService.verify_audit_chain returns PASS for V2.
    """
    async with TestSessionLocal() as session:
        # Create a new test temple specifically for this lifecycle to avoid interference
        temple_id = uuid.uuid4()
        temple = Temple(
            id=temple_id,
            name="Malottu Recovery Test Temple",
            domain="malottu_test_domain",
            operational_state=TempleOperationalState.SUSPENDED
        )
        session.add(temple)
        await session.commit()

        # 1. Populate a corrupted chain for Version 1
        # Block 1 (Genesis V1)
        log1_id = uuid.uuid4()
        log1 = ImmutableActivityLog(
            id=log1_id,
            temple_id=temple_id,
            temple_code="TMP-RECOVER",
            tenant_name="Malottu Recovery Test Temple",
            module_name="SYSTEM",
            entity_name="Genesis",
            action_type="INITIALIZE",
            action_category="SECURITY",
            description="Genesis block V1",
            performed_by_user_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
            performed_by_name="System",
            performed_by_role="SYSTEM",
            ip_address="127.0.0.1",
            correlation_id=uuid.uuid4(),
            previous_hash="0" * 64,
            current_hash="hash_genesis_v1",
            audit_chain_index=1,
            chain_version=1,
            created_utc=datetime.now(timezone.utc)
        )
        session.add(log1)

        # Block 2 (Index 2)
        log2_id = uuid.uuid4()
        log2 = ImmutableActivityLog(
            id=log2_id,
            temple_id=temple_id,
            temple_code="TMP-RECOVER",
            tenant_name="Malottu Recovery Test Temple",
            module_name="POOJAS",
            entity_name="Pooja",
            action_type="CREATE",
            action_category="MUTATION",
            description="Created pooja",
            performed_by_user_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
            performed_by_name="System",
            performed_by_role="SYSTEM",
            ip_address="127.0.0.1",
            correlation_id=uuid.uuid4(),
            previous_hash="hash_genesis_v1",
            current_hash="hash_block2_v1",
            audit_chain_index=2,
            chain_version=1,
            created_utc=datetime.now(timezone.utc)
        )
        session.add(log2)

        # Block 3 (Duplicate index 2 - simulated concurrency corruption!)
        log3_id = uuid.uuid4()
        log3 = ImmutableActivityLog(
            id=log3_id,
            temple_id=temple_id,
            temple_code="TMP-RECOVER",
            tenant_name="Malottu Recovery Test Temple",
            module_name="BOOKINGS",
            entity_name="Booking",
            action_type="CREATE",
            action_category="MUTATION",
            description="Concurrent created booking",
            performed_by_user_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
            performed_by_name="System",
            performed_by_role="SYSTEM",
            ip_address="127.0.0.1",
            correlation_id=uuid.uuid4(),
            previous_hash="hash_genesis_v1",
            current_hash="hash_block3_duplicate_index2_v1",
            audit_chain_index=2,
            chain_version=1,
            created_utc=datetime.now(timezone.utc)
        )
        session.add(log3)
        await session.commit()

        # Capture initial states to ensure they remain frozen
        log1_snap = (log1.current_hash, log1.audit_chain_index)
        log2_snap = (log2.current_hash, log2.audit_chain_index)
        log3_snap = (log3.current_hash, log3.audit_chain_index)

        # 2. RUN RECOVERY PROCEDURE
        # Calculate lineage link terminal hash
        logs_stmt = (
            select(ImmutableActivityLog)
            .filter(ImmutableActivityLog.temple_id == temple_id)
            .order_by(ImmutableActivityLog.audit_chain_index.asc(), ImmutableActivityLog.created_utc.asc())
        )
        logs_res = await session.execute(logs_stmt)
        all_logs = logs_res.scalars().all()
        last_log = all_logs[-1]
        parent_terminal_hash = last_log.current_hash

        # Identify duplicates
        duplicates = [{
            "audit_chain_index": 2,
            "records": [str(log2_id), str(log3_id)]
        }]
        evidence = {
            "duplicate_indices": duplicates,
            "terminal_hash": parent_terminal_hash
        }

        # Atomic writes inside a transaction
        incident_id = uuid.uuid4()
        incident = AuditChainIncident(
            id=incident_id,
            temple_id=temple_id,
            chain_version=1,
            incident_type="SEQUENCE_BREAK",
            severity="CRITICAL",
            detected_at=datetime.now(timezone.utc),
            resolved_at=datetime.now(timezone.utc),
            root_cause="Concurrent write race condition.",
            evidence_reference=evidence,
            resolution_summary="Sealed V1, initialized V2.",
            status="RESOLVED"
        )
        session.add(incident)

        v1_version = AuditChainVersion(
            id=uuid.uuid4(),
            temple_id=temple_id,
            chain_version=1,
            chain_status="SEALED",
            verification_status="FAIL",
            created_at=datetime.now(timezone.utc),
            sealed_at=datetime.now(timezone.utc),
            seal_reason="Sequence break duplicate index.",
            incident_id=incident_id,
            recovery_method="CHAIN_FORK_ARCHIVE"
        )
        session.add(v1_version)

        v2_version = AuditChainVersion(
            id=uuid.uuid4(),
            temple_id=temple_id,
            chain_version=2,
            chain_status="ACTIVE",
            verification_status="PASS",
            created_at=datetime.now(timezone.utc),
            parent_chain_version=1,
            parent_terminal_hash=parent_terminal_hash,
            incident_id=incident_id,
            recovery_method="CHAIN_FORK_ARCHIVE"
        )
        session.add(v2_version)

        # Write Genesis Block 1 (Version 2) using AuditChainWriter
        genesis_id = uuid.uuid4()
        created_utc = datetime.now(timezone.utc)
        genesis_hash = ActivityLogProcessor.calculate_log_hash(
            log_id=genesis_id,
            temple_id=temple_id,
            action_type="INITIALIZE",
            created_utc=created_utc,
            after_value={"parent_terminal_hash": parent_terminal_hash, "parent_chain_version": 1},
            prev_hash="0" * 64
        )

        await AuditChainWriter.write_record(
            db=session,
            entry_id=genesis_id,
            temple_id=temple_id,
            temple_code="TMP-RECOVER",
            tenant_name="Malottu Recovery Test Temple",
            module_name="SYSTEM",
            entity_name="AuditChain",
            entity_id="Version2",
            action_type="INITIALIZE",
            action_category="SECURITY",
            description=f"Genesis block V2",
            before_value=None,
            after_value={"parent_terminal_hash": parent_terminal_hash, "parent_chain_version": 1},
            performed_by_user_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
            performed_by_name="Audit Recovery Agent",
            performed_by_role="SUPER_ADMIN",
            masked_pii=None,
            hashed_pii=None,
            ip_address="127.0.0.1",
            correlation_id=uuid.uuid4(),
            request_id=None,
            severity="HIGH",
            risk_score=50,
            previous_hash="0" * 64,
            current_hash=genesis_hash,
            audit_chain_index=1,
            chain_version=2,
            created_utc=created_utc
        )

        # Transition operational state back to ACTIVE
        temple.operational_state = TempleOperationalState.ACTIVE
        await session.commit()

        # 3. VERIFY AND ASSERT
        # Test Case 1: Corrupted Chain Frozen & Unaltered
        # Reload logs and verify their content has not changed
        v1_logs_stmt = (
            select(ImmutableActivityLog)
            .filter(ImmutableActivityLog.temple_id == temple_id, ImmutableActivityLog.chain_version == 1)
            .order_by(ImmutableActivityLog.id)
        )
        v1_logs = (await session.execute(v1_logs_stmt)).scalars().all()
        assert len(v1_logs) == 3
        
        # Verify hashes and indices are exactly as snapshots
        l1 = [l for l in v1_logs if l.id == log1_id][0]
        l2 = [l for l in v1_logs if l.id == log2_id][0]
        l3 = [l for l in v1_logs if l.id == log3_id][0]
        assert (l1.current_hash, l1.audit_chain_index) == log1_snap
        assert (l2.current_hash, l2.audit_chain_index) == log2_snap
        assert (l3.current_hash, l3.audit_chain_index) == log3_snap

        # Test Case 2: Incident Record Certification
        incident_db = (await session.execute(
            select(AuditChainIncident).filter(AuditChainIncident.temple_id == temple_id)
        )).scalar_one()
        assert incident_db.status == "RESOLVED"
        assert incident_db.chain_version == 1
        assert incident_db.evidence_reference["terminal_hash"] == parent_terminal_hash
        assert len(incident_db.evidence_reference["duplicate_indices"]) == 1

        # Test Case 3: Chain Sealed & Handshake populated
        v1_db = (await session.execute(
            select(AuditChainVersion).filter(AuditChainVersion.temple_id == temple_id, AuditChainVersion.chain_version == 1)
        )).scalar_one()
        assert v1_db.chain_status == "SEALED"
        assert v1_db.verification_status == "FAIL"

        v2_db = (await session.execute(
            select(AuditChainVersion).filter(AuditChainVersion.temple_id == temple_id, AuditChainVersion.chain_version == 2)
        )).scalar_one()
        assert v2_db.chain_status == "ACTIVE"
        assert v2_db.verification_status == "PASS"
        assert v2_db.parent_terminal_hash == parent_terminal_hash
        assert v2_db.parent_chain_version == 1

        # Test Case 4: Cryptographic Verification PASS
        verify_res = await ChainVerificationService.verify_audit_chain(session, temple_id)
        assert verify_res["verified"] is True
        assert verify_res["status"] == "PASS"
        assert verify_res["total_logs"] == 1 # Only Genesis block for V2
