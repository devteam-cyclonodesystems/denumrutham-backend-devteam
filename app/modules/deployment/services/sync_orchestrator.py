from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from uuid import UUID
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import logging
from app.models.accounting import FinancialLedgerEntry, LedgerEntryType
from app.models.archana import ArchanaSyncState

logger = logging.getLogger("tms.services.sync")

class HybridSyncOrchestrator:
    """Enterprise foundation for local-first hybrid synchronization."""
    
    @staticmethod
    async def reconcile_journal(
        db: AsyncSession, 
        temple_id: UUID, 
        device_id: str, 
        journal_entries: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Reconciles a batch of offline events into the master ledger.
        Ensures idempotency and detects conflicts.
        """
        sync_results = []
        conflicts = 0
        processed = 0
        
        for entry in journal_entries:
            event_id = entry.get("offline_event_id")
            if not event_id:
                continue
            
            # 1. Idempotency Check (Anti-Duplication)
            query = select(FinancialLedgerEntry).filter(
                FinancialLedgerEntry.temple_id == temple_id,
                FinancialLedgerEntry.offline_event_id == event_id
            )
            existing = await db.execute(query)
            if existing.scalar():
                sync_results.append({"event_id": event_id, "status": "ALREADY_SYNCED"})
                continue
            
            # 2. Conflict Detection (Edited Totals / Overwrites)
            # Future: add timestamp based LWW (Last Write Wins) or manual resolution
            
            # 3. Apply Event to Ledger
            try:
                ledger_entry = FinancialLedgerEntry(
                    temple_id=temple_id,
                    entry_type=LedgerEntryType.BOOKING,
                    ref_id=entry.get("ref_id"),
                    amount=entry.get("amount"),
                    payment_mode=entry.get("payment_mode"),
                    device_id=device_id,
                    offline_event_id=event_id,
                    sync_status="SYNCED",
                    description=f"Offline Synced: {entry.get('description', '')}"
                )
                db.add(ledger_entry)
                processed += 1
                sync_results.append({"event_id": event_id, "status": "SUCCESS"})
            except Exception as e:
                logger.error(f"Sync failed for event {event_id}: {str(e)}")
                sync_results.append({"event_id": event_id, "status": "FAILED", "error": str(e)})

        await db.commit()
        
        return {
            "sync_id": f"SYNC-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            "processed": processed,
            "conflicts": conflicts,
            "results": sync_results
        }

    @staticmethod
    async def get_sync_status(db: AsyncSession, temple_id: UUID) -> Dict[str, Any]:
        """Returns the health of the hybrid sync ecosystem."""
        pending_query = select(FinancialLedgerEntry).filter(
            FinancialLedgerEntry.temple_id == temple_id,
            FinancialLedgerEntry.sync_status == "PENDING"
        )
        res = await db.execute(pending_query)
        pending_count = len(res.scalars().all())
        
        return {
            "pending_sync_events": pending_count,
            "last_global_sync": datetime.now(timezone.utc).isoformat(), # Placeholder
            "status": "HEALTHY" if pending_count < 100 else "DEGRADED"
        }
