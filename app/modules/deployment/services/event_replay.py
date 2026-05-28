
import logging
from typing import Dict, Any, Callable, Awaitable
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.system import ProcessedEvent
from app.core.database import AsyncSessionLocal

logger = logging.getLogger("tms.event_replay")

class EventReplayCoordinator:
    """
    Phase 7: Distributed Event Resilience.
    Wraps event handlers with idempotency checks.
    """
    @staticmethod
    async def process_event(
        event_id: str, 
        event_type: str, 
        payload: Dict[str, Any], 
        handler: Callable[[Dict[str, Any]], Awaitable[None]]
    ):
        if not event_id:
            logger.warning(f"Event received without ID: {event_type}. Skipping idempotency check.")
            return await handler(payload)

        async with AsyncSessionLocal() as db:
            # Check if already processed
            result = await db.execute(
                select(ProcessedEvent).filter(ProcessedEvent.event_id == event_id)
            )
            existing = result.scalars().first()
            if existing:
                logger.info(f"Duplicate event suppressed: {event_id} ({event_type})")
                return

            # Log start of processing
            processed_event = ProcessedEvent(
                event_id=event_id,
                event_type=event_type,
                payload=payload,
                status="processing"
            )
            db.add(processed_event)
            await db.flush()

            try:
                # Execute actual handler
                await handler(payload)
                processed_event.status = "success"
                await db.commit()
                logger.info(f"Event processed successfully: {event_id}")
            except Exception as e:
                await db.rollback()
                logger.error(f"Event processing failed: {event_id}. Error: {str(e)}")
                
                # Update status to failed
                async with AsyncSessionLocal() as db_err:
                    err_event = ProcessedEvent(
                        event_id=event_id,
                        event_type=event_type,
                        payload=payload,
                        status="failed",
                        error_message=str(e)
                    )
                    db_err.add(err_event)
                    await db_err.commit()
                raise
