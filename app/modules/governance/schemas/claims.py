"""
Claims Schemas — Pydantic models for Temple Claim Workflow.
"""
from pydantic import BaseModel, ConfigDict, field_validator
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class ClaimRequestCreate(BaseModel):
    temple_id: UUID
    proof_urls: List[str]
    target_management_mode: Optional[str] = "GOVERNED"
    target_subscription_plan: Optional[str] = "GOVERNED_STANDARD"
    claimant_notes: Optional[str] = None

    @field_validator("proof_urls")
    @classmethod
    def validate_proof_urls(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("At least one proof URL is required")
        for url in v:
            if not url.strip():
                raise ValueError("Proof URLs cannot be empty strings")
        return v

    @field_validator("target_management_mode")
    @classmethod
    def validate_management_mode(cls, v: str) -> str:
        valid_modes = {"GOVERNED", "SELF_MANAGED", "DENUMRUTHAM_MANAGED"}
        if v.upper() not in valid_modes:
            raise ValueError(f"Management mode must be one of {valid_modes}")
        return v.upper()


class ClaimRequestReview(BaseModel):
    status: str  # APPROVED or REJECTED
    rejection_reason: Optional[str] = None
    target_management_mode: Optional[str] = None
    target_subscription_plan: Optional[str] = None
    trial_duration_days: Optional[int] = 30

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        v_upper = v.upper()
        if v_upper not in {"APPROVED", "REJECTED"}:
            raise ValueError("Status must be APPROVED or REJECTED")
        return v_upper

    @field_validator("trial_duration_days")
    @classmethod
    def validate_trial_days(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("Trial duration days cannot be negative")
        return v


class ClaimRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    temple_id: UUID
    claimant_id: UUID
    status: str
    proof_urls: Optional[List[str]] = None
    target_management_mode: str
    target_subscription_plan: str
    trial_duration_days: int
    claimant_notes: Optional[str] = None
    reviewed_by: Optional[UUID] = None
    reviewed_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    # Extra field decorators
    temple_name: Optional[str] = None
    claimant_name: Optional[str] = None
    claimant_email: Optional[str] = None
    claimant_phone: Optional[str] = None


class ClaimRequestListResponse(BaseModel):
    claims: List[ClaimRequestResponse]
    total: int
