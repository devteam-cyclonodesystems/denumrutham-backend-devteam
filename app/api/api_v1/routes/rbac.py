from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID
from app.core.database import get_db
from app.core.deps import get_current_active_admin, get_current_temple_id
from app.services.rbac_service import RBACService
from app.schemas.domain import TokenData

router = APIRouter()

@router.get("/permissions/my")
async def get_my_permissions(
    current_user: TokenData = Depends(get_current_active_admin),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db)
):
    if current_user.role == "SUPERADMIN":
        return [{"resource_type": "all", "resource_key": "all", "access_level": "full"}]
    
    return await RBACService.get_user_permissions(db, UUID(current_user.sub), UUID(temple_id))
