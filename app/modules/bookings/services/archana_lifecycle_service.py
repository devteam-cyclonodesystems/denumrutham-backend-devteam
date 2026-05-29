import logging
from uuid import UUID
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload, joinedload
from sqlalchemy import update

from app.models.archana import (
    EnterpriseArchanaBooking, 
    ArchanaBookingMember,
    ArchanaBookingItem, 
    RitualQueue,
    ArchanaExecution,
    QueueStatus,
    ArchanaBookingAudit
)
from app.core.exceptions import ServiceException

logger = logging.getLogger("tms.services.archana_lifecycle")

class ArchanaLifecycleService:
    @staticmethod
    async def initialize_executions(db: AsyncSession, queue_id: UUID):
        """Initializes individual ritual executions for a queue entry."""
        result = await db.execute(
            select(RitualQueue).filter(RitualQueue.id == queue_id)
            .options(
                selectinload(RitualQueue.booking)
                .selectinload(EnterpriseArchanaBooking.members)
                .selectinload(ArchanaBookingMember.items)
            )
        )
        queue = result.scalar_one_or_none()
        if not queue:
            return

        for member in queue.booking.members:
            for item in member.items:
                # Check if already exists
                existing = await db.execute(
                    select(ArchanaExecution).filter(ArchanaExecution.booking_item_id == item.id)
                )
                if existing.scalar_one_or_none():
                    continue

                execution = ArchanaExecution(
                    temple_id=queue.temple_id,
                    booking_item_id=item.id,
                    queue_id=queue.id,
                    status=QueueStatus.WAITING
                )
                db.add(execution)
        
        await db.flush()

    @staticmethod
    async def start_ritual(
        db: AsyncSession, 
        execution_id: UUID, 
        actor_id: UUID,
        priest_id: Optional[UUID] = None
    ) -> ArchanaExecution:
        result = await db.execute(
            select(ArchanaExecution).filter(ArchanaExecution.id == execution_id)
            .options(
                joinedload(ArchanaExecution.item)
                .joinedload(ArchanaBookingItem.member)
            ).execution_options(populate_existing=True)
        )
        execution = result.scalar_one_or_none()
        if not execution:
            raise ServiceException("Execution not found", "NOT_FOUND", status_code=404)
        
        if execution.status == QueueStatus.IN_PROGRESS:
            return execution
        
        if execution.status != QueueStatus.WAITING:
            logger.warning(f"Failed to start ritual {execution_id}: Invalid state {execution.status}")
            raise ServiceException(f"Cannot start ritual in {execution.status} state. Only WAITING rituals can be started.", "INVALID_STATE")

        now = datetime.now(timezone.utc)
        duration = execution.item.ritual_duration_snapshot or 5 # Default 5 mins
        
        # Optimistic Locking check
        execution.status = QueueStatus.IN_PROGRESS
        if priest_id:
            logger.info(
                "Legacy priest_id received and ignored",
                extra={
                    "priest_id": str(priest_id),
                    "user_id": str(actor_id),
                    "execution_id": str(execution_id)
                }
            )
        execution.priest_id = None
        execution.started_by_user_id = actor_id
        execution.start_time = now
        execution.expected_completion_time = now + timedelta(minutes=duration)
        execution.version_number = (execution.version_number or 1) + 1
        
        # Update aggregate queue status if needed
        await db.execute(
            update(RitualQueue).where(RitualQueue.id == execution.queue_id)
            .values(status=QueueStatus.IN_PROGRESS, actual_start_time=now)
        )

        audit = ArchanaBookingAudit(
            booking_id=execution.item.member.booking_id, # Need to ensure relationship is loaded or join
            action="RITUAL_START",
            actor_id=actor_id,
            new_state={
                "execution_id": str(execution_id),
                "item": execution.item.ritual_name_snapshot,
                "start_time": now.isoformat(),
                "expected_completion": execution.expected_completion_time.isoformat(),
                "mode": "SINGLE"
            }
        )
        db.add(audit)
        logger.error(
            "PRE-COMMIT EXECUTION STATE",
            extra={
                "execution_id": str(execution.id),
                "priest_id": str(execution.priest_id),
                "started_by_user_id": str(execution.started_by_user_id),
                "status": str(execution.status)
            }
        )
        await db.commit()
        await db.refresh(execution)
        return execution

    @staticmethod
    async def start_grouped_rituals(
        db: AsyncSession,
        execution_ids: List[UUID],
        actor_id: UUID,
        temple_id: UUID,
        priest_id: Optional[UUID] = None
    ) -> List[ArchanaExecution]:
        """
        Starts multiple rituals together (Internal grouping).
        Terminology 'Batch' or 'Group' is NOT exposed to UI.
        """
        from app.models.archana import ArchanaExecutionGroup
        
        if not execution_ids:
            return []

        # 1. Fetch all requested executions
        result = await db.execute(
            select(ArchanaExecution)
            .filter(ArchanaExecution.id.in_(execution_ids))
            .options(
                joinedload(ArchanaExecution.item)
                .joinedload(ArchanaBookingItem.member)
            ).execution_options(populate_existing=True)
        )
        executions = result.scalars().all()
        
        if not executions:
            raise ServiceException("No valid rituals found to start", "NOT_FOUND")

        now = datetime.now(timezone.utc)
        
        # 2. Create Internal Grouping Record
        # We take the longest duration as the group completion target
        max_duration = max([ex.item.ritual_duration_snapshot or 5 for ex in executions])
        
        group = ArchanaExecutionGroup(
            temple_id=temple_id,
            started_by=actor_id,
            started_at=now,
            expected_completion_at=now + timedelta(minutes=max_duration),
            status=QueueStatus.IN_PROGRESS
        )
        db.add(group)
        await db.flush()

        started_rituals = []
        for ex in executions:
            if ex.status != QueueStatus.WAITING:
                continue
                
            ex.status = QueueStatus.IN_PROGRESS
            if priest_id:
                logger.info(
                    "Legacy priest_id received and ignored",
                    extra={
                        "priest_id": str(priest_id),
                        "user_id": str(actor_id),
                        "execution_id": str(ex.id)
                    }
                )
            ex.priest_id = None
            ex.started_by_user_id = actor_id
            ex.start_time = now
            ex.expected_completion_time = group.expected_completion_at
            ex.execution_group_id = group.id
            ex.version_number = (ex.version_number or 1) + 1
            started_rituals.append(ex)
            
            # Sync Queue status
            await db.execute(
                update(RitualQueue).where(RitualQueue.id == ex.queue_id)
                .values(status=QueueStatus.IN_PROGRESS, actual_start_time=now)
            )

        if not started_rituals:
            raise ServiceException("All selected rituals are already in progress or completed.", "ALREADY_STARTED")

        audit = ArchanaBookingAudit(
            booking_id=executions[0].item.member.booking_id,
            action="RITUAL_GROUP_START",
            actor_id=actor_id,
            new_state={
                "count": len(started_rituals),
                "group_id": str(group.id),
                "expected_completion": group.expected_completion_at.isoformat()
            }
        )
        db.add(audit)
        for ex in started_rituals:
            logger.error(
                "PRE-COMMIT EXECUTION STATE",
                extra={
                    "execution_id": str(ex.id),
                    "priest_id": str(ex.priest_id),
                    "started_by_user_id": str(ex.started_by_user_id),
                    "status": str(ex.status)
                }
            )
        await db.commit()
        return started_rituals

    @staticmethod
    async def complete_ritual(
        db: AsyncSession, 
        execution_id: UUID, 
        actor_id: Optional[UUID],
        is_auto: bool = False
    ) -> ArchanaExecution:
        """Completes a ritual execution (either manually or automatically)."""
        from app.models.archana import CompletionMode
        
        result = await db.execute(
            select(ArchanaExecution).filter(ArchanaExecution.id == execution_id)
            .options(
                joinedload(ArchanaExecution.item)
                .joinedload(ArchanaBookingItem.member)
            ).execution_options(populate_existing=True)
        )
        execution = result.scalar_one_or_none()
        if not execution:
            raise ServiceException("Execution not found", "NOT_FOUND", status_code=404)
        
        if execution.status == QueueStatus.COMPLETED:
            return execution
        
        if execution.status != QueueStatus.IN_PROGRESS and not is_auto:
            logger.warning(f"Failed to complete ritual {execution_id}: Invalid state {execution.status}")
            raise ServiceException(f"Cannot complete ritual in {execution.status} state. Only IN_PROGRESS rituals can be completed.", "INVALID_STATE")

        now = datetime.now(timezone.utc)
        execution.status = QueueStatus.COMPLETED
        execution.completed_at = now
        execution.auto_completed = is_auto
        if not is_auto and actor_id:
            execution.completed_by_user_id = actor_id
        execution.completion_mode = CompletionMode.AUTO if is_auto else CompletionMode.MANUAL
        execution.version_number = (execution.version_number or 1) + 1

        # ── Group Reconciliation ──
        if execution.execution_group_id:
            from app.models.archana import ArchanaExecutionGroup
            # Check if all in group are done
            res = await db.execute(
                select(ArchanaExecution).filter(
                    ArchanaExecution.execution_group_id == execution.execution_group_id,
                    ArchanaExecution.status != QueueStatus.COMPLETED
                )
            )
            if not res.scalars().first():
                await db.execute(
                    update(ArchanaExecutionGroup)
                    .where(ArchanaExecutionGroup.id == execution.execution_group_id)
                    .values(status=QueueStatus.COMPLETED, completed_at=now)
                )

        # Check if all rituals in this queue entry are completed
        # We exclude the current execution from the query since it is actively being completed in this transaction
        q_result = await db.execute(
            select(ArchanaExecution).filter(
                ArchanaExecution.queue_id == execution.queue_id,
                ArchanaExecution.id != execution.id,
                ArchanaExecution.status != QueueStatus.COMPLETED,
                ArchanaExecution.status != QueueStatus.CANCELLED,
                ArchanaExecution.status != QueueStatus.SKIPPED
            )
        )
        remaining = q_result.scalars().first()
        
        if not remaining:
            # Mark the whole queue as COMPLETED
            await db.execute(
                update(RitualQueue).where(RitualQueue.id == execution.queue_id)
                .values(status=QueueStatus.COMPLETED, completed_at=now)
            )

        audit = ArchanaBookingAudit(
            booking_id=execution.item.member.booking_id,
            action="RITUAL_COMPLETE",
            actor_id=actor_id,
            new_state={
                "execution_id": str(execution_id),
                "status": execution.status,
                "completed_at": now.isoformat(),
                "mode": execution.completion_mode
            }
        )
        db.add(audit)
        logger.error(
            "PRE-COMMIT EXECUTION STATE",
            extra={
                "execution_id": str(execution_id),
                "priest_id": str(execution.priest_id),
                "started_by_user_id": str(execution.started_by_user_id) if execution.started_by_user_id else None,
                "status": str(execution.status)
            }
        )
        await db.commit()
        await db.refresh(execution)
        return execution

    @staticmethod
    async def process_auto_completions(db: AsyncSession):
        """Background process to auto-complete expired rituals."""
        now = datetime.now(timezone.utc)
        result = await db.execute(
            select(ArchanaExecution).filter(
                ArchanaExecution.status == QueueStatus.IN_PROGRESS,
                ArchanaExecution.expected_completion_time <= now
            )
        )
        expired = result.scalars().all()
        
        count = 0
        for execution in expired:
            try:
                await ArchanaLifecycleService.complete_ritual(db, execution.id, None, is_auto=True)
                count += 1
            except Exception as e:
                logger.error(f"Failed to auto-complete ritual {execution.id}: {str(e)}")
        
        if count > 0:
            logger.info(f"Auto-completed {count} rituals.")
