"""
Claims Routes — REST API endpoints for submitting, listing, and reviewing temple claims.
"""
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from uuid import UUID

from app.api.deps import get_db, get_current_user, require_system_permission
from app.core.middleware.limiter import limiter
from app.core.response import api_response
from app.modules.governance.schemas.claims import (
    ClaimRequestCreate, ClaimRequestReview, ClaimRequestResponse, ClaimRequestListResponse
)
from app.modules.governance.services.claims_service import ClaimsService

router = APIRouter()


@router.post("", response_model=ClaimRequestResponse, status_code=201)
@limiter.limit("5/day")
async def create_claim_request(
    request: Request,
    payload: ClaimRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """
    Submit a claim request for a DIRECTORY_ONLY temple.
    Rate limited to 5 requests per day per user/IP.
    """
    claimant_id = UUID(current_user.sub)
    claim = await ClaimsService.submit_claim(db, claimant_id, payload)
    await db.commit()
    return claim


@router.get("/my-claims", response_model=List[ClaimRequestResponse])
async def list_my_claims(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """
    List all claims submitted by the current authenticated user.
    """
    claimant_id = UUID(current_user.sub)
    claims, _ = await ClaimsService.list_claims(db, claimant_id=claimant_id, page=1, limit=100)
    return claims


@router.get("/admin", response_model=ClaimRequestListResponse)
async def list_claims_for_admin(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None, description="Filter by status (PENDING, APPROVED, REJECTED)"),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_system_permission("MANAGE_LEADS")),
):
    """
    List all claims submitted on the platform. Requires system permission MANAGE_LEADS.
    """
    claims, total = await ClaimsService.list_claims(
        db, status_filter=status, page=page, limit=limit
    )
    return {
        "claims": claims,
        "total": total
    }


@router.post("/admin/{claim_id}/review")
async def review_claim_request(
    claim_id: UUID,
    payload: ClaimRequestReview,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_system_permission("MANAGE_LEADS")),
):
    """
    Approve or reject a pending claim request. Requires system permission MANAGE_LEADS.
    """
    reviewer_id = UUID(current_user.sub)
    claim = await ClaimsService.review_claim(
        db=db,
        claim_id=claim_id,
        reviewer_id=reviewer_id,
        schema=payload
    )
    await db.commit()
    return api_response(
        data=claim,
        message=f"Claim request successfully updated to status {claim.status}."
    )
