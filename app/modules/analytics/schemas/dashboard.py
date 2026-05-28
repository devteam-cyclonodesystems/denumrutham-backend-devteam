from pydantic import BaseModel, UUID4
from typing import Optional, List
from datetime import datetime


class RecentTransaction(BaseModel):
    id: UUID4
    type: str
    category: str
    amount: float
    description: str
    reference_id: Optional[str] = None
    date: datetime


class DashboardSummaryResponse(BaseModel):
    total_income: float = 0.0
    today_income: float = 0.0
    total_expense: float = 0.0
    total_bookings: int = 0
    today_bookings: int = 0
    total_hall_bookings: int = 0
    employee_count: int = 0
    staff_count: int = 0
    active_staff_count: int = 0
    pending_leaves: int = 0
    low_inventory_count: int = 0
    pending_approvals: int = 0
    active_workflows: int = 0
    live_streams_active: int = 0
    attendance_summary: dict = {"present": 0, "total": 0}
    recent_transactions: List[RecentTransaction] = []
