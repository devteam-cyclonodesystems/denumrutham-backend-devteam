from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List
from uuid import UUID

from app.api.deps import get_db, get_current_user, get_current_temple_id, require_permission
from app.schemas.domain import TokenData
from app.schemas.staff import StaffCreate, StaffResponse, StaffUpdate, StaffCounts
from app.services.staff_service import StaffService

router = APIRouter()

@router.post("", response_model=StaffResponse)
async def create_staff(
    staff_in: StaffCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("staff", "manage_employees")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Manager-driven staff provisioning."""
    return await StaffService.create_staff(
        db=db, 
        staff_in=staff_in, 
        temple_id=UUID(temple_id), 
        creator_id=UUID(current_user.sub)
    )

@router.get("", response_model=List[StaffResponse])
async def list_staff(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("staff", "manage_employees")),
    temple_id: str = Depends(get_current_temple_id),
):
    return await StaffService.get_staff_list(db=db, temple_id=UUID(temple_id))

@router.get("/counts", response_model=StaffCounts)
async def get_staff_counts(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("staff", "manage_employees")),
    temple_id: str = Depends(get_current_temple_id),
):
    return await StaffService.get_staff_counts(db=db, temple_id=UUID(temple_id))

@router.patch("/{staff_id}/suspend", response_model=StaffResponse)
async def suspend_staff(
    staff_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("staff", "manage_employees")),
    temple_id: str = Depends(get_current_temple_id),
):
    return await StaffService.update_staff_status(
        db=db, staff_id=staff_id, status="SUSPENDED", temple_id=UUID(temple_id), actor_id=UUID(current_user.sub)
    )

@router.patch("/{staff_id}/reactivate", response_model=StaffResponse)
async def reactivate_staff(
    staff_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("staff", "manage_employees")),
    temple_id: str = Depends(get_current_temple_id),
):
    return await StaffService.update_staff_status(
        db=db, staff_id=staff_id, status="ACTIVE", temple_id=UUID(temple_id), actor_id=UUID(current_user.sub)
    )

@router.post("/{staff_id}/reset-password", response_model=StaffResponse)
async def reset_password(
    staff_id: UUID,
    new_password: str, # Should be in a schema really, but keeping it simple for now
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("staff", "manage_employees")),
    temple_id: str = Depends(get_current_temple_id),
):
    return await StaffService.reset_password(
        db=db, staff_id=staff_id, new_password=new_password, temple_id=UUID(temple_id), actor_id=UUID(current_user.sub)
    )

@router.patch("/{staff_id}", response_model=StaffResponse)
async def update_staff_details(
    staff_id: UUID,
    staff_in: StaffUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("staff", "manage_employees")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Update details of existing staff member."""
    return await StaffService.update_staff(
        db=db,
        staff_id=staff_id,
        staff_in=staff_in,
        temple_id=UUID(temple_id),
        actor_id=UUID(current_user.sub)
    )

@router.delete("/{staff_id}", response_model=dict)
async def delete_staff(
    staff_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("staff", "manage_employees")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Release/delete staff member from directory."""
    return await StaffService.delete_staff(
        db=db,
        staff_id=staff_id,
        temple_id=UUID(temple_id),
        actor_id=UUID(current_user.sub)
    )
