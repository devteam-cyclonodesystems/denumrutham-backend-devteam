from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID
from typing import List
from pydantic import BaseModel, ConfigDict
from datetime import datetime

from app.core.database import get_db
from app.core.deps import get_current_user, get_current_temple_id
from app.schemas.domain import TokenData
from app.services.notification_service import NotificationService
from app.core.response import api_response, paginated_response
from app.core.pagination import PaginationParams, get_pagination

router = APIRouter()

class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    message: str
    is_read: bool
    created_at: datetime

@router.get("/")
async def get_notifications(
    pagination: PaginationParams = Depends(get_pagination),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id),
    db: AsyncSession = Depends(get_db)
):
    notifs = await NotificationService.get_user_notifications(
        db=db,
        temple_id=UUID(temple_id),
        user_id=UUID(current_user.sub),
        role=current_user.role,
        limit=pagination.limit
    )
    # mock total count since notification_service doesn't return it yet.
    total = len(notifs)
    notif_list = [NotificationResponse.model_validate(n).model_dump() for n in notifs]
    return paginated_response(
        data=notif_list,
        total_count=total, 
        page=pagination.page, 
        page_size=pagination.page_size, 
        message="Notifications retrieved"
    )

@router.post("/{notification_id}/mark-read")
async def mark_notification_read(
    notification_id: UUID,
    current_user: TokenData = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    notif = await NotificationService.mark_as_read(db, notification_id, UUID(current_user.sub))
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    await db.commit()
    return api_response(message="Notification marked as read")
