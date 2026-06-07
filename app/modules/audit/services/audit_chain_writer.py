import logging
from datetime import datetime
from uuid import UUID
from typing import Any, Optional
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.audit.models.audit_models import ImmutableActivityLog, AuditChainIndexRegistry

logger = logging.getLogger(__name__)

class AuditChainWriter:
    """
    Dedicated single write path for writing activity logs and registry entries.
    Enforces writing to both the registry lookup table and the partitioned activity logs.
    """
    @staticmethod
    async def write_record(
        db: AsyncSession,
        entry_id: UUID,
        temple_id: UUID,
        temple_code: str,
        tenant_name: str,
        module_name: str,
        entity_name: str,
        entity_id: Optional[str],
        action_type: str,
        action_category: str,
        description: str,
        before_value: Any,
        after_value: Any,
        performed_by_user_id: UUID,
        performed_by_name: str,
        performed_by_role: str,
        masked_pii: Any,
        hashed_pii: Any,
        ip_address: str,
        correlation_id: UUID,
        request_id: Optional[str],
        severity: str,
        risk_score: int,
        previous_hash: str,
        current_hash: str,
        audit_chain_index: int,
        chain_version: int,
        created_utc: datetime
    ) -> ImmutableActivityLog:
        # 1. Enforce writing to the registry lookup table to check uniqueness
        registry_entry = AuditChainIndexRegistry(
            temple_id=temple_id,
            audit_chain_index=audit_chain_index,
            created_utc=created_utc
        )
        db.add(registry_entry)
        await db.flush()  # Flush immediately to catch any index duplicates early

        # 2. Write to the partitioned ImmutableActivityLog table
        log_record = ImmutableActivityLog(
            id=entry_id,
            temple_id=temple_id,
            temple_code=temple_code,
            tenant_name=tenant_name,
            module_name=module_name,
            entity_name=entity_name,
            entity_id=entity_id,
            action_type=action_type,
            action_category=action_category,
            description=description,
            before_value=before_value,
            after_value=after_value,
            performed_by_user_id=performed_by_user_id,
            performed_by_name=performed_by_name,
            performed_by_role=performed_by_role,
            masked_pii=masked_pii,
            hashed_pii=hashed_pii,
            ip_address=ip_address,
            correlation_id=correlation_id,
            request_id=request_id,
            severity=severity,
            risk_score=risk_score,
            previous_hash=previous_hash,
            current_hash=current_hash,
            audit_chain_index=audit_chain_index,
            chain_version=chain_version,
            created_utc=created_utc
        )
        db.add(log_record)
        return log_record
