
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from uuid import UUID
from fastapi import HTTPException
from app.models.domain import TempleProfile, TempleProfileDraft
from datetime import datetime, timezone

class TempleProfileService:
    @staticmethod
    async def get_live_profile(db: AsyncSession, temple_id: UUID) -> TempleProfile:
        result = await db.execute(
            select(TempleProfile).filter(TempleProfile.temple_id == temple_id)
        )
        return result.scalars().first()

    @staticmethod
    async def get_draft_profile(db: AsyncSession, temple_id: UUID) -> TempleProfileDraft:
        result = await db.execute(
            select(TempleProfileDraft).filter(
                TempleProfileDraft.temple_id == temple_id,
                TempleProfileDraft.status == "PENDING"
            ).order_by(TempleProfileDraft.created_at.desc())
        )
        return result.scalars().first()

    @staticmethod
    async def save_draft(db: AsyncSession, temple_id: UUID, user_id: UUID, data: dict) -> TempleProfileDraft:
        async with db.begin():
            # Check if there is an existing pending draft
            result = await db.execute(
                select(TempleProfileDraft).filter(
                    TempleProfileDraft.temple_id == temple_id,
                    TempleProfileDraft.status == "PENDING"
                )
            )
            draft = result.scalars().first()
            
            if not draft:
                draft = TempleProfileDraft(temple_id=temple_id, requested_by=user_id)
                db.add(draft)
            
            # Update fields
            for key, value in data.items():
                if hasattr(draft, key) and key not in ["id", "temple_id", "created_at"]:
                    setattr(draft, key, value)
            
            draft.updated_at = datetime.now(timezone.utc)
            draft.status = "PENDING"
            
            from app.services.audit_service import AuditService
            await AuditService.log_action(
                db=db,
                temple_id=temple_id,
                user_id=user_id,
                role="TEMPLE_MANAGER",
                module_name="temple_profile",
                action="save_draft",
                action_type="create",
                new_value=data
            )
        
        await db.refresh(draft)
        return draft

    @staticmethod
    async def approve_draft(db: AsyncSession, draft_id: UUID, approver_id: UUID) -> TempleProfile:
        async with db.begin():
            result = await db.execute(
                select(TempleProfileDraft).filter(TempleProfileDraft.id == draft_id)
            )
            draft = result.scalars().first()
            if not draft or draft.status != "PENDING":
                raise HTTPException(status_code=404, detail="Pending draft not found")

            # Update live profile
            profile_result = await db.execute(
                select(TempleProfile).filter(TempleProfile.temple_id == draft.temple_id)
            )
            profile = profile_result.scalars().first()
            if not profile:
                profile = TempleProfile(temple_id=draft.temple_id)
                db.add(profile)
            
            # Copy fields from draft to profile
            exclude = ["id", "temple_id", "requested_by", "status", "created_at", "updated_at"]
            for column in TempleProfileDraft.__table__.columns:
                if column.name not in exclude and hasattr(profile, column.name):
                    val = getattr(draft, column.name)
                    if val is not None:
                        setattr(profile, column.name, val)
            
            draft.status = "APPROVED"
            
            from app.services.audit_service import AuditService
            await AuditService.log_action(
                db=db,
                temple_id=draft.temple_id,
                user_id=approver_id,
                role="SUPERADMIN",
                module_name="temple_profile",
                action="approve_draft",
                action_type="update",
                entity_id=str(draft.id)
            )
            
        await db.refresh(profile)
        return profile

    @staticmethod
    async def reject_draft(db: AsyncSession, draft_id: UUID, approver_id: UUID) -> TempleProfileDraft:
        async with db.begin():
            result = await db.execute(
                select(TempleProfileDraft).filter(TempleProfileDraft.id == draft_id)
            )
            draft = result.scalars().first()
            if not draft:
                raise HTTPException(status_code=404, detail="Draft not found")
            
            draft.status = "REJECTED"
            
            from app.services.audit_service import AuditService
            await AuditService.log_action(
                db=db,
                temple_id=draft.temple_id,
                user_id=approver_id,
                role="SUPERADMIN",
                module_name="temple_profile",
                action="reject_draft",
                action_type="update",
                entity_id=str(draft.id)
            )
            
        await db.refresh(draft)
        return draft
