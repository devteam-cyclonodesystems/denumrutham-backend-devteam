from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional
import logging

from app.schemas.domain import TempleUpdateFull
from app.services.superadmin_service import SuperAdminService

# Import other services and models if necessary:
# from app.services.hall_service import HallService
# from app.services.employee_service import EmployeeService

logger = logging.getLogger(__name__)

class ApprovalExecutor:
    """Safe Execution Layer validating payload and dispatching to services natively."""
    
    @staticmethod
    async def execute_module_action(
        db: AsyncSession, 
        module: str, 
        entity_id: str, 
        request_payload: dict,
        executed_by: Optional[str] = None,
    ):
        """Dispatches an approved payload safely mapped to service functions after dynamic Pydantic validation."""
        
        if module == "temples":
            try:
                # Schema mismatch triggers ValidationError
                valid_data = TempleUpdateFull(**request_payload)
            except Exception as e:
                logger.error(f"Schema validation failed for {module}: {str(e)}")
                raise ValueError("Payload schema validation failed.")
            
            # NEVER writes JSON directly. We call the service layer abstraction safely
            await SuperAdminService.update_temple(db, str(entity_id), valid_data, updated_by=executed_by)

        # Example blocks for scalability:
        # elif module == "halls": ...
        # elif module == "finance": ...
        # elif module == "hr": ...
        else:
            raise ValueError(f"No execution handler registered for module: {module}")
        
        logger.info(f"Safely executed approval block natively mapped to module {module} -> {entity_id}")

