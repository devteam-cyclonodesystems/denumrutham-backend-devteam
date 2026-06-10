from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from uuid import UUID
from fastapi import HTTPException
from datetime import datetime, timezone, date, time
from typing import List, Optional

from app.models.domain import (
    TempleWebsiteSettings,
    TempleAnnouncement,
    TempleActivity,
    TempleFestival,
    TempleImage,
    ImageCategory,
    ActivityStatus,
    TempleWebsiteSettingsLive,
    Temple,
)
from app.modules.audit.services.audit_service import AuditService


def _serialize_for_audit(data: Optional[dict]) -> Optional[dict]:
    if data is None:
        return None
    res = {}
    for k, v in data.items():
        if isinstance(v, (date, time, datetime)):
            res[k] = v.isoformat()
        elif isinstance(v, UUID):
            res[k] = str(v)
        elif isinstance(v, list):
            res[k] = [
                _serialize_for_audit(item) if isinstance(item, dict)
                else (str(item) if isinstance(item, UUID) else item)
                for item in v
            ]
        elif isinstance(v, dict):
            res[k] = _serialize_for_audit(v)
        else:
            res[k] = v
    return res


class DigitalExperienceService:

    # =========================================================================
    # WEBSITE SETTINGS CRUD
    # =========================================================================
    @staticmethod
    async def get_or_create_settings(db: AsyncSession, temple_id: UUID) -> TempleWebsiteSettings:
        result = await db.execute(
            select(TempleWebsiteSettings).filter(TempleWebsiteSettings.temple_id == temple_id)
        )
        settings = result.scalars().first()
        
        if not settings:
            async with db.begin_nested():
                settings = TempleWebsiteSettings(
                    temple_id=temple_id,
                    theme_name="default",
                    primary_color="#ff6600",
                    secondary_color="#ffcc00",
                    logo_url=None,
                    hero_layout="split",
                    section_order=["hero", "about", "deities", "announcements", "activities", "gallery", "offerings", "location"],
                    enable_mantras=True,
                    enable_festivals=True,
                    enable_donations=True,
                    enable_hall_booking=True,
                    enable_store=True,
                    seo_keywords=None,
                    og_image_url=None,
                    hero_title=None,
                    hero_subtitle=None,
                    notice_board_content=None,
                )
                db.add(settings)
            await db.commit()
            await db.refresh(settings)
            
        return settings

    @staticmethod
    async def update_settings(
        db: AsyncSession,
        temple_id: UUID,
        data: dict,
        current_user_id: UUID,
        role: str
    ) -> TempleWebsiteSettings:
        settings = await DigitalExperienceService.get_or_create_settings(db, temple_id)
        
        old_value = {
            c.name: getattr(settings, c.name) 
            for c in TempleWebsiteSettings.__table__.columns 
            if c.name not in ["id", "temple_id", "created_at", "updated_at"]
        }
        
        for key, value in data.items():
            if hasattr(settings, key) and key not in ["id", "temple_id", "created_at", "updated_at"]:
                setattr(settings, key, value)
                
        settings.updated_at = datetime.now(timezone.utc)
        
        new_value = {
            c.name: getattr(settings, c.name) 
            for c in TempleWebsiteSettings.__table__.columns 
            if c.name not in ["id", "temple_id", "created_at", "updated_at"]
        }
        
        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=current_user_id,
            role=role,
            module_name="digital_experience",
            action="UPDATE_WEBSITE_SETTINGS",
            action_type="UPDATE",
            entity_id=str(settings.id),
            old_value=_serialize_for_audit(old_value),
            new_value=_serialize_for_audit(new_value),
            details=f"Updated website settings for temple {temple_id}"
        )
        
        await db.commit()
        await db.refresh(settings)
        return settings


    # =========================================================================
    # ANNOUNCEMENTS CRUD
    # =========================================================================
    @staticmethod
    async def list_announcements(
        db: AsyncSession,
        temple_id: UUID,
        include_inactive: bool = False
    ) -> List[TempleAnnouncement]:
        stmt = select(TempleAnnouncement).filter(TempleAnnouncement.temple_id == temple_id)
        if not include_inactive:
            stmt = stmt.filter(TempleAnnouncement.is_active == True)
            
        stmt = stmt.order_by(
            TempleAnnouncement.is_pinned.desc(),
            TempleAnnouncement.display_order.asc(),
            TempleAnnouncement.created_at.desc()
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def create_announcement(
        db: AsyncSession,
        temple_id: UUID,
        data: dict,
        current_user_id: UUID,
        role: str
    ) -> TempleAnnouncement:
        announcement = TempleAnnouncement(
            temple_id=temple_id,
            created_by=current_user_id,
            title=data.get("title"),
            content=data.get("content"),
            is_active=data.get("is_active", True),
            is_pinned=data.get("is_pinned", False),
            priority=data.get("priority", 0),
            display_order=data.get("display_order", 0),
            start_date=data.get("start_date"),
            expiry_date=data.get("expiry_date"),
        )
        db.add(announcement)
        await db.flush()
        
        new_val = {
            c.name: getattr(announcement, c.name)
            for c in TempleAnnouncement.__table__.columns
            if c.name not in ["id", "temple_id", "created_at", "updated_at"]
        }
        
        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=current_user_id,
            role=role,
            module_name="digital_experience",
            action="CREATE_ANNOUNCEMENT",
            action_type="CREATE",
            entity_id=str(announcement.id),
            new_value=_serialize_for_audit(new_val),
            details=f"Created announcement: {announcement.title}"
        )
        
        await db.commit()
        await db.refresh(announcement)
        
        # Dispatch follower notifications in the background
        try:
            from app.modules.temple_management.services.notification_service import NotificationService
            NotificationService.dispatch_follower_notifications_background(
                temple_id=temple_id,
                category="ANNOUNCEMENT",
                title=f"New Announcement: {announcement.title}",
                message=announcement.content or "",
                payload={"announcement_id": str(announcement.id)}
            )
        except Exception as e:
            logger.error("Failed to trigger follower notifications for announcement: %s", e)
            
        return announcement

    @staticmethod
    async def update_announcement(
        db: AsyncSession,
        temple_id: UUID,
        announcement_id: UUID,
        data: dict,
        current_user_id: UUID,
        role: str
    ) -> TempleAnnouncement:
        result = await db.execute(
            select(TempleAnnouncement).filter(
                TempleAnnouncement.id == announcement_id,
                TempleAnnouncement.temple_id == temple_id
            )
        )
        announcement = result.scalars().first()
        if not announcement:
            raise HTTPException(status_code=404, detail="Announcement not found")
            
        old_val = {
            c.name: getattr(announcement, c.name)
            for c in TempleAnnouncement.__table__.columns
            if c.name not in ["id", "temple_id", "created_at", "updated_at"]
        }
        
        for key, value in data.items():
            if hasattr(announcement, key) and key not in ["id", "temple_id", "created_at", "updated_at", "created_by"]:
                setattr(announcement, key, value)
                
        announcement.updated_at = datetime.now(timezone.utc)
        
        new_val = {
            c.name: getattr(announcement, c.name)
            for c in TempleAnnouncement.__table__.columns
            if c.name not in ["id", "temple_id", "created_at", "updated_at"]
        }
        
        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=current_user_id,
            role=role,
            module_name="digital_experience",
            action="UPDATE_ANNOUNCEMENT",
            action_type="UPDATE",
            entity_id=str(announcement.id),
            old_value=_serialize_for_audit(old_val),
            new_value=_serialize_for_audit(new_val),
            details=f"Updated announcement: {announcement.title}"
        )
        
        await db.commit()
        await db.refresh(announcement)
        return announcement

    @staticmethod
    async def delete_announcement(
        db: AsyncSession,
        temple_id: UUID,
        announcement_id: UUID,
        current_user_id: UUID,
        role: str
    ) -> bool:
        result = await db.execute(
            select(TempleAnnouncement).filter(
                TempleAnnouncement.id == announcement_id,
                TempleAnnouncement.temple_id == temple_id
            )
        )
        announcement = result.scalars().first()
        if not announcement:
            raise HTTPException(status_code=404, detail="Announcement not found")
            
        old_val = {
            c.name: getattr(announcement, c.name)
            for c in TempleAnnouncement.__table__.columns
            if c.name not in ["id", "temple_id", "created_at", "updated_at"]
        }
        
        await db.delete(announcement)
        
        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=current_user_id,
            role=role,
            module_name="digital_experience",
            action="DELETE_ANNOUNCEMENT",
            action_type="DELETE",
            entity_id=str(announcement_id),
            old_value=_serialize_for_audit(old_val),
            details=f"Deleted announcement: {announcement.title}"
        )
        
        await db.commit()
        return True


    # =========================================================================
    # ACTIVITIES CRUD
    # =========================================================================
    @staticmethod
    async def list_activities(
        db: AsyncSession,
        temple_id: UUID,
        include_inactive: bool = False
    ) -> List[TempleActivity]:
        stmt = select(TempleActivity).filter(TempleActivity.temple_id == temple_id)
        if not include_inactive:
            stmt = stmt.filter(TempleActivity.is_active == True)
            
        stmt = stmt.order_by(
            TempleActivity.activity_date.asc(),
            TempleActivity.start_time.asc()
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def create_activity(
        db: AsyncSession,
        temple_id: UUID,
        data: dict,
        current_user_id: UUID,
        role: str
    ) -> TempleActivity:
        activity = TempleActivity(
            temple_id=temple_id,
            created_by=current_user_id,
            title=data.get("title"),
            description=data.get("description"),
            activity_date=data.get("activity_date"),
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            location=data.get("location"),
            is_active=data.get("is_active", True),
            status=data.get("status", ActivityStatus.UPCOMING),
            livestream_url=data.get("livestream_url"),
        )
        db.add(activity)
        await db.flush()
        
        new_val = {
            c.name: getattr(activity, c.name)
            for c in TempleActivity.__table__.columns
            if c.name not in ["id", "temple_id", "created_at", "updated_at"]
        }
        
        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=current_user_id,
            role=role,
            module_name="digital_experience",
            action="CREATE_ACTIVITY",
            action_type="CREATE",
            entity_id=str(activity.id),
            new_value=_serialize_for_audit(new_val),
            details=f"Created activity: {activity.title}"
        )
        
        await db.commit()
        await db.refresh(activity)
        
        # Dispatch follower notifications in the background
        try:
            from app.modules.temple_management.services.notification_service import NotificationService
            NotificationService.dispatch_follower_notifications_background(
                temple_id=temple_id,
                category="EVENT",
                title=f"New Activity: {activity.title}",
                message=activity.description or "",
                payload={"activity_id": str(activity.id)}
            )
        except Exception as e:
            logger.error("Failed to trigger follower notifications for activity: %s", e)
            
        return activity

    @staticmethod
    async def update_activity(
        db: AsyncSession,
        temple_id: UUID,
        activity_id: UUID,
        data: dict,
        current_user_id: UUID,
        role: str
    ) -> TempleActivity:
        result = await db.execute(
            select(TempleActivity).filter(
                TempleActivity.id == activity_id,
                TempleActivity.temple_id == temple_id
            )
        )
        activity = result.scalars().first()
        if not activity:
            raise HTTPException(status_code=404, detail="Activity not found")
            
        old_val = {
            c.name: getattr(activity, c.name)
            for c in TempleActivity.__table__.columns
            if c.name not in ["id", "temple_id", "created_at", "updated_at"]
        }
        
        for key, value in data.items():
            if hasattr(activity, key) and key not in ["id", "temple_id", "created_at", "updated_at", "created_by"]:
                setattr(activity, key, value)
                
        activity.updated_at = datetime.now(timezone.utc)
        
        new_val = {
            c.name: getattr(activity, c.name)
            for c in TempleActivity.__table__.columns
            if c.name not in ["id", "temple_id", "created_at", "updated_at"]
        }
        
        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=current_user_id,
            role=role,
            module_name="digital_experience",
            action="UPDATE_ACTIVITY",
            action_type="UPDATE",
            entity_id=str(activity.id),
            old_value=_serialize_for_audit(old_val),
            new_value=_serialize_for_audit(new_val),
            details=f"Updated activity: {activity.title}"
        )
        
        await db.commit()
        await db.refresh(activity)
        return activity

    @staticmethod
    async def delete_activity(
        db: AsyncSession,
        temple_id: UUID,
        activity_id: UUID,
        current_user_id: UUID,
        role: str
    ) -> bool:
        result = await db.execute(
            select(TempleActivity).filter(
                TempleActivity.id == activity_id,
                TempleActivity.temple_id == temple_id
            )
        )
        activity = result.scalars().first()
        if not activity:
            raise HTTPException(status_code=404, detail="Activity not found")
            
        old_val = {
            c.name: getattr(activity, c.name)
            for c in TempleActivity.__table__.columns
            if c.name not in ["id", "temple_id", "created_at", "updated_at"]
        }
        
        await db.delete(activity)
        
        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=current_user_id,
            role=role,
            module_name="digital_experience",
            action="DELETE_ACTIVITY",
            action_type="DELETE",
            entity_id=str(activity_id),
            old_value=_serialize_for_audit(old_val),
            details=f"Deleted activity: {activity.title}"
        )
        
        await db.commit()
        return True


    # =========================================================================
    # FESTIVALS CRUD
    # =========================================================================
    @staticmethod
    async def list_festivals(
        db: AsyncSession,
        temple_id: UUID,
        include_inactive: bool = False
    ) -> List[TempleFestival]:
        stmt = select(TempleFestival).filter(TempleFestival.temple_id == temple_id)
        if not include_inactive:
            stmt = stmt.filter(TempleFestival.is_active == True)
        stmt = stmt.order_by(
            TempleFestival.start_date.asc(),
            TempleFestival.priority.desc()
        )
        result = await db.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def create_festival(
        db: AsyncSession,
        temple_id: UUID,
        data: dict,
        current_user_id: UUID,
        role: str
    ) -> TempleFestival:
        festival = TempleFestival(
            temple_id=temple_id,
            name=data.get("name"),
            description=data.get("description"),
            start_date=data.get("start_date"),
            end_date=data.get("end_date"),
            priority=data.get("priority", 0),
            banner_image=data.get("banner_image"),
            catalogue_urls=data.get("catalogue_urls", []),
            is_active=data.get("is_active", True)
        )
        db.add(festival)
        await db.flush()

        new_val = {
            c.name: getattr(festival, c.name)
            for c in TempleFestival.__table__.columns
            if c.name not in ["id", "temple_id", "created_at", "updated_at"]
        }

        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=current_user_id,
            role=role,
            module_name="digital_experience",
            action="CREATE_FESTIVAL",
            action_type="CREATE",
            entity_id=str(festival.id),
            new_value=_serialize_for_audit(new_val),
            details=f"Created festival: {festival.name}"
        )

        await db.commit()
        await db.refresh(festival)
        return festival

    @staticmethod
    async def update_festival(
        db: AsyncSession,
        temple_id: UUID,
        festival_id: UUID,
        data: dict,
        current_user_id: UUID,
        role: str
    ) -> TempleFestival:
        result = await db.execute(
            select(TempleFestival).filter(
                TempleFestival.id == festival_id,
                TempleFestival.temple_id == temple_id
            )
        )
        festival = result.scalars().first()
        if not festival:
            raise HTTPException(status_code=404, detail="Festival not found")

        old_val = {
            c.name: getattr(festival, c.name)
            for c in TempleFestival.__table__.columns
            if c.name not in ["id", "temple_id", "created_at", "updated_at"]
        }

        for key, value in data.items():
            if hasattr(festival, key) and key not in ["id", "temple_id", "created_at", "updated_at"]:
                setattr(festival, key, value)

        festival.updated_at = datetime.now(timezone.utc)

        new_val = {
            c.name: getattr(festival, c.name)
            for c in TempleFestival.__table__.columns
            if c.name not in ["id", "temple_id", "created_at", "updated_at"]
        }

        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=current_user_id,
            role=role,
            module_name="digital_experience",
            action="UPDATE_FESTIVAL",
            action_type="UPDATE",
            entity_id=str(festival.id),
            old_value=_serialize_for_audit(old_val),
            new_value=_serialize_for_audit(new_val),
            details=f"Updated festival: {festival.name}"
        )

        await db.commit()
        await db.refresh(festival)
        return festival

    @staticmethod
    async def delete_festival(
        db: AsyncSession,
        temple_id: UUID,
        festival_id: UUID,
        current_user_id: UUID,
        role: str
    ) -> bool:
        result = await db.execute(
            select(TempleFestival).filter(
                TempleFestival.id == festival_id,
                TempleFestival.temple_id == temple_id
            )
        )
        festival = result.scalars().first()
        if not festival:
            raise HTTPException(status_code=404, detail="Festival not found")

        old_val = {
            c.name: getattr(festival, c.name)
            for c in TempleFestival.__table__.columns
            if c.name not in ["id", "temple_id", "created_at", "updated_at"]
        }

        await db.delete(festival)

        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=current_user_id,
            role=role,
            module_name="digital_experience",
            action="DELETE_FESTIVAL",
            action_type="DELETE",
            entity_id=str(festival_id),
            old_value=_serialize_for_audit(old_val),
            details=f"Deleted festival: {festival.name}"
        )

        await db.commit()
        return True


    # =========================================================================
    # IMAGES CRUD
    # =========================================================================
    @staticmethod
    async def list_images(db: AsyncSession, temple_id: UUID) -> List[TempleImage]:
        result = await db.execute(
            select(TempleImage)
            .filter(TempleImage.temple_id == temple_id)
            .order_by(TempleImage.created_at.desc())
        )
        return result.scalars().all()

    @staticmethod
    async def create_image(
        db: AsyncSession,
        temple_id: UUID,
        data: dict,
        current_user_id: UUID,
        role: str
    ) -> TempleImage:
        image = TempleImage(
            temple_id=temple_id,
            image_url=data.get("image_url"),
            caption=data.get("caption", ""),
            category=data.get("category", ImageCategory.GALLERY),
        )
        db.add(image)
        await db.flush()
        
        new_val = {
            c.name: getattr(image, c.name)
            for c in TempleImage.__table__.columns
            if c.name not in ["id", "temple_id", "created_at"]
        }
        
        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=current_user_id,
            role=role,
            module_name="digital_experience",
            action="CREATE_IMAGE",
            action_type="CREATE",
            entity_id=str(image.id),
            new_value=_serialize_for_audit(new_val),
            details=f"Added temple image to gallery"
        )
        
        await db.commit()
        await db.refresh(image)
        return image

    @staticmethod
    async def update_image(
        db: AsyncSession,
        temple_id: UUID,
        image_id: UUID,
        data: dict,
        current_user_id: UUID,
        role: str
    ) -> TempleImage:
        result = await db.execute(
            select(TempleImage).filter(
                TempleImage.id == image_id,
                TempleImage.temple_id == temple_id
            )
        )
        image = result.scalars().first()
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")
            
        old_val = {
            c.name: getattr(image, c.name)
            for c in TempleImage.__table__.columns
            if c.name not in ["id", "temple_id", "created_at"]
        }
        
        for key, value in data.items():
            if hasattr(image, key) and key not in ["id", "temple_id", "created_at"]:
                setattr(image, key, value)
                
        new_val = {
            c.name: getattr(image, c.name)
            for c in TempleImage.__table__.columns
            if c.name not in ["id", "temple_id", "created_at"]
        }
        
        # Determine specific action/details based on is_visible updates
        action = "UPDATE_IMAGE"
        details = "Updated temple image"
        if "is_visible" in data:
            new_vis = data["is_visible"]
            if new_vis is True:
                action = "GALLERY_IMAGE_PUBLISHED"
                details = "Gallery Image Published"
            elif new_vis is False:
                action = "GALLERY_IMAGE_HIDDEN"
                details = "Gallery Image Hidden"
            else:
                action = "GALLERY_IMAGE_VISIBILITY_UPDATED"
                details = "Gallery Image Visibility Updated"

        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=current_user_id,
            role=role,
            module_name="digital_experience",
            action=action,
            action_type="UPDATE",
            entity_id=str(image.id),
            old_value=_serialize_for_audit(old_val),
            new_value=_serialize_for_audit(new_val),
            details=details
        )
        
        await db.commit()
        await db.refresh(image)
        return image

    @staticmethod
    async def delete_image(
        db: AsyncSession,
        temple_id: UUID,
        image_id: UUID,
        current_user_id: UUID,
        role: str
    ) -> bool:
        result = await db.execute(
            select(TempleImage).filter(
                TempleImage.id == image_id,
                TempleImage.temple_id == temple_id
            )
        )
        image = result.scalars().first()
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")
            
        old_val = {
            c.name: getattr(image, c.name)
            for c in TempleImage.__table__.columns
            if c.name not in ["id", "temple_id", "created_at"]
        }
        
        await db.delete(image)
        
        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=current_user_id,
            role=role,
            module_name="digital_experience",
            action="DELETE_IMAGE",
            action_type="DELETE",
            entity_id=str(image_id),
            old_value=_serialize_for_audit(old_val),
            details=f"Deleted temple image"
        )
        
        await db.commit()
        return True

    @staticmethod
    async def publish_settings(
        db: AsyncSession,
        temple_id: UUID,
        current_user_id: UUID,
        role: str
    ) -> TempleWebsiteSettingsLive:
        # We wrap the entire validation, serialization, upsert, and logging in a nested transaction
        async with db.begin_nested():
            # 1. Fetch Temple to perform validations
            temple_stmt = select(Temple).filter(Temple.id == temple_id)
            temple_res = await db.execute(temple_stmt)
            temple = temple_res.scalars().first()
            if not temple:
                raise HTTPException(status_code=404, detail="Temple not found")
                
            # Operational checks
            if not temple.is_active or temple.status != "APPROVED":
                raise HTTPException(
                    status_code=400, 
                    detail="Cannot publish website for an inactive or unapproved temple"
                )
                
            # Slug validation
            slug = temple.domain
            import re
            if not slug or not re.match(r"^[a-z0-9-]+$", slug):
                raise HTTPException(
                    status_code=400,
                    detail=f"Temple website has an invalid or missing slug: '{slug}'"
                )
                
            # Check unique slug conflict (ensure no other temple shares it)
            conflict_stmt = select(Temple).filter(Temple.domain == slug, Temple.id != temple_id)
            conflict_res = await db.execute(conflict_stmt)
            if conflict_res.scalars().first():
                raise HTTPException(
                    status_code=400,
                    detail=f"Temple slug conflict: '{slug}' is already in use by another temple"
                )

            # 2. Fetch the latest committed draft settings
            draft_stmt = select(TempleWebsiteSettings).filter(TempleWebsiteSettings.temple_id == temple_id)
            draft_res = await db.execute(draft_stmt)
            draft = draft_res.scalars().first()
            if not draft:
                raise HTTPException(
                    status_code=404, 
                    detail="Website settings not found. Save settings before publishing."
                )

            # 3. Build snapshot using explicit serialization contract
            try:
                # Merge draft feature visibility with default fallbacks
                default_visibility = {
                    "enablePoojaBooking": True,
                    "enableOfferings": True,
                    "enableStore": True,
                    "enableHallBooking": True,
                    "enableFollow": True,
                    "enableTempleAds": True,
                    "enablePlatformAds": True,
                    "enableGallery": True,
                    "enableActivities": True,
                    "enableNoticeBoard": True,
                    "enableAnnouncements": True,
                    "showLeftSpotlight": True,
                    "showRightSpotlight": True,
                    "showSidebarRail": True
                }
                feature_vis = dict(default_visibility)
                if draft.feature_visibility:
                    for k, v in draft.feature_visibility.items():
                        feature_vis[k] = v

                snapshot = {
                    "theme_name": draft.theme_name or "default",
                    "primary_color": draft.primary_color or "#ff6600",
                    "secondary_color": draft.secondary_color or "#ffcc00",
                    "logo_url": draft.logo_url,
                    "hero_layout": draft.hero_layout or "split",
                    "featureVisibility": feature_vis,
                    "section_order": draft.section_order or ["hero", "about", "deities", "announcements", "activities", "gallery", "offerings", "location"],
                    "enable_mantras": draft.enable_mantras if draft.enable_mantras is not None else True,
                    "enable_festivals": draft.enable_festivals if draft.enable_festivals is not None else True,
                    "enable_donations": draft.enable_donations if draft.enable_donations is not None else True,
                    "enable_hall_booking": draft.enable_hall_booking if draft.enable_hall_booking is not None else True,
                    "enable_store": draft.enable_store if draft.enable_store is not None else True,
                    "seo_keywords": draft.seo_keywords,
                    "og_image_url": draft.og_image_url,
                    "hero_title": draft.hero_title,
                    "hero_subtitle": draft.hero_subtitle,
                    "seo_description": draft.seo_description,
                    "notice_board_content": draft.notice_board_content,
                    "location_settings": draft.location_settings,
                    "timings_settings": draft.timings_settings,
                    "daily_activities_settings": draft.daily_activities_settings,
                }
            except Exception as e:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Failed to serialize settings snapshot: {str(e)}"
                )

            # 4. Upsert Live Snapshot
            live_stmt = select(TempleWebsiteSettingsLive).filter(TempleWebsiteSettingsLive.temple_id == temple_id)
            live_res = await db.execute(live_stmt)
            live = live_res.scalars().first()
            
            if live:
                old_version = live.version
                live.settings_snapshot = snapshot
                live.version = old_version + 1
                live.published_at = datetime.now(timezone.utc)
                live.published_by = current_user_id
                live.status = "PUBLISHED"
                live.schema_version = 1
            else:
                live = TempleWebsiteSettingsLive(
                    temple_id=temple_id,
                    settings_snapshot=snapshot,
                    version=1,
                    schema_version=1,
                    status="PUBLISHED",
                    published_at=datetime.now(timezone.utc),
                    published_by=current_user_id
                )
                db.add(live)

            # Log to central audit trail
            await AuditService.log_action(
                db=db,
                temple_id=temple_id,
                user_id=current_user_id,
                role=role,
                module_name="digital_experience",
                action="PUBLISH_WEBSITE",
                action_type="CREATE",
                entity_id=str(live.id if live.id else temple_id),
                new_value={"version": live.version, "status": "PUBLISHED"},
                details=f"Published website for temple {temple_id} (slug: {slug})"
            )
            
        # Commit the transaction
        await db.commit()
        if live.id:
            await db.refresh(live)
        return live

    @staticmethod
    async def unpublish_settings(
        db: AsyncSession,
        temple_id: UUID,
        current_user_id: UUID,
        role: str
    ) -> bool:
        async with db.begin_nested():
            # 1. Fetch live snapshot
            live_stmt = select(TempleWebsiteSettingsLive).filter(TempleWebsiteSettingsLive.temple_id == temple_id)
            live_res = await db.execute(live_stmt)
            live = live_res.scalars().first()
            if not live:
                raise HTTPException(status_code=404, detail="Website is not currently published")
                
            # 2. Delete live snapshot record
            await db.delete(live)
            
            # 3. Log to central audit trail
            await AuditService.log_action(
                db=db,
                temple_id=temple_id,
                user_id=current_user_id,
                role=role,
                module_name="digital_experience",
                action="UNPUBLISH_WEBSITE",
                action_type="DELETE",
                entity_id=str(live.id),
                details=f"Unpublished website for temple {temple_id}"
            )
            
        await db.commit()
        return True

    @staticmethod
    async def get_publication_status(
        db: AsyncSession,
        temple_id: UUID
    ) -> dict:
        live_stmt = select(TempleWebsiteSettingsLive).filter(TempleWebsiteSettingsLive.temple_id == temple_id)
        live_res = await db.execute(live_stmt)
        live = live_res.scalars().first()
        
        if live:
            return {
                "isPublished": True,
                "publishedAt": live.published_at.isoformat() if live.published_at else None,
                "publishedBy": str(live.published_by) if live.published_by else None
            }
        else:
            return {
                "isPublished": False,
                "publishedAt": None,
                "publishedBy": None
            }
