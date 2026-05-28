"""
Change Request Schemas — Field-level change approval system.
"""
from pydantic import BaseModel, ConfigDict, UUID4
from typing import Optional
from datetime import datetime


class ChangeRequestCreate(BaseModel):
    """Create a field-level change request."""
    entity_type: str  # 'temple', 'employee', 'hall', etc.
    entity_id: str
    field_name: str
    old_value: Optional[str] = None
    new_value: str


class ChangeRequestBulkCreate(BaseModel):
    """Create multiple change requests at once (multi-field update)."""
    entity_type: str
    entity_id: str
    changes: list[ChangeRequestCreate]


class ChangeRequestProcess(BaseModel):
    """Approve or reject a change request."""
    status: str  # APPROVED | REJECTED
    remarks: Optional[str] = None


class ChangeRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    entity_type: str
    entity_id: str
    field_name: str
    old_value: Optional[str] = None
    new_value: str
    requested_by: UUID4
    approved_by: Optional[UUID4] = None
    status: str
    remarks: Optional[str] = None
    temple_id: UUID4
    created_at: datetime
    updated_at: Optional[datetime] = None


class PendingApprovalsResponse(BaseModel):
    """Response for manager dashboard."""
    items: list[ChangeRequestResponse]
    total: int
