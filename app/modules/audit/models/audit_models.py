import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, Integer, DateTime, BigInteger, JSON, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.core.database.database import Base

def utcnow():
    return datetime.now(timezone.utc)

class ImmutableActivityLog(Base):
    """Immutable, append-only historical database record of staff action."""
    __tablename__ = "immutable_activity_logs"
    __table_args__ = (
        {
            "postgresql_partition_by": "RANGE (created_utc)"
        }
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    temple_code = Column(String(50), nullable=False)
    tenant_name = Column(String(150), nullable=False)
    module_name = Column(String(100), nullable=False)
    entity_name = Column(String(100), nullable=False)
    entity_id = Column(String(100), nullable=True)
    action_type = Column(String(100), nullable=False)
    action_category = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    before_value = Column(JSON, nullable=True)
    after_value = Column(JSON, nullable=True)
    performed_by_user_id = Column(UUID(as_uuid=True), nullable=False)
    performed_by_name = Column(String(255), nullable=False)
    performed_by_role = Column(String(100), nullable=False)
    
    # Hybrid PII fields
    masked_pii = Column(JSON, nullable=True)
    hashed_pii = Column(JSON, nullable=True)
    
    # Fingerprint fields
    ip_address = Column(String(45), nullable=False)
    device_info = Column(Text, nullable=True)
    browser_info = Column(Text, nullable=True)
    operating_system = Column(String(100), nullable=True)
    
    # Trace elements
    correlation_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    request_id = Column(String(100), nullable=True)
    session_id = Column(String(100), nullable=True)
    
    # Severity & Risk Rating
    severity = Column(String(50), nullable=False, default="LOW")
    risk_score = Column(Integer, nullable=False, default=10)
    
    # Cryptographic Chain Validation
    previous_hash = Column(String(64), nullable=False)
    current_hash = Column(String(64), nullable=False)
    audit_chain_index = Column(BigInteger, nullable=False)
    chain_version = Column(Integer, nullable=False, default=1)
    
    # Created Timestamp (part of composite primary key for table partitioning)
    created_utc = Column(DateTime(timezone=True), primary_key=True, default=utcnow, index=True)


class ActivityOutbox(Base):
    """Transactional Outbox buffering activity events to keep transaction routes non-blocking."""
    __tablename__ = "activity_outbox"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), nullable=False)
    module_name = Column(String(100), nullable=False)
    entity_name = Column(String(100), nullable=False)
    entity_id = Column(String(100), nullable=True)
    action_type = Column(String(100), nullable=False)
    action_category = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    before_value = Column(JSON, nullable=True)
    after_value = Column(JSON, nullable=True)
    performed_by_user_id = Column(UUID(as_uuid=True), nullable=False)
    performed_by_name = Column(String(255), nullable=False)
    performed_by_role = Column(String(100), nullable=False)
    masked_pii = Column(JSON, nullable=True)
    hashed_pii = Column(JSON, nullable=True)
    ip_address = Column(String(45), nullable=False)
    correlation_id = Column(UUID(as_uuid=True), nullable=False)
    request_id = Column(String(100), nullable=True)
    severity = Column(String(50), nullable=False, default="LOW")
    risk_score = Column(Integer, nullable=False, default=10)
    created_at = Column(DateTime(timezone=True), default=utcnow)


from sqlalchemy import event

@event.listens_for(ImmutableActivityLog, "before_update")
def block_updates(mapper, connection, target):
    raise PermissionError("Mutation Denied: Activity log entries are strictly immutable.")

@event.listens_for(ImmutableActivityLog, "before_delete")
def block_deletes(mapper, connection, target):
    raise PermissionError("Mutation Denied: Activity log entries are strictly immutable.")


def to_uuid_db(val, dialect_name):
    if not val:
        return None
    import uuid
    if isinstance(val, str):
        try:
            val = uuid.UUID(val)
        except ValueError:
            return val
    if dialect_name == "sqlite":
        return val.hex
    return val

# ═══════════════════════════════════════════════════════════════════════
# after_insert Hooks to Propagate Module-Specific Audits to Outbox
# ═══════════════════════════════════════════════════════════════════════

from app.modules.bookings.models.archana import ArchanaBookingAudit
from app.modules.temple_management.models.offering import OfferingAuditLog

@event.listens_for(ArchanaBookingAudit, "after_insert")
def prop_archana_audit(mapper, connection, target):
    try:
        import uuid
        import json
        from datetime import datetime, timezone
        from sqlalchemy import text
        from app.modules.audit.services.activity_log_service import ActivityLogService
        
        dialect_name = connection.dialect.name
        
        # 1. Fetch details of the booking
        bid_bind = to_uuid_db(target.booking_id, dialect_name)
        b_res = connection.execute(
            text("SELECT temple_id, ref_id, grand_total, primary_devotee_name FROM archana_bookings WHERE id = :bid"),
            {"bid": bid_bind}
        ).first()
        
        if b_res:
            temple_id_raw, ref_id, grand_total, devotee_name = b_res
            temple_id = uuid.UUID(str(temple_id_raw)) if temple_id_raw else None
        else:
            temple_id, ref_id, grand_total, devotee_name = None, None, 0.0, ""
            
        # 2. Fetch actor details
        perf_name = "System"
        perf_role = "SYSTEM"
        if target.actor_id:
            actor_bind = to_uuid_db(target.actor_id, dialect_name)
            u_res = connection.execute(
                text("SELECT name, role FROM users WHERE id = :uid"),
                {"uid": actor_bind}
            ).first()
            if u_res:
                perf_name, perf_role = u_res
                
        # 3. Clean secrets and format PII mapping
        before_clean = ActivityLogService.redact_secrets(target.old_state) if target.old_state else None
        after_clean = ActivityLogService.redact_secrets(target.new_state) if target.new_state else None
        masked_pii, hashed_pii = ActivityLogService.extract_and_process_pii(before_clean, after_clean)
        
        severity, risk_score = ActivityLogService.determine_risk_and_severity("BOOKINGS", target.action)
        
        # 4. Insert into transactional outbox
        outbox_id = uuid.uuid4()
        connection.execute(
            text("""
                INSERT INTO activity_outbox (
                    id, temple_id, module_name, entity_name, entity_id, 
                    action_type, action_category, description, before_value, after_value, 
                    performed_by_user_id, performed_by_name, performed_by_role, 
                    masked_pii, hashed_pii, ip_address, correlation_id, severity, risk_score, created_at
                ) VALUES (
                    :id, :temple_id, :module_name, :entity_name, :entity_id, 
                    :action_type, :action_category, :description, :before_value, :after_value, 
                    :performed_by_user_id, :performed_by_name, :performed_by_role, 
                    :masked_pii, :hashed_pii, :ip_address, :correlation_id, :severity, :risk_score, :created_at
                )
            """),
            {
                "id": to_uuid_db(outbox_id, dialect_name),
                "temple_id": to_uuid_db(temple_id if temple_id else uuid.UUID("00000000-0000-0000-0000-000000000000"), dialect_name),
                "module_name": "BOOKINGS",
                "entity_name": "ArchanaBooking",
                "entity_id": ref_id or (str(target.booking_id) if target.booking_id else None),
                "action_type": target.action,
                "action_category": "ARCHANA_RITUAL",
                "description": f"Archana ritual booking action '{target.action}' for devotee '{devotee_name}' (Total: ₹{grand_total})",
                "before_value": json.dumps(before_clean) if before_clean else None,
                "after_value": json.dumps(after_clean) if after_clean else None,
                "performed_by_user_id": to_uuid_db(target.actor_id if target.actor_id else uuid.UUID("00000000-0000-0000-0000-000000000000"), dialect_name),
                "performed_by_name": perf_name,
                "performed_by_role": perf_role,
                "masked_pii": json.dumps(masked_pii) if masked_pii else None,
                "hashed_pii": json.dumps(hashed_pii) if hashed_pii else None,
                "ip_address": "127.0.0.1",
                "correlation_id": to_uuid_db(uuid.uuid4(), dialect_name),
                "severity": severity,
                "risk_score": risk_score,
                "created_at": datetime.now(timezone.utc)
            }
        )
    except Exception as e:
        import logging
        logging.getLogger("tms.audit").error(f"Failed in prop_archana_audit hook: {str(e)}", exc_info=True)


@event.listens_for(OfferingAuditLog, "after_insert")
def prop_offering_audit(mapper, connection, target):
    try:
        import uuid
        import json
        from datetime import datetime, timezone
        from sqlalchemy import text
        from app.modules.audit.services.activity_log_service import ActivityLogService
        
        dialect_name = connection.dialect.name
        
        # 1. Fetch offering reference details
        oid_bind = to_uuid_db(target.offering_id, dialect_name)
        off_res = connection.execute(
            text("SELECT offering_number, donor_name, total_amount FROM offerings WHERE id = :oid"),
            {"oid": oid_bind}
        ).first() if target.offering_id else None
        
        if off_res:
            off_num, donor_name, total_amount = off_res
        else:
            off_num, donor_name, total_amount = None, "", 0.0
            
        # 2. Match performer details
        perf_name = target.changed_by or "System"
        perf_role = "STAFF"
        performed_by_user_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
        
        if target.changed_by:
            try:
                user_uuid = uuid.UUID(str(target.changed_by))
                uid_bind = to_uuid_db(user_uuid, dialect_name)
                u_res = connection.execute(
                    text("SELECT name, role FROM users WHERE id = :uid"),
                    {"uid": uid_bind}
                ).first()
                if u_res:
                    perf_name, perf_role = u_res
                    performed_by_user_id = user_uuid
            except ValueError:
                pass
                
        # 3. Clean secrets and process hybrid PII
        before_clean = ActivityLogService.redact_secrets(target.old_value) if target.old_value else None
        after_clean = ActivityLogService.redact_secrets(target.new_value) if target.new_value else None
        masked_pii, hashed_pii = ActivityLogService.extract_and_process_pii(before_clean, after_clean)
        
        severity, risk_score = ActivityLogService.determine_risk_and_severity("DONATIONS", target.action_type)
        
        # 4. Write to activity outbox queue
        outbox_id = uuid.uuid4()
        connection.execute(
            text("""
                INSERT INTO activity_outbox (
                    id, temple_id, module_name, entity_name, entity_id, 
                    action_type, action_category, description, before_value, after_value, 
                    performed_by_user_id, performed_by_name, performed_by_role, 
                    masked_pii, hashed_pii, ip_address, correlation_id, severity, risk_score, created_at
                ) VALUES (
                    :id, :temple_id, :module_name, :entity_name, :entity_id, 
                    :action_type, :action_category, :description, :before_value, :after_value, 
                    :performed_by_user_id, :performed_by_name, :performed_by_role, 
                    :masked_pii, :hashed_pii, :ip_address, :correlation_id, :severity, :risk_score, :created_at
                )
            """),
            {
                "id": to_uuid_db(outbox_id, dialect_name),
                "temple_id": to_uuid_db(target.temple_id, dialect_name),
                "module_name": "DONATIONS",
                "entity_name": "Offering",
                "entity_id": off_num or (str(target.offering_id) if target.offering_id else None),
                "action_type": target.action_type,
                "action_category": "OFFERING_OPERATION",
                "description": f"Offering action '{target.action_type}' recorded for donor '{donor_name}' (Total: ₹{total_amount})",
                "before_value": json.dumps(before_clean) if before_clean else None,
                "after_value": json.dumps(after_clean) if after_clean else None,
                "performed_by_user_id": to_uuid_db(performed_by_user_id, dialect_name),
                "performed_by_name": perf_name,
                "performed_by_role": perf_role,
                "masked_pii": json.dumps(masked_pii) if masked_pii else None,
                "hashed_pii": json.dumps(hashed_pii) if hashed_pii else None,
                "ip_address": target.ip_address or "127.0.0.1",
                "correlation_id": to_uuid_db(uuid.uuid4(), dialect_name),
                "severity": severity,
                "risk_score": risk_score,
                "created_at": datetime.now(timezone.utc)
            }
        )
    except Exception as e:
        import logging
        logging.getLogger("tms.audit").error(f"Failed in prop_offering_audit hook: {str(e)}", exc_info=True)


class AuditGovernanceConfig(Base):
    """
    Governance configuration for the audit log system.
    Supports Retention Policies, Export Policies, Severity Mapping, Alert Thresholds,
    and Audit Access Controls.
    
    Includes versioning so that modifications to this configuration are themselves
    immutable audit events recorded in the chain (Audit-of-Audit).
    """
    __tablename__ = "audit_governance_configs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id"), nullable=False, unique=True, index=True)
    
    # Retention Policy in days (e.g. 90, 365, etc.)
    retention_days = Column(Integer, nullable=False, default=365)
    
    # Export policies configuration (stored as JSON)
    export_policy = Column(JSON, nullable=True, default=dict)
    
    # Severity mapping configuration (stored as JSON)
    severity_mapping = Column(JSON, nullable=True, default=dict)
    
    # Alert thresholds (stored as JSON)
    alert_thresholds = Column(JSON, nullable=True, default=dict)
    
    # Audit Access Controls (role-based permissions to read logs, stored as JSON)
    access_controls = Column(JSON, nullable=True, default=dict)
    
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AuditIntegrityVerificationReport(Base):
    """Tracks the results of cryptographic chain audits for each temple."""
    __tablename__ = "audit_integrity_verification_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False, index=True)
    verified_at = Column(DateTime(timezone=True), default=utcnow)
    status = Column(String, nullable=False)  # "PASS" | "FAIL"
    total_logs = Column(Integer, nullable=False, default=0)
    failed_logs_count = Column(Integer, nullable=False, default=0)
    failed_log_ids = Column(JSON, nullable=True)  # List of failed log UUIDs as JSON array
    details = Column(Text, nullable=True)


class AuditChainIncident(Base):
    """Audit incident ledger tracking sequence breaks, bypass attempts, etc."""
    __tablename__ = "audit_chain_incidents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False)
    chain_version = Column(Integer, nullable=False)
    incident_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False, default="HIGH")
    detected_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    root_cause = Column(Text, nullable=False)
    evidence_reference = Column(JSON, nullable=False)
    resolution_summary = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="OPEN")


class AuditChainVersion(Base):
    """Tracks active/sealed audit chain versions and their cryptographic handshakes."""
    __tablename__ = "audit_chain_versions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), nullable=False)
    chain_version = Column(Integer, nullable=False)
    chain_status = Column(String(20), nullable=False, default="ACTIVE")
    verification_status = Column(String(20), nullable=False, default="PASS")
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    sealed_at = Column(DateTime(timezone=True), nullable=True)
    seal_reason = Column(Text, nullable=True)
    parent_chain_version = Column(Integer, nullable=True)
    parent_terminal_hash = Column(String(64), nullable=True)
    incident_id = Column(UUID(as_uuid=True), ForeignKey("audit_chain_incidents.id", ondelete="SET NULL"), nullable=True)
    recovery_method = Column(String(50), nullable=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class AuditChainIndexRegistry(Base):
    """Enforces absolute uniqueness for temple_id and audit_chain_index combinations."""
    __tablename__ = "audit_chain_index_registry"

    temple_id = Column(UUID(as_uuid=True), ForeignKey("temples.id", ondelete="CASCADE"), primary_key=True)
    audit_chain_index = Column(BigInteger, primary_key=True)
    created_utc = Column(DateTime(timezone=True), nullable=False)



