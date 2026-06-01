import logging
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException

from app.models.domain import Temple, OperationalStateAudit, SecurityAuditEvent, utcnow
from app.modules.governance.models.operational_states import TempleOperationalState
from app.services.tenant_policy import TenantPolicy
from app.services.broadcast_service import BroadcastService

logger = logging.getLogger(__name__)

# Valid state transitions to prevent logic errors
VALID_TRANSITIONS = {
    TempleOperationalState.ACTIVE: [
        TempleOperationalState.DEACTIVATED,
        TempleOperationalState.SUSPENDED,
        TempleOperationalState.READ_ONLY,
        TempleOperationalState.QUARANTINED,
        TempleOperationalState.INVESTIGATION,
        TempleOperationalState.SYNC_LOCKED,
        TempleOperationalState.OFFLINE_ONLY,
    ],
    TempleOperationalState.DEACTIVATED: [TempleOperationalState.ACTIVE],
    TempleOperationalState.SUSPENDED: [TempleOperationalState.RECOVERY_MODE, TempleOperationalState.ACTIVE],
    TempleOperationalState.READ_ONLY: [TempleOperationalState.ACTIVE, TempleOperationalState.SUSPENDED],
    TempleOperationalState.QUARANTINED: [TempleOperationalState.ACTIVE, TempleOperationalState.INVESTIGATION, TempleOperationalState.SUSPENDED],
    TempleOperationalState.INVESTIGATION: [TempleOperationalState.ACTIVE, TempleOperationalState.QUARANTINED, TempleOperationalState.SUSPENDED],
    TempleOperationalState.SYNC_LOCKED: [TempleOperationalState.ACTIVE, TempleOperationalState.SUSPENDED],
    TempleOperationalState.OFFLINE_ONLY: [TempleOperationalState.ACTIVE, TempleOperationalState.SUSPENDED],
    TempleOperationalState.RECOVERY_MODE: [TempleOperationalState.ACTIVE, TempleOperationalState.SUSPENDED],
}

class OperationalStateService:
    """
    Handles formal transitions between tenant operational states.
    """
    
    @staticmethod
    async def transition_to(
        db: AsyncSession,
        temple_id: UUID,
        new_state: TempleOperationalState,
        changed_by: UUID,
        reason: str,
        ip_address: str = None
    ) -> Temple:
        """
        Safely transition a temple to a new operational state.
        """
        async with db.begin_nested():
            # 1. Fetch current state with lock
            result = await db.execute(
                select(Temple).filter(Temple.id == temple_id).with_for_update()
            )
            temple = result.scalars().first()
            if not temple:
                raise HTTPException(status_code=404, detail="Temple not found")
            
            old_state = temple.operational_state
            
            # Idempotency: Return early if already in the target state
            if new_state == old_state:
                logger.debug(f"Idempotent transition for temple {temple_id}: already in state {new_state}")
                return temple
            
            # 2. Validate transition
            if new_state != old_state:
                allowed_next = VALID_TRANSITIONS.get(old_state, [])
                if new_state not in allowed_next:
                    raise HTTPException(
                        status_code=400, 
                        detail=f"Invalid state transition: {old_state} -> {new_state}"
                    )
            
            # 3. Apply state change
            temple.operational_state = new_state
            
            # 4. Maintain backward compatibility for 'is_active'
            temple.is_active = TenantPolicy.get_is_active_compat(new_state)
            
            # 5. Handle Security Hardening (Emergency transitions)
            if new_state in [TempleOperationalState.SUSPENDED, TempleOperationalState.QUARANTINED]:
                # Emergency: Increment security version and set last event timestamp
                temple.security_version += 1
                temple.last_security_event_at = utcnow()
                
                # Log security audit event
                security_event = SecurityAuditEvent(
                    temple_id=temple_id,
                    user_id=changed_by,
                    event_type="EMERGENCY_STATE_TRANSITION",
                    severity="CRITICAL",
                    ip_address=ip_address,
                    details={"old_state": old_state, "new_state": new_state, "reason": reason}
                )
                db.add(security_event)
            
            # 6. Audit Logging
            audit = OperationalStateAudit(
                temple_id=temple_id,
                old_state=old_state,
                new_state=new_state,
                changed_by=changed_by,
                reason=reason,
                ip_address=ip_address
            )
            db.add(audit)
            
            # 7. Update temple version for sync reconciliation
            temple.version += 1
            temple.updated_at = utcnow()
            
        await db.commit()
        
        # 8. Real-time Invalidation (WS/Broadcast)
        # Emergency: Force logout all sessions if state is SUSPENDED or DEACTIVATED
        if new_state in [TempleOperationalState.SUSPENDED, TempleOperationalState.DEACTIVATED]:
            await BroadcastService.force_logout_tenant(temple_id, reason=f"Tenant state changed to {new_state}")
        else:
            # Generic update for UI refreshes
            await BroadcastService.publish_tenant_event(temple_id, "TENANT_STATE_UPDATED", {
                "old_state": old_state,
                "new_state": new_state
            })
        
        from app.events.dispatcher import EventDispatcher
        
        return temple
