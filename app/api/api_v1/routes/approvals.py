from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from uuid import UUID
from typing import List, Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.core.deps import get_current_temple_id, require_permission
from app.schemas.domain import TokenData
from app.models.domain import ApprovalRequest
from app.services.approval_service import ApprovalService
from app.core.response import api_response

router = APIRouter()

class ProcessApprovalInput(BaseModel):
    status: str  # approved or rejected
    remarks: Optional[str] = None

@router.get("/")
async def get_pending_approvals(
    module: Optional[str] = None,
    current_user: TokenData = Depends(require_permission("approvals", "read")),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(ApprovalRequest).filter(
        ApprovalRequest.temple_id == UUID(temple_id),
        ApprovalRequest.status == "pending"
    )
    if module:
        stmt = stmt.filter(ApprovalRequest.module == module)
        
    result = await db.execute(stmt)
    approvals = result.scalars().all()
    approvals_list = [
        {
            "id": str(a.id),
            "temple_id": str(a.temple_id),
            "module": a.module,
            "entity_id": a.entity_id,
            "action": a.module,
            "status": a.status,
            "requested_by": str(a.requested_by),
            "created_at": a.created_at.isoformat(),
        } for a in approvals
    ]
    return api_response(data=approvals_list, message="Approvals retrieved")

@router.post("/{request_id}/process")
async def process_approval(
    request_id: UUID,
    payload: ProcessApprovalInput,
    current_user: TokenData = Depends(require_permission("approvals", "full")),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db)
):
    if payload.status not in ("approved", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid status")
    
    try:
        req = await ApprovalService.process_approval(
            db, request_id, UUID(current_user.sub), payload.status, payload.remarks
        )
        # Note: Depending on the module, the caller or background worker 
        # should now apply `req.request_payload`.
        req_data = {
            "id": str(req.id),
            "status": req.status,
            "remarks": req.remarks
        }
        return api_response(data=req_data, message="Approval processed successfully")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
