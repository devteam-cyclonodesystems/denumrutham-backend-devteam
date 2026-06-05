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
    TempleImage,
    ImageCategory,
    ActivityStatus,
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
        
        await AuditService.log_action(
            db=db,
            temple_id=temple_id,
            user_id=current_user_id,
            role=role,
            module_name="digital_experience",
            action="UPDATE_IMAGE",
            action_type="UPDATE",
            entity_id=str(image.id),
            old_value=_serialize_for_audit(old_val),
            new_value=_serialize_for_audit(new_val),
            details=f"Updated temple image"
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
