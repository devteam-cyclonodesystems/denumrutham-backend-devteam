"""
Authentication & Registration Schemas — Unified registration with
email-or-phone detection, OTP verification, and redirect logic.
"""
import re
from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional
from datetime import datetime


# ── Registration ──────────────────────────────────────────────────────

class UnifiedRegister(BaseModel):
    """Unified registration with 3 entry roles: DEVOTEE, TEMPLE_MANAGER, STAFF.
    
    The `email_or_phone` field auto-detects whether the input is an email or
    a mobile number and stores them in separate DB columns.
    """
    email_or_phone: str
    password: str
    confirm_password: Optional[str] = None # Added for Phase 3 validation
    name: str
    role: str = "DEVOTEE"  # DEVOTEE | TEMPLE_MANAGER | STAFF
    onboarding_method: Optional[str] = "INVITE_TOKEN"  # INVITE_TOKEN | DOMAIN_APPROVAL
    temple_domain: Optional[str] = None  # Slug identifier (backward compat)
    temple_id: Optional[str] = None      # Internal ID identifier (Phase 2/3)
    temple_code: Optional[str] = None    # Human-readable identifier (Phase 2/3)
    invite_token: Optional[str] = None   # For STAFF registration hardening

    @field_validator("email_or_phone")
    @classmethod
    def validate_email_or_phone(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Email or phone number is required")
        # Check if it looks like an email
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if re.match(email_pattern, v):
            return v
        # Check if it looks like a phone number (digits, optional +, 7-15 digits)
        phone_cleaned = re.sub(r'[\s\-\(\)\+]', '', v)
        if re.match(r'^\d{7,15}$', phone_cleaned):
            return v
        raise ValueError("Must be a valid email address or phone number (7-15 digits)")

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        allowed = {"DEVOTEE", "TEMPLE_MANAGER", "STAFF"}
        if v.upper() not in allowed:
            raise ValueError(f"Role must be one of: {', '.join(sorted(allowed))}")
        return v.upper()

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        return v


class TempleManagerRegister(BaseModel):
    """Temple registration — creates Temple (PENDING) + User (TEMPLE_MANAGER)."""
    email_or_phone: str
    password: str
    name: str
    temple_name: str
    temple_contact_number: Optional[str] = ""
    temple_email: Optional[str] = ""
    temple_location: Optional[str] = ""
    temple_state: Optional[str] = ""
    temple_district: Optional[str] = ""
    temple_pincode: Optional[str] = ""

    @field_validator("email_or_phone")
    @classmethod
    def validate_email_or_phone(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Email or phone number is required")
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if re.match(email_pattern, v):
            return v
        phone_cleaned = re.sub(r'[\s\-\(\)\+]', '', v)
        if re.match(r'^\d{7,15}$', phone_cleaned):
            return v
        raise ValueError("Must be a valid email address or phone number")


# ── OTP ───────────────────────────────────────────────────────────────

class OTPRequest(BaseModel):
    """Request OTP for verification."""
    email_or_phone: str


class OTPVerify(BaseModel):
    """Verify OTP code."""
    email_or_phone: str
    otp_code: str


# ── Login Response ────────────────────────────────────────────────────

class LoginResponse(BaseModel):
    """Login response with redirect URL based on role."""
    access_token: str
    token_type: str = "bearer"
    role: str
    redirect_url: str
    user_status: str
    temple_id: Optional[str] = None
    force_password_change: bool = False
    user_id: Optional[str] = None


# ── User Responses ────────────────────────────────────────────────────

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    role: str
    status: str
    temple_id: Optional[str] = None
    created_at: datetime


class RegistrationResponse(BaseModel):
    """Response after successful registration."""
    message: str
    user_id: str
    role: str
    status: str
    temple_id: Optional[str] = None
    temple_status: Optional[str] = None


# ── Password Reset ───────────────────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    """Input for requesting a password reset link."""
    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, v):
            raise ValueError("Must be a valid email address")
        return v


class ResetPasswordRequest(BaseModel):
    """Input for setting a new password via token."""
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        # Strong password policy check (Fix PART 2.3 security requirement)
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&]).{8,}$', v):
            raise ValueError("Password must contain uppercase, lowercase, number and special character")
        return v

class ForceResetPasswordRequest(BaseModel):
    """Input for setting a new password when already logged in but forced to change."""
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        # Strong password policy check
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.match(r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&]).{8,}$', v):
            raise ValueError("Password must contain uppercase, lowercase, number and special character")
        return v

