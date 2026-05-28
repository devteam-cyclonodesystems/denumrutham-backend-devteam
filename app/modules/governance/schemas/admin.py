from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import datetime
from uuid import UUID

class AdminDashboardSummary(BaseModel):
    total_temples: int
    active_temples: int
    inactive_temples: int
    pending_approvals: int
    rejected_temples: int

class TempleListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    domain: str
    location: str
    state: str
    district: str
    contact_number: str
    email: str
    status: str
    is_active: Optional[bool] = True
    created_at: datetime

class TempleListResponse(BaseModel):
    items: List[TempleListItem]
    total: int
    page: int
    limit: int
    pages: int
