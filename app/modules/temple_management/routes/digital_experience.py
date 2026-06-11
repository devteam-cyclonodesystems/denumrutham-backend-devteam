from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
from uuid import UUID

from app.api.deps import get_db, get_current_user, get_current_temple_id, require_permission, require_system_permission, enforce_active_subscription
from app.schemas.domain import TokenData
from app.modules.temple_management.services.digital_experience_service import DigitalExperienceService
from app.modules.temple_management.schemas.digital_experience import (
    TempleWebsiteSettingsUpdate, TempleWebsiteSettingsResponse,
    TempleAnnouncementCreate, TempleAnnouncementUpdate, TempleAnnouncementResponse,
    TempleActivityCreate, TempleActivityUpdate, TempleActivityResponse,
    TempleImageCreate, TempleImageUpdate, TempleImageResponse,
    TempleFestivalCreate, TempleFestivalUpdate, TempleFestivalResponse,
)

router = APIRouter()


# =============================================================================
# WEBSITE SETTINGS ROUTE
# =============================================================================
@router.get(
    "/website-settings",
    response_model=TempleWebsiteSettingsResponse,
    tags=["digital-experience-settings"]
)
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("website", "view")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Retrieve website settings for the manager's temple."""
    return await DigitalExperienceService.get_or_create_settings(db, UUID(temple_id))


@router.put(
    "/website-settings",
    response_model=TempleWebsiteSettingsResponse,
    dependencies=[Depends(enforce_active_subscription)],
    tags=["digital-experience-settings"]
)
async def update_settings(
    data: TempleWebsiteSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("website", "edit")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Update website settings for the manager's temple."""
    return await DigitalExperienceService.update_settings(
        db=db,
        temple_id=UUID(temple_id),
        data=data.model_dump(exclude_unset=True),
        current_user_id=UUID(current_user.sub),
        role=current_user.role,
    )


# =============================================================================
# WEBSITE PUBLICATION ROUTES
# =============================================================================
@router.get(
    "/website-settings/status",
    tags=["digital-experience-settings"]
)
async def get_publication_status(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("website", "view")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Get the publication status of the temple website."""
    return await DigitalExperienceService.get_publication_status(db, UUID(temple_id))


@router.post(
    "/website-settings/publish",
    dependencies=[Depends(enforce_active_subscription)],
    tags=["digital-experience-settings"]
)
async def publish_website(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("website", "publish")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Publish the current draft website settings."""
    live = await DigitalExperienceService.publish_settings(
        db=db,
        temple_id=UUID(temple_id),
        current_user_id=UUID(current_user.sub),
        role=current_user.role,
    )
    return {
        "status": "success",
        "message": "Website published successfully",
        "publishedAt": live.published_at.isoformat() if live.published_at else None,
        "version": live.version
    }


@router.post(
    "/website-settings/unpublish",
    dependencies=[Depends(enforce_active_subscription)],
    tags=["digital-experience-settings"]
)
async def unpublish_website(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("website", "publish")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Unpublish the temple website, deleting its public live snapshot."""
    await DigitalExperienceService.unpublish_settings(
        db=db,
        temple_id=UUID(temple_id),
        current_user_id=UUID(current_user.sub),
        role=current_user.role,
    )
    return {
        "status": "success",
        "message": "Website unpublished successfully"
    }


@router.post(
    "/website-settings/submit-review",
    dependencies=[Depends(enforce_active_subscription)],
    tags=["digital-experience-settings"]
)
async def submit_website_review(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("website", "edit")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Submit website draft changes for review (GOVERNED temples)."""
    draft = await DigitalExperienceService.submit_settings_for_review(
        db=db,
        temple_id=UUID(temple_id),
        current_user_id=UUID(current_user.sub)
    )
    return {
        "status": "success",
        "message": "Website changes submitted for review",
        "approval_status": draft.approval_status
    }


@router.get(
    "/website-settings/pending",
    tags=["digital-experience-admin"]
)
async def list_pending_website_reviews(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_system_permission("APPROVE_WEBSITE_CHANGES")),
):
    """List all website settings drafts waiting for review. (Admin only)."""
    from app.models.domain import TempleWebsiteSettings, Temple
    from sqlalchemy.orm import selectinload
    from sqlalchemy import select
    
    stmt = (
        select(TempleWebsiteSettings)
        .options(selectinload(TempleWebsiteSettings.temple))
        .filter(TempleWebsiteSettings.approval_status == "PENDING_REVIEW")
    )
    res = await db.execute(stmt)
    drafts = res.scalars().all()
    
    results = []
    for d in drafts:
        results.append({
            "temple_id": str(d.temple_id),
            "temple_name": d.temple.name if d.temple else "",
            "theme_name": d.theme_name,
            "primary_color": d.primary_color,
            "submitted_by": str(d.submitted_by) if d.submitted_by else None,
            "submitted_at": d.submitted_at.isoformat() if d.submitted_at else None,
        })
    return results


@router.get(
    "/website-settings/{target_temple_id}",
    response_model=TempleWebsiteSettingsResponse,
    tags=["digital-experience-admin"]
)
async def get_target_website_settings(
    target_temple_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_system_permission("APPROVE_WEBSITE_CHANGES")),
):
    """Retrieve website settings for a specific target temple. (Admin only)."""
    return await DigitalExperienceService.get_or_create_settings(db, target_temple_id)


@router.get(
    "/website-settings/{target_temple_id}/live",
    tags=["digital-experience-admin"]
)
async def get_target_live_website_settings(
    target_temple_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_system_permission("APPROVE_WEBSITE_CHANGES")),
):
    """Retrieve live published website settings for a specific target temple. (Admin only)."""
    from app.models.domain import TempleWebsiteSettingsLive
    from sqlalchemy.future import select
    
    stmt = select(TempleWebsiteSettingsLive).filter(TempleWebsiteSettingsLive.temple_id == target_temple_id)
    res = await db.execute(stmt)
    live = res.scalars().first()
    if not live:
        return {"settings_snapshot": None}
    return live


from pydantic import BaseModel as RouteBaseModel

class WebsiteReviewPayload(RouteBaseModel):
    status: str
    rejection_reason: Optional[str] = None



@router.post(
    "/website-settings/{target_temple_id}/review",
    tags=["digital-experience-admin"]
)
async def review_website_submission(
    target_temple_id: UUID,
    payload: WebsiteReviewPayload,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_system_permission("APPROVE_WEBSITE_CHANGES")),
):
    """Approve or reject a pending website builder submission. (Admin only)."""
    if payload.status.upper() == "APPROVED":
        live = await DigitalExperienceService.approve_settings_submission(
            db=db,
            temple_id=target_temple_id,
            reviewer_id=UUID(current_user.sub)
        )
        return {
            "status": "success",
            "message": "Website changes approved and published live",
            "version": live.version
        }
    elif payload.status.upper() == "REJECTED":
        if not payload.rejection_reason or not payload.rejection_reason.strip():
            raise HTTPException(status_code=400, detail="Rejection reason is required")
        draft = await DigitalExperienceService.reject_settings_submission(
            db=db,
            temple_id=target_temple_id,
            reviewer_id=UUID(current_user.sub),
            reason=payload.rejection_reason
        )
        return {
            "status": "success",
            "message": "Website changes rejected",
            "rejection_reason": draft.rejection_reason
        }
    else:
        raise HTTPException(status_code=400, detail="Invalid review status. Must be APPROVED or REJECTED.")


# =============================================================================
# ANNOUNCEMENTS ROUTES
# =============================================================================
@router.get(
    "/announcements",
    response_model=List[TempleAnnouncementResponse],
    tags=["digital-experience-announcements"]
)
async def list_announcements(
    include_inactive: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("communication", "view")),
    temple_id: str = Depends(get_current_temple_id),
):
    """List announcements for the manager's temple."""
    return await DigitalExperienceService.list_announcements(
        db, UUID(temple_id), include_inactive=include_inactive
    )


@router.post(
    "/announcements",
    response_model=TempleAnnouncementResponse,
    status_code=201,
    tags=["digital-experience-announcements"]
)
async def create_announcement(
    data: TempleAnnouncementCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("communication", "manage")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Create a new announcement for the manager's temple."""
    return await DigitalExperienceService.create_announcement(
        db=db,
        temple_id=UUID(temple_id),
        data=data.model_dump(exclude_unset=True),
        current_user_id=UUID(current_user.sub),
        role=current_user.role,
    )


@router.put(
    "/announcements/{announcement_id}",
    response_model=TempleAnnouncementResponse,
    tags=["digital-experience-announcements"]
)
async def update_announcement(
    announcement_id: UUID,
    data: TempleAnnouncementUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("communication", "manage")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Update an existing announcement."""
    return await DigitalExperienceService.update_announcement(
        db=db,
        temple_id=UUID(temple_id),
        announcement_id=announcement_id,
        data=data.model_dump(exclude_unset=True),
        current_user_id=UUID(current_user.sub),
        role=current_user.role,
    )


@router.delete(
    "/announcements/{announcement_id}",
    tags=["digital-experience-announcements"]
)
async def delete_announcement(
    announcement_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("communication", "manage")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Delete an announcement."""
    await DigitalExperienceService.delete_announcement(
        db=db,
        temple_id=UUID(temple_id),
        announcement_id=announcement_id,
        current_user_id=UUID(current_user.sub),
        role=current_user.role,
    )
    return {"status": "success", "message": "Announcement deleted successfully"}


# =============================================================================
# ACTIVITIES ROUTES
# =============================================================================
@router.get(
    "/activities",
    response_model=List[TempleActivityResponse],
    tags=["digital-experience-activities"]
)
async def list_activities(
    include_inactive: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("communication", "view")),
    temple_id: str = Depends(get_current_temple_id),
):
    """List activities for the manager's temple."""
    return await DigitalExperienceService.list_activities(
        db, UUID(temple_id), include_inactive=include_inactive
    )


@router.post(
    "/activities",
    response_model=TempleActivityResponse,
    status_code=201,
    tags=["digital-experience-activities"]
)
async def create_activity(
    data: TempleActivityCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("communication", "manage")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Create a new activity for the manager's temple."""
    return await DigitalExperienceService.create_activity(
        db=db,
        temple_id=UUID(temple_id),
        data=data.model_dump(exclude_unset=True),
        current_user_id=UUID(current_user.sub),
        role=current_user.role,
    )


@router.put(
    "/activities/{activity_id}",
    response_model=TempleActivityResponse,
    tags=["digital-experience-activities"]
)
async def update_activity(
    activity_id: UUID,
    data: TempleActivityUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("communication", "manage")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Update an existing activity."""
    return await DigitalExperienceService.update_activity(
        db=db,
        temple_id=UUID(temple_id),
        activity_id=activity_id,
        data=data.model_dump(exclude_unset=True),
        current_user_id=UUID(current_user.sub),
        role=current_user.role,
    )


@router.delete(
    "/activities/{activity_id}",
    tags=["digital-experience-activities"]
)
async def delete_activity(
    activity_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("communication", "manage")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Delete an activity."""
    await DigitalExperienceService.delete_activity(
        db=db,
        temple_id=UUID(temple_id),
        activity_id=activity_id,
        current_user_id=UUID(current_user.sub),
        role=current_user.role,
    )
    return {"status": "success", "message": "Activity deleted successfully"}


# =============================================================================
# IMAGES ROUTES
# =============================================================================
@router.get(
    "/images",
    response_model=List[TempleImageResponse],
    tags=["digital-experience-images"]
)
async def list_images(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("website", "view")),
    temple_id: str = Depends(get_current_temple_id),
):
    """List gallery images for the manager's temple."""
    return await DigitalExperienceService.list_images(db, UUID(temple_id))


@router.post(
    "/images",
    response_model=TempleImageResponse,
    status_code=201,
    tags=["digital-experience-images"]
)
async def create_image(
    data: TempleImageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("website", "edit")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Register/add a new image to the manager's temple gallery."""
    return await DigitalExperienceService.create_image(
        db=db,
        temple_id=UUID(temple_id),
        data=data.model_dump(exclude_unset=True),
        current_user_id=UUID(current_user.sub),
        role=current_user.role,
    )


@router.put(
    "/images/{image_id}",
    response_model=TempleImageResponse,
    tags=["digital-experience-images"]
)
async def update_image(
    image_id: UUID,
    data: TempleImageUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("website", "edit")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Update caption/category of a gallery image."""
    return await DigitalExperienceService.update_image(
        db=db,
        temple_id=UUID(temple_id),
        image_id=image_id,
        data=data.model_dump(exclude_unset=True),
        current_user_id=UUID(current_user.sub),
        role=current_user.role,
    )


@router.delete(
    "/images/{image_id}",
    tags=["digital-experience-images"]
)
async def delete_image(
    image_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("website", "edit")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Delete a gallery image."""
    await DigitalExperienceService.delete_image(
        db=db,
        temple_id=UUID(temple_id),
        image_id=image_id,
        current_user_id=UUID(current_user.sub),
        role=current_user.role,
    )
    return {"status": "success", "message": "Image deleted successfully"}


# =============================================================================
# FESTIVALS ROUTES
# =============================================================================
@router.get(
    "/festivals",
    response_model=List[TempleFestivalResponse],
    tags=["digital-experience-festivals"]
)
async def list_festivals(
    include_inactive: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("festivals", "view")),
    temple_id: str = Depends(get_current_temple_id),
):
    """List festivals for the manager's temple."""
    return await DigitalExperienceService.list_festivals(
        db, UUID(temple_id), include_inactive=include_inactive
    )


@router.post(
    "/festivals",
    response_model=TempleFestivalResponse,
    status_code=201,
    tags=["digital-experience-festivals"]
)
async def create_festival(
    data: TempleFestivalCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("festivals", "create")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Create a new festival for the manager's temple."""
    return await DigitalExperienceService.create_festival(
        db=db,
        temple_id=UUID(temple_id),
        data=data.model_dump(exclude_unset=True),
        current_user_id=UUID(current_user.sub),
        role=current_user.role,
    )


@router.put(
    "/festivals/{festival_id}",
    response_model=TempleFestivalResponse,
    tags=["digital-experience-festivals"]
)
async def update_festival(
    festival_id: UUID,
    data: TempleFestivalUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("festivals", "edit")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Update an existing festival."""
    return await DigitalExperienceService.update_festival(
        db=db,
        temple_id=UUID(temple_id),
        festival_id=festival_id,
        data=data.model_dump(exclude_unset=True),
        current_user_id=UUID(current_user.sub),
        role=current_user.role,
    )


@router.delete(
    "/festivals/{festival_id}",
    tags=["digital-experience-festivals"]
)
async def delete_festival(
    festival_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(require_permission("festivals", "delete")),
    temple_id: str = Depends(get_current_temple_id),
):
    """Delete a festival."""
    await DigitalExperienceService.delete_festival(
        db=db,
        temple_id=UUID(temple_id),
        festival_id=festival_id,
        current_user_id=UUID(current_user.sub),
        role=current_user.role,
    )
    return {"status": "success", "message": "Festival deleted successfully"}
