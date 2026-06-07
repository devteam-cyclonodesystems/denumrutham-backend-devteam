import logging
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from fastapi import HTTPException, status

from app.models.domain import Temple
from app.models.operational_states import TempleOperationalState, OperationalCapability, STATE_CAPABILITIES

logger = logging.getLogger(__name__)

class TenantPolicy:
    """
    Centralized Policy Engine for Tenant Operational Governance.
    
    Enforces operational boundaries based on TempleOperationalState.
    """
    
    @staticmethod
    async def get_state(db: AsyncSession, temple_id: UUID) -> TempleOperationalState:
        """Fetch current operational state of a temple."""
        result = await db.execute(select(Temple.operational_state).filter(Temple.id == temple_id))
        state = result.scalar()
        if not state:
            # Fallback for backward compatibility or missing state
            return TempleOperationalState.ACTIVE
        return state

    @staticmethod
    async def has_capability(
        db: AsyncSession, 
        temple_id: UUID, 
        capability: OperationalCapability,
        user_role: str = None
    ) -> bool:
        """
        Evaluate if a temple has a specific capability in its current state.
        
        Args:
            db: Database session
            temple_id: The tenant ID
            capability: The capability to check (e.g. CAN_WRITE)
            user_role: The role of the user performing the action (SUPERADMIN bypasses some restrictions)
        """
        state = await TenantPolicy.get_state(db, temple_id)
        
        # 1. SUPERADMIN Bypass
        # SuperAdmin can always read and admin, even in SUSPENDED state
        if user_role and user_role.upper().replace("_", "") == "SUPERADMIN":
            if capability in [OperationalCapability.CAN_READ, OperationalCapability.CAN_ADMIN]:
                return True

        # 2. Check capability matrix
        allowed_capabilities = STATE_CAPABILITIES.get(state, set())
        
        if capability in allowed_capabilities:
            return True
            
        return False

    @staticmethod
    async def enforce(
        db: AsyncSession,
        temple_id: UUID,
        capability: OperationalCapability,
        user_role: str = None
    ):
        """
        Enforce a capability check. Raises HTTPException if not allowed.
        """
        allowed = await TenantPolicy.has_capability(db, temple_id, capability, user_role)
        if not allowed:
            state = await TenantPolicy.get_state(db, temple_id)
            logger.warning(
                "POLICY VIOLATION: Temple %s in state %s attempted %s",
                temple_id, state, capability
            )
            
            detail = f"Action {capability} is restricted for temple in {state} state."
            if state == TempleOperationalState.SUSPENDED:
                detail = "This temple is under administrative suspension. Operations are blocked."
            elif state == TempleOperationalState.READ_ONLY:
                detail = "This temple is in read-only mode. Mutations are blocked."
            elif state == TempleOperationalState.DEGRADED:
                detail = "This temple is in degraded mode due to audit chain security verification failure. Mutations are blocked."
            
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=detail
            )

    @staticmethod
    def get_is_active_compat(state: TempleOperationalState) -> bool:
        """
        Returns boolean is_active for backward compatibility.
        Only ACTIVE and READ_ONLY are considered 'is_active=True' for general logic.
        """
        return state in [
            TempleOperationalState.ACTIVE, 
            TempleOperationalState.READ_ONLY,
            TempleOperationalState.OFFLINE_ONLY,
            TempleOperationalState.SYNC_LOCKED,
            TempleOperationalState.INVESTIGATION
        ]
