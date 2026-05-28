"""
Audit Logging Service — append-only, immutable, transaction-aware.

All methods use flush() only. The caller controls the commit boundary.
"""
import logging
import hashlib
import json
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional
from app.models.domain import AuditLog

logger = logging.getLogger(__name__)


class AuditService:
    @staticmethod
    async def log_action(
        db: AsyncSession,
        temple_id: Optional[UUID],
        user_id: Optional[UUID],
        role: Optional[str],
        module_name: str,
        action: str,
        action_type: str,
        entity_id: Optional[str] = None,
        old_value: Optional[dict] = None,
        new_value: Optional[dict] = None,
        ip_address: Optional[str] = None,
        details: str = "",
        approval_id: Optional[UUID] = None,
        content_hash: Optional[str] = None,
    ):
        """
        Append-only audit log creation.

        NEVER commits — always uses flush() so the caller's transaction
        boundary controls atomicity.  If the outer transaction rolls back,
        this audit row disappears with it (correct behaviour for atomic flows).
        """
        # Auto-generate content_hash from new_value when not provided
        if content_hash is None and new_value is not None:
            try:
                payload_str = json.dumps(new_value, sort_keys=True, default=str)
                content_hash = hashlib.sha256(payload_str.encode()).hexdigest()
            except (TypeError, ValueError):
                pass

        audit = AuditLog(
            temple_id=temple_id,
            user_id=user_id,
            role=role,
            module_name=module_name,
            action=action,
            action_type=action_type,
            entity_id=entity_id,
            old_value=old_value,
            new_value=new_value,
            ip_address=ip_address,
            details=details,
            approval_id=approval_id,
            content_hash=content_hash,
        )
        db.add(audit)
        await db.flush()
        logger.info(
            "Audit log staged: %s -> %s for entity %s",
            module_name, action, entity_id,
        )
