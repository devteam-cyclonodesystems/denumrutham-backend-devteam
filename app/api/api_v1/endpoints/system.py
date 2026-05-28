
from fastapi import APIRouter, Depends, HTTPException
from app.api.deps import get_current_superadmin
from app.core.integrity import DeploymentIntegrityService
from app.schemas.domain import TokenData

router = APIRouter()

@router.get("/integrity")
async def get_system_integrity(
    current_user: TokenData = Depends(get_current_superadmin)
):
    """
    Phase 1: Deployment Drift Detection.
    Returns the comprehensive integrity status of the system.
    """
    return await DeploymentIntegrityService.get_integrity_status()

@router.get("/version")
async def get_system_version():
    """
    Phase 4: Container Integrity System.
    Exposes versioning metadata without requiring full admin auth (public health check).
    """
    return DeploymentIntegrityService.get_build_info()
