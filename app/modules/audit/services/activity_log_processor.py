import json
import hashlib
import logging
import asyncio
from datetime import datetime, timezone
from uuid import UUID
from typing import Any, List, Optional
from abc import ABC, abstractmethod
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import text
from app.modules.audit.models.audit_models import ActivityOutbox, ImmutableActivityLog, AuditChainVersion
from app.modules.audit.services.audit_chain_writer import AuditChainWriter
from app.modules.temple_management.models.temple_models import Temple
from app.core.database.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

# Metrics for Queue Observability
class OutboxMetrics:
    worker_running: bool = False
    queue_depth: int = 0
    oldest_pending_event_age_seconds: int = 0
    total_processed: int = 0
    total_failed: int = 0
    total_retries: int = 0
    last_heartbeat: Optional[datetime] = None

# ---------------------------------------------------------------------------
# Abstract Event Broker Interface (Supports Kafka / RabbitMQ / Redis Streams migration)
# ---------------------------------------------------------------------------
class EventBroker(ABC):
    @abstractmethod
    async def poll_batch(self, db: AsyncSession, limit: int = 50) -> List[Any]:
        """Poll a batch of events from the underlying transport."""
        pass

    @abstractmethod
    async def acknowledge(self, db: AsyncSession, entry: Any) -> None:
        """Acknowledge successful consumption of the event."""
        pass


class DatabaseOutboxBroker(EventBroker):
    """SQLAlchemy Outbox implementation of the EventBroker interface."""
    
    async def poll_batch(self, db: AsyncSession, limit: int = 50) -> List[ActivityOutbox]:
        stmt = (
            select(ActivityOutbox)
            .order_by(ActivityOutbox.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())

    async def acknowledge(self, db: AsyncSession, entry: ActivityOutbox) -> None:
        await db.delete(entry)


# ---------------------------------------------------------------------------
# Activity Log Processor Subsystem
# ---------------------------------------------------------------------------
class ActivityLogProcessor:
    # Tracks in-memory processing failure counts for poison pill detection
    _failure_registry = {}

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
        """Backward-compatible entry point for polling and processing outbox logs."""
        return await ActivityLogProcessor.process_outbox_batch(db, DatabaseOutboxBroker(), limit=50)

    @classmethod
    async def process_outbox_batch(cls, db: AsyncSession, broker: EventBroker, limit: int = 50) -> int:
        """
        Poll and process activity outbox records.
        Returns the count of successfully processed entries.
        """
        entries = await broker.poll_batch(db, limit=limit)
        if not entries:
            return 0
            
        processed_count = 0
        processed_logs = []
        
        for entry in entries:
            try:
                # 1. Poison Pill Guard
                failure_count = cls._failure_registry.get(entry.id, 0)
                if failure_count >= 3:
                    logger.critical(
                        f"POISON PILL DETECTED! Outbox event {entry.id} failed 3 times. "
                        "Skipping and removing event to prevent head-of-line blocking."
                    )
                    cls._failure_registry.pop(entry.id, None)
                    await broker.acknowledge(db, entry)
                    OutboxMetrics.total_retries += 1
                    continue

                # Run each entry in a nested savepoint transaction to prevent partial success states
                async with db.begin_nested():
                    # 2. Idempotency Check: Explicitly verify if this event was already processed
                    dup_stmt = select(ImmutableActivityLog.id).filter(ImmutableActivityLog.id == entry.id).limit(1)
                    dup_res = await db.execute(dup_stmt)
                    if dup_res.scalar_one_or_none():
                        logger.warning(f"Idempotency Guard: Event {entry.id} already exists in immutable logs. Acknowledging outbox entry.")
                        await broker.acknowledge(db, entry)
                        continue

                    # 3. Fetch Temple Code and Tenant Name with row lock
                    temple_stmt = select(Temple).filter(Temple.id == entry.temple_id).with_for_update()
                    temple_res = await db.execute(temple_stmt)
                    temple = temple_res.scalar_one_or_none()
                    
                    temple_code = temple.temple_code if (temple and temple.temple_code) else "SYSTEM"
                    tenant_name = temple.name if temple else "Denumrutham System"
                    
                    # 4. Fetch the active chain version
                    version_stmt = (
                        select(AuditChainVersion.chain_version)
                        .filter(
                            AuditChainVersion.temple_id == entry.temple_id,
                            AuditChainVersion.chain_status == 'ACTIVE'
                        )
                        .limit(1)
                    )
                    version_res = await db.execute(version_stmt)
                    active_version = version_res.scalar() or 1

                    # 5. Lock the audit chain of this tenant and get the latest index/hash for the active version
                    chain_stmt = (
                        select(ImmutableActivityLog)
                        .filter(
                            ImmutableActivityLog.temple_id == entry.temple_id,
                            ImmutableActivityLog.chain_version == active_version
                        )
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
                        
                    created_utc = datetime.now(timezone.utc)
                    curr_hash = cls.calculate_log_hash(
                        log_id=entry.id,
                        temple_id=entry.temple_id,
                        action_type=entry.action_type,
                        created_utc=created_utc,
                        after_value=entry.after_value,
                        prev_hash=prev_hash
                    )
                    
                    # 6. Create registry lookup and immutable log entry via single writer service
                    log_record = await AuditChainWriter.write_record(
                        db=db,
                        entry_id=entry.id,
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
                        chain_version=active_version,
                        created_utc=created_utc
                    )
                    
                    # 7. Real-Time Verification Hook: Inline post-write validation
                    recalc = cls.calculate_log_hash(
                        log_id=log_record.id,
                        temple_id=log_record.temple_id,
                        action_type=log_record.action_type,
                        created_utc=log_record.created_utc,
                        after_value=log_record.after_value,
                        prev_hash=log_record.previous_hash
                    )
                    if log_record.current_hash != recalc:
                        raise ValueError(
                            f"Post-write validation failure: current_hash mismatch. "
                            f"Calculated {recalc}, got {log_record.current_hash}"
                        )
                    
                    await db.flush()  # Flush within nested transaction to enforce DB unique constraints
                    await broker.acknowledge(db, entry)
                    
                    processed_logs.append(log_record)
                    processed_count += 1
                    
                    # Clear failure count on success
                    cls._failure_registry.pop(entry.id, None)
                    logger.info(f"Processed outbox entry {entry.id} into audit chain index {next_index}")
                    
            except Exception as e:
                cls._failure_registry[entry.id] = cls._failure_registry.get(entry.id, 0) + 1
                OutboxMetrics.total_failed += 1
                logger.error(f"Failed to process activity outbox entry {entry.id}: {str(e)}", exc_info=True)
                # The nested transaction savepoint automatically rolls back changes for this entry
                continue

        # Commit overall transaction
        await db.commit()

        # Broadcast events via Redis Pub/Sub for real-time manager UI updates
        for log_record in processed_logs:
            try:
                from app.services.broadcast_service import BroadcastService
                log_data = {
                    "id": str(log_record.id),
                    "module_name": log_record.module_name,
                    "entity_name": log_record.entity_name,
                    "entity_id": log_record.entity_id,
                    "action_type": log_record.action_type,
                    "description": log_record.description,
                    "performed_by_name": log_record.performed_by_name,
                    "performed_by_role": log_record.performed_by_role,
                    "severity": log_record.severity,
                    "created_utc": log_record.created_utc.isoformat() if log_record.created_utc else None
                }
                await BroadcastService.publish_tenant_event(
                    temple_id=log_record.temple_id,
                    event_type="ACTIVITY_LOG_CREATED",
                    data=log_data
                )
            except Exception as e:
                logger.error(f"Failed to broadcast real-time activity log update: {str(e)}")

        return processed_count


# ---------------------------------------------------------------------------
# Background Polling Task (FastAPI Startup Worker)
# ---------------------------------------------------------------------------
async def run_outbox_worker(shutdown_event: asyncio.Event) -> None:
    """
    Non-blocking background loop that processes activity logs outbox.
    Implements exponential backoff (2s to 60s max) if database connections fail.
    Ensures per-process singleton protection.
    """
    if OutboxMetrics.worker_running:
        logger.warning("run_outbox_worker invoked but it is already running. Ignoring duplicate call.")
        return

    OutboxMetrics.worker_running = True
    broker = DatabaseOutboxBroker()
    current_backoff = 5.0
    min_backoff = 5.0
    max_backoff = 60.0
    
    logger.info("Background activity logs outbox processor worker started.")
    last_verification_run = None
    
    while not shutdown_event.is_set():
        try:
            async with AsyncSessionLocal() as db:
                # Set RLS parameters for systemic bypass
                if db.bind.dialect.name != "sqlite":
                    await db.execute(text("SELECT set_config('app.current_temple_id', '', false)"))
                    await db.execute(text("SELECT set_config('app.current_role', 'SUPER_ADMIN', false)"))
                
                # Run nightly audit chain integrity verification
                now = datetime.now(timezone.utc)
                if last_verification_run is None or (now - last_verification_run).total_seconds() >= 86400:
                    logger.info("Executing nightly background audit chain integrity verification...")
                    try:
                        from app.modules.audit.services.chain_verification_service import ChainVerificationService
                        await ChainVerificationService.verify_all_temples(db)
                        last_verification_run = now
                        logger.info("Nightly background audit chain verification completed successfully.")
                    except Exception as ex:
                        logger.error(f"Error executing nightly background audit chain verification: {str(ex)}")

                # Update queue metrics size
                size_res = await db.execute(select(sa_func_count()))
                OutboxMetrics.queue_depth = size_res.scalar() or 0
                
                oldest_res = await db.execute(
                    select(ActivityOutbox.created_at)
                    .order_by(ActivityOutbox.created_at.asc())
                    .limit(1)
                )
                oldest = oldest_res.scalar_one_or_none()
                if oldest:
                    OutboxMetrics.oldest_pending_event_age_seconds = int((now - oldest.astimezone(timezone.utc)).total_seconds())
                else:
                    OutboxMetrics.oldest_pending_event_age_seconds = 0
                
                processed = await ActivityLogProcessor.process_outbox_batch(db, broker, limit=50)
                
                # Update observability metrics
                OutboxMetrics.total_processed += processed
                OutboxMetrics.last_heartbeat = datetime.now(timezone.utc)
                
                # If we successfully processed events or queue is empty, reset backoff
                current_backoff = min_backoff
                
        except Exception as e:
            OutboxMetrics.total_failed += 1
            logger.error(f"Outbox worker encountered error: {str(e)}. Backing off for {current_backoff}s.")
            # Exponential backoff
            current_backoff = min(current_backoff * 2.0, max_backoff)
            
        # Bounded sleep checking shutdown event every 0.5 seconds
        sleep_remaining = current_backoff
        while sleep_remaining > 0 and not shutdown_event.is_set():
            await asyncio.sleep(min(0.5, sleep_remaining))
            sleep_remaining -= 0.5

    OutboxMetrics.worker_running = False
    logger.info("Background activity logs outbox processor worker stopped.")


def sa_func_count():
    from sqlalchemy import func
    return func.count(ActivityOutbox.id)
