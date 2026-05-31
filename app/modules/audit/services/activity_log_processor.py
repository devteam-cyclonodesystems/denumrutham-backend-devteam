import json
import hashlib
import logging
from datetime import datetime, timezone
from uuid import UUID
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.modules.audit.models.audit_models import ActivityOutbox, ImmutableActivityLog
from app.modules.temple_management.models.temple_models import Temple

logger = logging.getLogger(__name__)

class ActivityLogProcessor:
    @staticmethod
    def calculate_log_hash(
        log_id: UUID,
        temple_id: UUID,
        action_type: str,
        created_utc: datetime,
        after_value: Any,
        prev_hash: str
    ) -> str:
        """Calculate the cryptographic signature for a log entry."""
        hasher = hashlib.sha256()
        hasher.update(str(log_id).encode())
        hasher.update(str(temple_id).encode())
        hasher.update(str(action_type).encode())
        
        # Standardize timezone to UTC and format consistently
        if created_utc.tzinfo is not None:
            utc_dt = created_utc.astimezone(timezone.utc)
        else:
            utc_dt = created_utc.replace(tzinfo=timezone.utc)
        dt_str = utc_dt.strftime("%Y-%m-%dT%H:%M:%S.%f")
        hasher.update(dt_str.encode())
        
        serialized_after = json.dumps(after_value, default=str, sort_keys=True) if after_value is not None else "null"
        hasher.update(serialized_after.encode())
        hasher.update(str(prev_hash).encode())
        
        return hasher.hexdigest()

    @staticmethod
    async def process_outbox(db: AsyncSession) -> int:
        """
        Poll and process activity outbox records.
        Returns the count of successfully processed entries.
        """
        # Fetch up to 50 outbox entries (ordered chronologically)
        # Using with_for_update(skip_locked=True) to avoid concurrency locks on scale workers
        stmt = (
            select(ActivityOutbox)
            .order_by(ActivityOutbox.created_at.asc())
            .limit(50)
            .with_for_update(skip_locked=True)
        )
        res = await db.execute(stmt)
        entries = res.scalars().all()
        
        if not entries:
            return 0
            
        processed_count = 0
        
        for entry in entries:
            try:
                # 1. Fetch Temple Code and Tenant Name
                temple_stmt = select(Temple).filter(Temple.id == entry.temple_id)
                temple_res = await db.execute(temple_stmt)
                temple = temple_res.scalar_one_or_none()
                
                temple_code = temple.temple_code if (temple and temple.temple_code) else "SYSTEM"
                tenant_name = temple.name if temple else "Denumrutham System"
                
                # 2. Lock the audit chain of this tenant and get the latest index/hash
                chain_stmt = (
                    select(ImmutableActivityLog)
                    .filter(ImmutableActivityLog.temple_id == entry.temple_id)
                    .order_by(ImmutableActivityLog.audit_chain_index.desc())
                    .limit(1)
                    .with_for_update()
                )
                chain_res = await db.execute(chain_stmt)
                latest_log = chain_res.scalar_one_or_none()
                
                if latest_log:
                    prev_hash = latest_log.current_hash
                    next_index = latest_log.audit_chain_index + 1
                else:
                    prev_hash = "0" * 64
                    next_index = 1
                    
                # 3. Establish timing timestamp
                # Using timezone-aware UTC datetime
                created_utc = datetime.now(timezone.utc)
                
                # 4. Cryptographically compute Current Hash
                curr_hash = ActivityLogProcessor.calculate_log_hash(
                    log_id=entry.id,
                    temple_id=entry.temple_id,
                    action_type=entry.action_type,
                    created_utc=created_utc,
                    after_value=entry.after_value,
                    prev_hash=prev_hash
                )
                
                # 5. Create immutable log entry
                log_record = ImmutableActivityLog(
                    id=entry.id, # Keep same correlation id / UUID
                    temple_id=entry.temple_id,
                    temple_code=temple_code,
                    tenant_name=tenant_name,
                    module_name=entry.module_name,
                    entity_name=entry.entity_name,
                    entity_id=entry.entity_id,
                    action_type=entry.action_type,
                    action_category=entry.action_category,
                    description=entry.description,
                    before_value=entry.before_value,
                    after_value=entry.after_value,
                    performed_by_user_id=entry.performed_by_user_id,
                    performed_by_name=entry.performed_by_name,
                    performed_by_role=entry.performed_by_role,
                    masked_pii=entry.masked_pii,
                    hashed_pii=entry.hashed_pii,
                    ip_address=entry.ip_address,
                    correlation_id=entry.correlation_id,
                    request_id=entry.request_id,
                    severity=entry.severity,
                    risk_score=entry.risk_score,
                    previous_hash=prev_hash,
                    current_hash=curr_hash,
                    audit_chain_index=next_index,
                    created_utc=created_utc
                )
                
                db.add(log_record)
                
                # 6. Delete entry from Outbox queue
                await db.delete(entry)
                
                processed_count += 1
                logger.info(f"Processed outbox entry {entry.id} into audit chain index {next_index}")
                
            except Exception as e:
                logger.error(f"Failed to process activity outbox entry {entry.id}: {str(e)}", exc_info=True)
                # Continue processing other outbox entries to avoid blocking queue
                continue
                
        # Commit the batch changes
        await db.commit()
        return processed_count

    @staticmethod
    async def process_outbox_task() -> int:
        """Background task wrapper that opens a database session and processes the outbox."""
        from app.core.database.database import AsyncSessionLocal
        from sqlalchemy import text
        
        async with AsyncSessionLocal() as db:
            try:
                # Set RLS session variables for background process context
                if db.bind.dialect.name != "sqlite":
                    await db.execute(text("SELECT set_config('app.current_temple_id', '', false)"))
                    await db.execute(text("SELECT set_config('app.current_role', 'SUPER_ADMIN', false)"))
                
                count = await ActivityLogProcessor.process_outbox(db)
                return count
            except Exception as e:
                logger.error(f"Error in background activity log processor task: {str(e)}", exc_info=True)
                return 0
