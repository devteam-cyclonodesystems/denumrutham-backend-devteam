
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.system import ConflictReport, SyncCheckpoint
from app.models.domain import Temple

logger = logging.getLogger("tms.sync.conflict")

class OfflineConflictResolver:
    """
    Phase 8: Offline Conflict Reconciliation.
    Handles version-based conflict resolution for hybrid architecture.
    """
    @staticmethod
    async def reconcile(
        db: AsyncSession,
        temple_id: str,
        entity_type: str,
        entity_id: str,
        server_version: int,
        client_version: int,
        server_data: Dict[str, Any],
        client_data: Dict[str, Any],
        strategy: str = "server_wins"
    ) -> Dict[str, Any]:
        """
        Deterministic conflict resolution.
        Returns the resolved data and logs the conflict.
        """
        if server_version == client_version:
            # No conflict
            return client_data

        logger.warning(
            f"Conflict detected for {entity_type} {entity_id} "
            f"(Server V{server_version} vs Client V{client_version})"
        )

        resolved_data = server_data if strategy == "server_wins" else client_data
        
        # Log the conflict
        report = ConflictReport(
            temple_id=temple_id,
            entity_type=entity_type,
            entity_id=entity_id,
            resolution_strategy=strategy,
            conflict_details={
                "server_version": server_version,
                "client_version": client_version,
                "server_snapshot": server_data,
                "client_snapshot": client_data
            }
        )
        db.add(report)
        
        return resolved_data

    @staticmethod
    async def update_checkpoint(
        db: AsyncSession,
        temple_id: str,
        device_id: str,
        last_version: int
    ):
        """Phase 8: Track sync progress per device."""
        from sqlalchemy.dialects.postgresql import insert
        
        stmt = insert(SyncCheckpoint).values(
            temple_id=temple_id,
            device_id=device_id,
            last_version=last_version,
            last_sync_at=datetime.utcnow()
        ).on_conflict_do_update(
            index_elements=["temple_id", "device_id"],
            set_={"last_version": last_version, "last_sync_at": datetime.utcnow()}
        )
        await db.execute(stmt)
