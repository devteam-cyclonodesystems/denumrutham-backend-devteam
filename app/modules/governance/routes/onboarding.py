"""
Onboarding API Routes — Temple registration and approval endpoints.

Public:
  POST /onboarding/register-temple — Submit temple onboarding request

Admin:
  GET  /admin/onboarding/temple-requests         — List pending requests
  GET  /admin/onboarding/temple-requests/{id}    — Get request details
  POST /admin/onboarding/approve-temple/{id}     — Approve request
  POST /admin/onboarding/reject-temple/{id}      — Reject request
"""
from uuid import UUID
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from slowapi import Limiter
from slowapi.util import get_remote_address
from typing import Optional

from app.api.deps import get_db, require_system_permission
from app.schemas.domain import TokenData
from app.schemas.onboarding import (
    TempleOnboardingRequest,
    TempleRequestResponse,
    TempleRequestListResponse,
    TempleApprovalRequest,
    TempleRejectionRequest,
)
from app.services.onboarding_service import OnboardingService
from app.core.response import api_response

# ── Routers ──────────────────────────────────────────────────────────
# We use two separate routers to keep public and admin paths distinct (Fix #8)
router = APIRouter()
admin_router = APIRouter()

limiter = Limiter(key_func=get_remote_address)


# ═══════════════════════════════════════════════════════════════════════
# PUBLIC: Temple Registration
# ═══════════════════════════════════════════════════════════════════════

@router.post("/register-temple")
@limiter.limit("3/minute")
async def register_temple(
    request: Request,
    data: TempleOnboardingRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Submit a temple onboarding request.

    Creates staging records (temple_request + user_request).
    No production records are created — manager cannot login yet.
    Requires Super Admin approval to activate.
    """
    # 1. Consolidated fields for backward compatibility (Safeguard #1)
    consolidated_email = data.email or data.manager_email
    consolidated_phone = data.phone or data.manager_phone
    consolidated_contact = data.temple_contact or data.contact

    result = await OnboardingService.register_temple(
        db=db,
        temple_name=data.temple_name,
        domain=data.domain,
        manager_name=data.manager_name,
        manager_email=consolidated_email,
        manager_phone=consolidated_phone,
        password=data.password,
        contact=consolidated_contact or "",
        alt_contact=data.alt_contact or "",
        address=data.address or "",
        state=data.state or "",
        district=data.district or "",
        pincode=data.pincode or "",
        temple_email=data.temple_email or "",
    )
    return api_response(data=result, message="Temple registration submitted", status_code=201)

@router.get("/check-domain")
@limiter.limit("10/minute")
async def check_domain(
    request: Request,
    domain: str = Query(..., min_length=3, max_length=50),
    db: AsyncSession = Depends(get_db),
):
    """
    Check if a temple domain is available.
    """
    is_available = await OnboardingService.is_domain_available(db, domain)
    return api_response(data={"available": is_available}, message="Domain availability check")



# ═══════════════════════════════════════════════════════════════════════
# ADMIN: Temple Request Management (Fix #8: /admin/onboarding/...)
# ═══════════════════════════════════════════════════════════════════════

@admin_router.get("/temple-requests")
async def list_temple_requests(
    status_filter: Optional[str] = Query(None, description="Filter by status: PENDING, APPROVED, REJECTED"),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_system_permission("APPROVE_TEMPLE")),
):
    """List temple registration requests. Defaults to all; filter by status."""
    if status_filter:
        result = await OnboardingService.list_all_requests(db, status_filter)
    else:
        result = await OnboardingService.list_pending_requests(db)

    return api_response(
        data=result,
        message=f"Found {result['count']} temple request(s)",
    )


@admin_router.get("/temple-requests/{request_id}")
async def get_temple_request(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_system_permission("APPROVE_TEMPLE")),
):
    """Get details of a single temple registration request."""
    item = await OnboardingService.get_request(db, UUID(request_id))
    return api_response(data=item, message="Temple request details")


@admin_router.post("/approve-temple/{request_id}")
async def approve_temple(
    request_id: str,
    body: Optional[TempleApprovalRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_system_permission("APPROVE_TEMPLE")),
):
    """
    Approve a pending temple registration request.

    Atomically creates production Temple + User + TempleProfile + UserTemple.
    Manager can login after this.
    """
    result = await OnboardingService.approve_temple(
        db=db,
        request_id=UUID(request_id),
        approver_id=UUID(current_user.sub),
    )
    return api_response(data=result, message="Temple approved successfully")


@admin_router.post("/reject-temple/{request_id}")
async def reject_temple(
    request_id: str,
    body: TempleRejectionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_system_permission("APPROVE_TEMPLE")),
):
    """
    Reject a pending temple registration request.

    Requires a rejection reason (minimum 10 characters).
    No production records are created.
    """
    result = await OnboardingService.reject_temple(
        db=db,
        request_id=UUID(request_id),
        approver_id=UUID(current_user.sub),
        rejection_reason=body.rejection_reason,
    )
    return api_response(data=result, message="Temple rejected")
