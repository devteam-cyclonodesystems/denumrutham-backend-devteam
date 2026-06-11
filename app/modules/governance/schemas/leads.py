"""
Leads Schemas — Pydantic models for Temple Leads CRM pipeline.
"""
from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional, List
from datetime import datetime, date
from uuid import UUID
import re

class LeadBase(BaseModel):
    temple_name: str
    contact_person: str
    phone: str
    email: str
    state: str
    district: str
    interested_plan: Optional[str] = None
    lead_source: Optional[str] = None
    follow_up_date: Optional[date] = None
    status: Optional[str] = "NEW"
    notes: Optional[str] = None

class LeadCreate(LeadBase):
    @field_validator("temple_name")
    @classmethod
    def validate_temple_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Temple name is required")
        return v

    @field_validator("contact_person")
    @classmethod
    def validate_contact_person(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Contact person name is required")
        return v

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Phone number is required")
        cleaned = re.sub(r'[\s\-\(\)\+]', '', v)
        if not re.match(r'^\d{7,15}$', cleaned):
            raise ValueError("Invalid phone number format (7-15 digits expected)")
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Email is required")
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, v):
            raise ValueError("Invalid email format")
        return v

class LeadUpdate(BaseModel):
    temple_name: Optional[str] = None
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    state: Optional[str] = None
    district: Optional[str] = None
    interested_plan: Optional[str] = None
    lead_source: Optional[str] = None
    follow_up_date: Optional[date] = None
    status: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Phone number cannot be empty")
            cleaned = re.sub(r'[\s\-\(\)\+]', '', v)
            if not re.match(r'^\d{7,15}$', cleaned):
                raise ValueError("Invalid phone number format (7-15 digits expected)")
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("Email cannot be empty")
            pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(pattern, v):
                raise ValueError("Invalid email format")
        return v

class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    temple_name: str
    contact_person: str
    phone: str
    email: str
    state: str
    district: str
    interested_plan: Optional[str] = None
    lead_source: Optional[str] = None
    follow_up_date: Optional[date] = None
    status: str
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

class LeadListResponse(BaseModel):
    leads: List[LeadResponse]
    total: int


class LeadConvert(BaseModel):
    domain: str
    manager_password: str

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        v = v.strip().lower()
        if not v:
            raise ValueError("Domain is required")
        if " " in v:
            raise ValueError("Domain cannot contain spaces")
        if not re.match(r'^[a-z0-9-]{3,50}$', v):
            raise ValueError("Domain must be 3-50 characters, lowercase alphanumeric and hyphens only")
        return v

    @field_validator("manager_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        return v
