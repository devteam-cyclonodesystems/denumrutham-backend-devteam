"""
Temple Suggestions Routes — REST API endpoints for submitting, listing, and reviewing temple suggestions.
"""
from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional, List
from uuid import UUID

from app.api.deps import get_db, get_current_user, require_system_permission
from app.modules.governance.schemas.suggestions import (
    TempleSuggestionCreate, TempleSuggestionResponse, TempleSuggestionReview,
    DuplicateCheckRequest, DuplicateMatchResponse
)
from app.modules.governance.services.suggestions_service import SuggestionsService

router = APIRouter()

@router.post("", response_model=TempleSuggestionResponse, status_code=201)
async def suggest_new_temple(
    payload: TempleSuggestionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """
    Submit a temple suggestion. Devotees only. Enforces 3 submissions per day limit.
    """
    user_id = UUID(current_user.sub)
    client_ip = request.client.host if request.client else None
    suggestion = await SuggestionsService.create_suggestion(db, user_id, payload, client_ip)
    await db.commit()
    return await SuggestionsService.get_suggestion_details(db, suggestion.id)

@router.post("/check-duplicates", response_model=List[DuplicateMatchResponse])
async def check_duplicate_temples(
    payload: DuplicateCheckRequest,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """
    Check for potential matching duplicate temples in the directory.
    """
    matches = await SuggestionsService.check_duplicates(
        db, payload.name, payload.district_id, payload.pincode
    )
    return matches

@router.get("/my", response_model=List[TempleSuggestionResponse])
async def list_my_suggestions(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user),
):
    """
    List all suggestions submitted by the current devotee.
    """
    user_id = UUID(current_user.sub)
    # Reuse list suggestions but scoped to devotee
    suggestions, _ = await SuggestionsService.list_suggestions(
        db, status=None, state_id=None, district_id=None, page=1, limit=100
    )
    # Filter locally or scope query (service returns all; let's filter by submitted_by)
    user_suggestions = [s for s in suggestions if s.submitted_by == user_id]
    return user_suggestions

@router.get("/admin")
async def list_suggestions_for_admin(
    status: Optional[str] = Query(None, description="Filter by status (PENDING, APPROVED, REJECTED, MERGED)"),
    state_id: Optional[UUID] = Query(None),
    district_id: Optional[UUID] = Query(None),
    min_score: Optional[int] = Query(None, ge=0, le=100),
    max_score: Optional[int] = Query(None, ge=0, le=100),
    search_query: Optional[str] = Query(None),
    sort_by: str = Query("newest", description="newest, highest_confidence, lowest_confidence"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_system_permission("MANAGE_LEADS")),
):
    """
    List suggestions for admins. Supports filters and sorting. Requires MANAGE_LEADS permission.
    """
    suggestions, total = await SuggestionsService.list_suggestions(
        db,
        status=status,
        state_id=state_id,
        district_id=district_id,
        min_score=min_score,
        max_score=max_score,
        search_query=search_query,
        sort_by=sort_by,
        page=page,
        limit=limit
    )
    return {
        "suggestions": suggestions,
        "total": total
    }

@router.get("/admin/{id}", response_model=TempleSuggestionResponse)
async def get_suggestion(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_system_permission("MANAGE_LEADS")),
):
    """
    Fetch full suggestion details for admin triage. Requires MANAGE_LEADS.
    """
    suggestion = await SuggestionsService.get_suggestion_details(db, id)
    return suggestion

@router.post("/admin/{id}/review", response_model=TempleSuggestionResponse)
async def review_suggestion(
    id: UUID,
    payload: TempleSuggestionReview,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_system_permission("MANAGE_LEADS")),
):
    """
    Approve, reject, or merge a temple suggestion. Requires MANAGE_LEADS.
    """
    reviewer_id = UUID(current_user.sub)
    suggestion = await SuggestionsService.review_suggestion(db, id, reviewer_id, payload)
    await db.commit()
    return await SuggestionsService.get_suggestion_details(db, suggestion.id)
