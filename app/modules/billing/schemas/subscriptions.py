from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID

class SubscriptionResponse(BaseModel):
    id: UUID
    temple_id: UUID
    razorpay_subscription_id: Optional[str] = None
    subscription_plan: str
    status: str
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    trial_start: Optional[datetime] = None
    trial_end: Optional[datetime] = None
    grace_period_ends_at: Optional[datetime] = None
    past_due_warning: bool = False
    write_locked: bool = False

    class Config:
        from_attributes = True

class RazorpaySubscriptionEntity(BaseModel):
    id: str
    plan_id: str
    status: str
    current_start: Optional[int] = None
    current_end: Optional[int] = None
    trial_start: Optional[int] = None
    trial_end: Optional[int] = None
    notes: Dict[str, Any] = Field(default_factory=dict)

class RazorpayWebhookPayloadDetail(BaseModel):
    subscription: Dict[str, Any]

class RazorpayWebhookPayload(BaseModel):
    event: str
    payload: RazorpayWebhookPayloadDetail

class RevenueReportResponse(BaseModel):
    status_counts: Dict[str, int] = Field(
        default_factory=lambda: {
            "PENDING": 0,
            "TRIALING": 0,
            "ACTIVE": 0,
            "PAST_DUE": 0,
            "HALTED": 0,
            "CANCELLED": 0,
            "EXPIRED": 0
        }
    )
    mrr: float = 0.0
    expected_renewal_revenue: float = 0.0
