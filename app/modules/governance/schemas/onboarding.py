"""
Onboarding Schemas — Pydantic models for temple registration and approval.
"""
import re
from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional, List
from datetime import datetime


# ── Registration Request ──────────────────────────────────────────────

class TempleOnboardingRequest(BaseModel):
    """Input for POST /onboarding/register-temple."""

    # Temple details
    temple_name: str
    domain: str
    temple_contact: Optional[str] = "" # New name
    contact: Optional[str] = ""        # Old name (backward compat)
    alt_contact: Optional[str] = ""
    address: Optional[str] = ""
    state: Optional[str] = ""
    district: Optional[str] = ""
    pincode: Optional[str] = ""
    temple_email: Optional[str] = ""

    # Manager details
    manager_name: str
    email: Optional[str] = None        # New name
    manager_email: Optional[str] = None # Old name (backward compat)
    phone: Optional[str] = None        # New name
    manager_phone: Optional[str] = None # Old name (backward compat)
    password: str

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

    @field_validator("temple_name")
    @classmethod
    def validate_temple_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Temple name is required")
        if len(v) < 3:
            raise ValueError("Temple name must be at least 3 characters")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        return v

    @field_validator("manager_email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v and v.strip():
            pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(pattern, v.strip()):
                raise ValueError("Invalid email format")
            return v.strip()
        return v

    @field_validator("manager_phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v and v.strip():
            cleaned = re.sub(r'[\s\-\(\)\+]', '', v)
            if not re.match(r'^\d{7,15}$', cleaned):
                raise ValueError("Invalid phone number format (7-15 digits expected)")
            return v.strip()
        return v

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, v: Optional[str]) -> Optional[str]:
        if v and v.strip():
            if not re.match(r'^\d{5,10}$', v.strip()):
                raise ValueError("Invalid pincode format")
        return v


# ── Response Models ───────────────────────────────────────────────────

class TempleRequestResponse(BaseModel):
    """Single temple request item."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    temple_name: str
    domain: str
    contact: str = ""
    alt_contact: str = ""
    address: str = ""
    state: str = ""
    district: str = ""
    pincode: str = ""
    email: str = ""
    status: str
    rejection_reason: Optional[str] = None
    rejected_by: Optional[str] = None # Phase 1 Additive
    rejected_at: Optional[datetime] = None # Phase 1 Additive
    created_at: datetime

    # Manager info (joined from user_request)
    manager_name: Optional[str] = None
    manager_email: Optional[str] = None
    manager_phone: Optional[str] = None


class TempleRequestListResponse(BaseModel):
    """Paginated list of temple requests."""
    requests: List[TempleRequestResponse]
    total: int


# ── Approval / Rejection ──────────────────────────────────────────────

class TempleApprovalRequest(BaseModel):
    """Optional notes when approving a temple request."""
    notes: Optional[str] = None


class TempleRejectionRequest(BaseModel):
    """Rejection requires a reason."""
    rejection_reason: str

    @field_validator("rejection_reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Rejection reason is required")
        if len(v) < 10:
            raise ValueError("Rejection reason must be at least 10 characters")
        return v
