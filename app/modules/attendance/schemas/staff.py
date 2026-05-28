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

    class Config:
        from_attributes = True

class StaffUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None # ACTIVE, SUSPENDED, DISABLED
    role: Optional[str] = None

class StaffCredentials(BaseModel):
    username: str
    password: str

class StaffCounts(BaseModel):
    total: int
    active: int
    suspended: int
    on_leave: int
