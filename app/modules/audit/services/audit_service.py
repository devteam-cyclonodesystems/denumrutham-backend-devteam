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
        
        # Centralized Activity Logs Integration
        try:
            from app.modules.audit.services.activity_log_service import ActivityLogService
            from app.models.domain import User
            from sqlalchemy.future import select
            from uuid import UUID
            
            perf_name = "System"
            perf_role = role or "SYSTEM"
            if user_id:
                user_uuid = UUID(str(user_id))
                user_res = await db.execute(select(User).filter(User.id == user_uuid))
                user_obj = user_res.scalar_one_or_none()
                if user_obj:
                    perf_name = user_obj.name
                    perf_role = user_obj.role or role or "STAFF"
            
            severity, risk_score = ActivityLogService.determine_risk_and_severity(module_name, action)
            
            # Formulate Clean Entity Name
            ent_name = module_name
            if action and "_" in action:
                parts = action.split("_")
                if len(parts) > 0:
                    ent_name = parts[0].capitalize()
            
            await ActivityLogService.emit_event(
                db=db,
                temple_id=UUID(str(temple_id)) if temple_id else UUID("00000000-0000-0000-0000-000000000000"),
                module_name=module_name,
                entity_name=ent_name,
                entity_id=entity_id,
                action_type=action_type or action,
                action_category=action,
                description=details or f"{action} action performed on {module_name}",
                before_value=old_value,
                after_value=new_value,
                performed_by_user_id=UUID(str(user_id)) if user_id else None,
                performed_by_name=perf_name,
                performed_by_role=perf_role,
                ip_address=ip_address or "127.0.0.1",
                severity=severity,
                risk_score=risk_score
            )
        except Exception as e:
            logger.error(f"Failed to propagate audit log to centralized activity logs: {str(e)}", exc_info=True)

        logger.info(
            "Audit log staged: %s -> %s for entity %s",
            module_name, action, entity_id,
        )
