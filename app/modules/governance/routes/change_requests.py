"""
Change Request Routes — Manager Dashboard API.

Endpoints:
- GET /  → list change requests (with filters)
- GET /pending → get_pending_approvals()
- POST /{id}/approve → approve_request()
- POST /{id}/reject → reject_request()
- POST / → create change request (for STAFF)
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import Optional

from app.core.database import get_db
from app.core.deps import get_current_user, get_current_temple_id, require_system_permission
from app.schemas.domain import TokenData
from app.schemas.change_request import (
    ChangeRequestCreate, ChangeRequestProcess,
    ChangeRequestResponse, PendingApprovalsResponse,
)
from app.services.change_request_service import ChangeRequestService
from app.core.response import api_response, paginated_response
from app.core.pagination import PaginationParams, get_pagination

router = APIRouter()


# ── Create Change Request (STAFF) ─────────────────────────────────────
@router.post("/", status_code=201)
async def create_change_request(
    data: ChangeRequestCreate,
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a field-level change request.
    STAFF cannot update live tables directly — all changes go through approval.
    Any authenticated user with temple context can create a change request.
    """
    # If TEMPLE_MANAGER or higher, they can update directly via other endpoints
    # STAFF must use change requests
    cr = await ChangeRequestService.create_change_request(
        db=db,
        temple_id=UUID(temple_id),
        entity_type=data.entity_type,
        entity_id=data.entity_id,
        field_name=data.field_name,
        old_value=data.old_value,
        new_value=data.new_value,
        requested_by=UUID(current_user.sub),
    )
    cr_dict = ChangeRequestResponse.model_validate(cr).model_dump()
    return api_response(data=cr_dict, message="Change request created successfully", status_code=201)


# ── Get Pending Approvals (Manager Dashboard) ────────────────────────
@router.get("/pending")
async def get_pending_approvals(
    entity_type: Optional[str] = None,
    pagination: PaginationParams = Depends(get_pagination),
    current_user: TokenData = Depends(require_system_permission("MANAGE_CHANGE_REQUESTS")),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Manager Dashboard: Get all pending change requests.
    Requires MANAGE_CHANGE_REQUESTS permission.
    """
    items, total = await ChangeRequestService.get_pending_approvals(
        db=db,
        temple_id=UUID(temple_id),
        entity_type=entity_type,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    items_list = [ChangeRequestResponse.model_validate(i).model_dump() for i in items]
    return paginated_response(
        data=items_list,
        total_count=total,
        page=pagination.page,
        page_size=pagination.page_size,
        message="Pending change requests retrieved"
    )


# ── List All Change Requests ──────────────────────────────────────────
@router.get("/")
async def list_change_requests(
    status: Optional[str] = None,
    entity_type: Optional[str] = None,
    pagination: PaginationParams = Depends(get_pagination),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db),
):
    """List change requests with optional status and entity_type filters."""
    items, total = await ChangeRequestService.get_change_requests(
        db=db,
        temple_id=UUID(temple_id),
        status=status,
        entity_type=entity_type,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    items_list = [ChangeRequestResponse.model_validate(i).model_dump() for i in items]
    return paginated_response(
        data=items_list,
        total_count=total,
        page=pagination.page,
        page_size=pagination.page_size,
        message="Change requests retrieved"
    )


# ── Approve Change Request ────────────────────────────────────────────
@router.post("/{request_id}/approve")
async def approve_request(
    request_id: UUID,
    payload: ChangeRequestProcess,
    current_user: TokenData = Depends(require_system_permission("MANAGE_CHANGE_REQUESTS")),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Approve a pending change request and apply to live table.
    Self-approval is prevented.
    Requires MANAGE_CHANGE_REQUESTS permission.
    """
    cr = await ChangeRequestService.approve_change(
        db=db,
        change_request_id=request_id,
        approved_by=UUID(current_user.sub),
        remarks=payload.remarks,
    )
    return api_response(data=ChangeRequestResponse.model_validate(cr).model_dump(), message="Change request approved")


# ── Reject Change Request ────────────────────────────────────────────
@router.post("/{request_id}/reject")
async def reject_request(
    request_id: UUID,
    payload: ChangeRequestProcess,
    current_user: TokenData = Depends(require_system_permission("MANAGE_CHANGE_REQUESTS")),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Reject a pending change request — no changes applied.
    Requires MANAGE_CHANGE_REQUESTS permission.
    """
    cr = await ChangeRequestService.reject_change(
        db=db,
        change_request_id=request_id,
        rejected_by=UUID(current_user.sub),
        remarks=payload.remarks,
    )
    return api_response(data=ChangeRequestResponse.model_validate(cr).model_dump(), message="Change request rejected")
