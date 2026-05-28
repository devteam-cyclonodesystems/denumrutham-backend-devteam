from pydantic import BaseModel, ConfigDict, UUID4
from typing import Optional, List
from datetime import datetime


# ---------- Employee ----------
class EmployeeCreate(BaseModel):
    """Matches exact UI payload from hr-payroll.js saveEmployee()."""
    name: str
    role: str = ""
    department: str = ""
    phone: str = ""
    salary: float = 0.0
    join_date: str = ""
    remarks: str = ""


class EmployeeUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    phone: Optional[str] = None
    salary: Optional[float] = None
    join_date: Optional[str] = None
    attendance: Optional[int] = None
    status: Optional[str] = None
    remarks: Optional[str] = None
    promotion_history: Optional[List[dict]] = None
    salary_history: Optional[List[dict]] = None


class EmployeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    emp_code: Optional[str] = None
    name: str
    role: str
    department: str
    phone: str
    salary: float
    join_date: str
    attendance: int
    status: str
    remarks: str
    promotion_history: Optional[List[dict]] = []
    salary_history: Optional[List[dict]] = []
    created_at: datetime


# ---------- Leave ----------
class LeaveCreate(BaseModel):
    """Matches exact UI payload from hr-payroll.js saveLeave()."""
    employee_id: UUID4
    emp_name: str = ""
    type: str = "Casual"
    from_date: str
    to_date: str
    reason: str = ""


class LeaveUpdate(BaseModel):
    status: Optional[str] = None
    remarks: Optional[str] = None


class LeaveResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID4
    temple_id: UUID4
    employee_id: UUID4
    leave_code: Optional[str] = None
    emp_name: str
    type: str
    from_date: str
    to_date: str
    reason: str
    status: str
    remarks: str
    created_at: datetime


# ---------- Payroll ----------
class PayrollRunResponse(BaseModel):
    total_amount: float
    employee_count: int
    transaction_id: UUID4
