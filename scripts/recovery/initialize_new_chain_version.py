import asyncio
import logging
import uuid
import json
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.future import select

from app.core.database.database import AsyncSessionLocal
from app.modules.temple_management.models.temple_models import Temple
from app.modules.audit.models.audit_models import ImmutableActivityLog
from app.modules.audit.services.audit_chain_writer import AuditChainWriter
from app.modules.audit.services.activity_log_processor import ActivityLogProcessor
from app.modules.governance.services.operational_state_service import OperationalStateService
from app.modules.governance.models.operational_states import TempleOperationalState

# Setup basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tms.recovery")

TEMPLE_ID = uuid.UUID("f96f45a1-d3a3-422f-9260-abfcd8df1aaa")

async def run_recovery():
    logger.info(f"Starting audit chain recovery for temple {TEMPLE_ID}...")
    
    async with AsyncSessionLocal() as db:
        # 1. Fetch Temple
        temple_stmt = select(Temple).filter(Temple.id == TEMPLE_ID)
        temple_res = await db.execute(temple_stmt)
        temple = temple_res.scalar_one_or_none()
        
        if not temple:
            logger.error(f"Temple {TEMPLE_ID} not found in database. Exiting.")
            return
            
        logger.info(f"Found temple: {temple.name} (Code: {temple.temple_code})")
        
        # 2. Query all logs for version 1 to calculate parent terminal hash and find duplicates
        logs_stmt = (
            select(ImmutableActivityLog)
            .filter(ImmutableActivityLog.temple_id == TEMPLE_ID)
            .order_by(ImmutableActivityLog.audit_chain_index.asc())
        )
        logs_res = await db.execute(logs_stmt)
        logs = logs_res.scalars().all()
        
        if not logs:
            logger.error("No audit logs found for Version 1. Recovery cannot proceed without historical chain.")
            return
            
        last_log = logs[-1]
        parent_terminal_hash = last_log.current_hash
        logger.info(f"Version 1 terminal hash: {parent_terminal_hash} at index {last_log.audit_chain_index}")
        
        # Identify duplicates and sequence breaks
        index_map = {}
        duplicates = []
        sequence_breaks = []
        
        for idx, log in enumerate(logs):
            index_map.setdefault(log.audit_chain_index, []).append(log)
            expected_index = idx + 1
            if log.audit_chain_index != expected_index:
                sequence_breaks.append({
                    "expected": expected_index,
                    "got": log.audit_chain_index,
                    "log_id": str(log.id)
                })
                
        for idx, log_list in index_map.items():
            if len(log_list) > 1:
                duplicates.append({
                    "audit_chain_index": idx,
                    "records": [
                        {
                            "id": str(l.id),
                            "correlation_id": str(l.correlation_id),
                            "created_utc": l.created_utc.isoformat() if l.created_utc else None
                        } for l in log_list
                    ]
                })
                
        logger.info(f"Found {len(duplicates)} duplicate indices and {len(sequence_breaks)} sequence breaks.")
        
        evidence = {
            "duplicate_indices": duplicates,
            "sequence_breaks": sequence_breaks,
            "verification_failure": "Sequence break: expected index 65, found 64",
            "terminal_log_id": str(last_log.id),
            "terminal_hash": parent_terminal_hash,
            "terminal_index": last_log.audit_chain_index,
            "audit_log_snapshot": [
                {
                    "id": str(l.id),
                    "index": l.audit_chain_index,
                    "hash": l.current_hash,
                    "action": l.action_type
                } for l in logs[max(0, len(logs)-15):] # Snapshot of last 15 entries
            ]
        }
        
        # 3. Perform atomic operations
        try:
            # Create incident ledger record
            incident_id = uuid.uuid4()
            incident_stmt = text("""
                INSERT INTO audit_chain_incidents (
                    id, temple_id, chain_version, incident_type, severity, detected_at, resolved_at, root_cause, evidence_reference, resolution_summary, status
                ) VALUES (
                    :id, :temple_id, :chain_version, :incident_type, :severity, :detected_at, :resolved_at, :root_cause, :evidence_reference, :resolution_summary, :status
                )
            """)
            await db.execute(
                incident_stmt,
                {
                    "id": incident_id,
                    "temple_id": TEMPLE_ID,
                    "chain_version": 1,
                    "incident_type": "SEQUENCE_BREAK",
                    "severity": "CRITICAL",
                    "detected_at": datetime.now(timezone.utc),
                    "resolved_at": datetime.now(timezone.utc),
                    "root_cause": "Concurrency race between multiple outbox workers caused duplicate audit_chain_index values.",
                    "evidence_reference": json.dumps(evidence),
                    "resolution_summary": "Sealed corrupt Chain Version 1. Initialized new Chain Version 2 with cryptographic lineage handshake link.",
                    "status": "RESOLVED"
                }
            )
            logger.info("Inserted resolved incident record in audit_chain_incidents.")
            
            # Insert sealed Version 1 record in audit_chain_versions
            v1_id = uuid.uuid4()
            v1_stmt = text("""
                INSERT INTO audit_chain_versions (
                    id, temple_id, chain_version, chain_status, verification_status, created_at, sealed_at, seal_reason, incident_id, recovery_method
                ) VALUES (
                    :id, :temple_id, :chain_version, :chain_status, :verification_status, :created_at, :sealed_at, :seal_reason, :incident_id, :recovery_method
                )
            """)
            await db.execute(
                v1_stmt,
                {
                    "id": v1_id,
                    "temple_id": TEMPLE_ID,
                    "chain_version": 1,
                    "chain_status": "SEALED",
                    "verification_status": "FAIL",
                    "created_at": logs[0].created_utc or datetime.now(timezone.utc),
                    "sealed_at": datetime.now(timezone.utc),
                    "seal_reason": "Cryptographic sequence break detected at index 65.",
                    "incident_id": incident_id,
                    "recovery_method": "CHAIN_FORK_ARCHIVE"
                }
            )
            logger.info("Inserted sealed Chain Version 1 record in audit_chain_versions.")
            
            # Insert ACTIVE Version 2 record in audit_chain_versions
            v2_id = uuid.uuid4()
            v2_stmt = text("""
                INSERT INTO audit_chain_versions (
                    id, temple_id, chain_version, chain_status, verification_status, created_at, parent_chain_version, parent_terminal_hash, incident_id, recovery_method
                ) VALUES (
                    :id, :temple_id, :chain_version, :chain_status, :verification_status, :created_at, :parent_chain_version, :parent_terminal_hash, :incident_id, :recovery_method
                )
            """)
            await db.execute(
                v2_stmt,
                {
                    "id": v2_id,
                    "temple_id": TEMPLE_ID,
                    "chain_version": 2,
                    "chain_status": "ACTIVE",
                    "verification_status": "PASS",
                    "created_at": datetime.now(timezone.utc),
                    "parent_chain_version": 1,
                    "parent_terminal_hash": parent_terminal_hash,
                    "incident_id": incident_id,
                    "recovery_method": "CHAIN_FORK_ARCHIVE"
                }
            )
            logger.info("Inserted active Chain Version 2 record in audit_chain_versions.")
            
            # Write Genesis Block for Chain Version 2
            genesis_id = uuid.uuid4()
            created_utc = datetime.now(timezone.utc)
            
            # Calculate cryptographic hash for genesis block
            genesis_hash = ActivityLogProcessor.calculate_log_hash(
                log_id=genesis_id,
                temple_id=TEMPLE_ID,
                action_type="INITIALIZE",
                created_utc=created_utc,
                after_value={"parent_terminal_hash": parent_terminal_hash, "parent_chain_version": 1},
                prev_hash="0" * 64
            )
            
            await AuditChainWriter.write_record(
                db=db,
                entry_id=genesis_id,
                temple_id=TEMPLE_ID,
                temple_code=temple.temple_code or "SYSTEM",
                tenant_name=temple.name or "System",
                module_name="SYSTEM",
                entity_name="AuditChain",
                entity_id="Version2",
                action_type="INITIALIZE",
                action_category="SECURITY",
                description=f"Genesis block for Chain Version 2. Sealed parent terminal hash: {parent_terminal_hash}",
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
            logger.info("Wrote Genesis Block 1 (Version 2) to audit chain and index registry.")
            
            # Transition temple operational state back to ACTIVE
            await OperationalStateService.transition_to(
                db=db,
                temple_id=TEMPLE_ID,
                new_state=TempleOperationalState.ACTIVE,
                changed_by=None,
                reason="Audit chain recovery complete. Sealed Version 1 and initialized Version 2."
            )
            logger.info(f"Transitioned temple operational state back to ACTIVE.")
            
            # Commit the recovery transaction
            await db.commit()
            logger.info("RECOVERY TRANSACTION COMMITTED SUCCESSFULLY!")
            
        except Exception as e:
            logger.error(f"Error executing recovery transaction: {str(e)}", exc_info=True)
            await db.rollback()
            logger.error("Recovery transaction rolled back.")

if __name__ == "__main__":
    asyncio.run(run_recovery())
