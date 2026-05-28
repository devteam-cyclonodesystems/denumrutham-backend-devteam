from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from app.api.deps import get_db
from app.schemas.devotee_portal import (
    TempleListItem, TempleListResponse, TempleProfileResponse,
    TempleServiceResponse, TempleImageResponse,
)
from app.services.temple_service import TempleService
from app.core.response import api_response, paginated_response
from app.core.pagination import PaginationParams, get_pagination

router = APIRouter()


@router.get("/")
async def list_temples(
    search: Optional[str] = None,
    pagination: PaginationParams = Depends(get_pagination),
    db: AsyncSession = Depends(get_db),
):
    """List all temples with basic info for the tile view. Public endpoint."""
    items, total = await TempleService.list_temples(db, skip=pagination.offset, limit=pagination.limit, search=search)
    temple_items = [TempleListItem(**item).model_dump() for item in items]
    return paginated_response(
        data=temple_items,
        total_count=total,
        page=pagination.page,
        page_size=pagination.page_size,
        message="Temples retrieved successfully"
    )


@router.get("/{temple_id}")
async def get_temple(temple_id: str, db: AsyncSession = Depends(get_db)):
    """Get full temple profile including images. Public endpoint."""
    data = await TempleService.get_temple(db, temple_id)
    images = [TempleImageResponse(**img).model_dump() for img in data.pop("images")]
    profile = TempleProfileResponse(**data, images=images).model_dump()
    return api_response(data=profile, message="Temple profile retrieved")


@router.get("/{temple_id}/services")
async def get_temple_services(temple_id: str, db: AsyncSession = Depends(get_db)):
    """Get active services for a temple. Public endpoint."""
    services = await TempleService.get_temple_services(db, temple_id)
    return api_response(data=[s.model_dump() for s in services], message="Temple services retrieved")
