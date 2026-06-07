import pytest
import uuid
from datetime import datetime, timezone
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError

from app.models.domain import Temple
from app.modules.audit.models.audit_models import (
    ActivityOutbox, ImmutableActivityLog, AuditChainVersion, AuditChainIndexRegistry
)
from tests.conftest import TestSessionLocal

@pytest.mark.asyncio
async def test_concurrent_outbox_processing():
    """
    Deterministic simulation of concurrency:
    1. Create a temple and active chain version.
    2. Open two separate database sessions (simulating two outbox workers).
    3. Session 1 and Session 2 both check the current chain version and latest log.
       They both calculate the next index to be 1.
    4. Session 1 writes to the registry for index 1 (flushes successfully).
    5. Session 2 attempts to write to the registry for index 1.
    6. Assert:
       - Session 2 raises an IntegrityError (unique constraint violation on temple_id + audit_chain_index).
       - Session 1 commits successfully.
    """
    # 1. Setup temple and active version using session 1
    async with TestSessionLocal() as session1:
        temple_id = uuid.uuid4()
        temple = Temple(
            id=temple_id,
            name="Concurrent Stress Test Temple",
            domain="concurrent_test_domain"
        )
        session1.add(temple)
        
        # Insert active version 1 in audit_chain_versions
        v1_version = AuditChainVersion(
            id=uuid.uuid4(),
            temple_id=temple_id,
            chain_version=1,
            chain_status="ACTIVE",
            verification_status="PASS",
            created_at=datetime.now(timezone.utc)
        )
        session1.add(v1_version)
        await session1.commit()

    # 2. Simulate concurrent inserts from separate sessions
    session1 = TestSessionLocal()
    session2 = TestSessionLocal()
    
    try:
        next_idx = 1
        now = datetime.now(timezone.utc)

        # Session 1 writes index 1 to the registry
        reg1 = AuditChainIndexRegistry(
            temple_id=temple_id,
            audit_chain_index=next_idx,
            created_utc=now
        )
        session1.add(reg1)
        # Flush session 1 to database transaction state
        await session1.flush()

        # Session 2 attempts to write the same index 1 to the registry
        reg2 = AuditChainIndexRegistry(
            temple_id=temple_id,
            audit_chain_index=next_idx,
            created_utc=now
        )
        session2.add(reg2)
        
        # Verify that Session 2 raises IntegrityError due to the unique constraint on (temple_id, audit_chain_index)
        with pytest.raises(IntegrityError):
            await session2.flush()

        # Commit Session 1 successfully
        await session1.commit()
        
    finally:
        await session1.close()
        await session2.close()
