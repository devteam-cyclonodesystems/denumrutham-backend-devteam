from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime

class StaffCreate(BaseModel):
    name: str
    email_or_phone: str
    role: str = "STAFF"
    department: Optional[str] = None
    shift: Optional[str] = None
    temporary_password: str
    notes: Optional[str] = None
    role_id: Optional[UUID] = None
    dob: Optional[str] = None
    salary: Optional[float] = None
    photo_url: Optional[str] = None
    media_urls: Optional[List[str]] = None
    remarks: Optional[str] = None
    availability_status: Optional[str] = "AVAILABLE"

class StaffResponse(BaseModel):
    id: UUID
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    role: str
    status: str
    onboarding_method: str
    created_at: datetime
    force_password_change: bool
    department: Optional[str] = None
    shift: Optional[str] = None
    dob: Optional[str] = None
    salary: Optional[float] = None
    photo_url: Optional[str] = None
    media_urls: Optional[List[str]] = None
    remarks: Optional[str] = None
    audit_trail: Optional[List[dict]] = None
    availability_status: Optional[str] = "AVAILABLE"

    class Config:
        from_attributes = True

class StaffUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None # ACTIVE, SUSPENDED, RESIGNED, TERMINATED
    role: Optional[str] = None
    department: Optional[str] = None
    shift: Optional[str] = None
    dob: Optional[str] = None
    salary: Optional[float] = None
    photo_url: Optional[str] = None
    media_urls: Optional[List[str]] = None
    remarks: Optional[str] = None
    audit_trail: Optional[List[dict]] = None
    availability_status: Optional[str] = None

class StaffCredentials(BaseModel):
    username: str
    password: str

class StaffCounts(BaseModel):
    total: int
    active: int
    suspended: int
    on_leave: int
