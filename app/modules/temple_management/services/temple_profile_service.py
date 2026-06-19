
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from uuid import UUID
from fastapi import HTTPException
from app.models.domain import TempleProfile, TempleProfileDraft
from datetime import datetime, timezone
from typing import Optional

class TempleProfileService:
    PROFILE_COMPLETENESS_RULES = {
        "description": 15,
        "history": 15,
        "gallery": 15,
        "activities": 10,
        "festivals": 10,
        "location": 10,
        "contact": 10,
        "key_personnel": 15
    }

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
        # Check if there is an existing pending draft
        result = await db.execute(
            select(TempleProfileDraft).filter(
                TempleProfileDraft.temple_id == temple_id,
                TempleProfileDraft.status == "PENDING"
            )
        )
        draft = result.scalars().first()
        
        if draft:
            # If a draft already exists and is PENDING, new edits are locked out
            raise HTTPException(
                status_code=409,
                detail="A profile draft is already pending approval. Edits are locked."
            )
        
        try:
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
            
            await db.commit()
            await db.refresh(draft)
            return draft
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def approve_draft(db: AsyncSession, draft_id: UUID, approver_id: UUID, edits: Optional[dict] = None) -> TempleProfile:
        result = await db.execute(
            select(TempleProfileDraft).filter(TempleProfileDraft.id == draft_id)
        )
        draft = result.scalars().first()
        if not draft or draft.status != "PENDING":
            raise HTTPException(status_code=404, detail="Pending draft not found")

        try:
            def make_serializable(d: dict) -> dict:
                res = {}
                for k, v in d.items():
                    if isinstance(v, UUID):
                        res[k] = str(v)
                    elif isinstance(v, datetime):
                        res[k] = v.isoformat()
                    else:
                        res[k] = v
                return res

            # Capture original draft state for audit trail
            original_draft = make_serializable({
                c.name: getattr(draft, c.name) 
                for c in TempleProfileDraft.__table__.columns 
                if c.name not in ["id", "temple_id", "created_at", "updated_at"]
            })

            # Apply SuperAdmin edits during approval if provided
            if edits:
                for k, v in edits.items():
                    if hasattr(draft, k) and k not in ["id", "temple_id", "created_at"]:
                        setattr(draft, k, v)
                draft.updated_at = datetime.now(timezone.utc)

            reviewed_draft = make_serializable({
                c.name: getattr(draft, c.name) 
                for c in TempleProfileDraft.__table__.columns 
                if c.name not in ["id", "temple_id", "created_at", "updated_at"]
            })

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
            
            # Record publication fields
            profile.published_at = datetime.now(timezone.utc)
            profile.published_by = approver_id

            draft.status = "APPROVED"
            
            # Capture published profile state
            published_profile = make_serializable({
                c.name: getattr(profile, c.name) 
                for c in TempleProfile.__table__.columns 
                if c.name not in ["id", "temple_id", "created_at"]
            })

            # Audit governance metadata overrides
            audit_metadata = {
                "original_draft": original_draft,
                "reviewed_draft": reviewed_draft,
                "published_profile": published_profile
            }
            
            from app.services.audit_service import AuditService
            await AuditService.log_action(
                db=db,
                temple_id=draft.temple_id,
                user_id=approver_id,
                role="SUPERADMIN",
                module_name="temple_profile",
                action="approve_draft",
                action_type="update",
                entity_id=str(draft.id),
                new_value=audit_metadata,
                details="Approved draft" + (" with edits" if edits else "")
            )
            
            await db.commit()
            await db.refresh(profile)
            return profile
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def reject_draft(db: AsyncSession, draft_id: UUID, approver_id: UUID) -> TempleProfileDraft:
        result = await db.execute(
            select(TempleProfileDraft).filter(TempleProfileDraft.id == draft_id)
        )
        draft = result.scalars().first()
        if not draft:
            raise HTTPException(status_code=404, detail="Draft not found")
        
        try:
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
            
            await db.commit()
            await db.refresh(draft)
            return draft
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def direct_update_profile(db: AsyncSession, temple_id: UUID, user_id: UUID, role: str, data: dict) -> TempleProfile:
        profile_result = await db.execute(
            select(TempleProfile).filter(TempleProfile.temple_id == temple_id)
        )
        profile = profile_result.scalars().first()
        try:
            def make_serializable(d: dict) -> dict:
                res = {}
                for k, v in d.items():
                    if isinstance(v, UUID):
                        res[k] = str(v)
                    elif isinstance(v, datetime):
                        res[k] = v.isoformat()
                    else:
                        res[k] = v
                return res

            if not profile:
                profile = TempleProfile(temple_id=temple_id)
                db.add(profile)
            
            old_value = make_serializable({
                c.name: getattr(profile, c.name) 
                for c in TempleProfile.__table__.columns 
                if c.name not in ["id", "temple_id", "created_at"]
            })
            
            # Update fields
            for key, value in data.items():
                if hasattr(profile, key) and key not in ["id", "temple_id", "created_at"]:
                    setattr(profile, key, value)
            
            # Record publication audit details
            profile.published_at = datetime.now(timezone.utc)
            profile.published_by = user_id
            
            new_value = make_serializable({
                c.name: getattr(profile, c.name) 
                for c in TempleProfile.__table__.columns 
                if c.name not in ["id", "temple_id", "created_at"]
            })
            
            from app.services.audit_service import AuditService
            await AuditService.log_action(
                db=db,
                temple_id=temple_id,
                user_id=user_id,
                role=role,
                module_name="temple_profile",
                action="direct_update",
                action_type="update",
                entity_id=str(profile.id),
                old_value=old_value,
                new_value=new_value,
                details="Directly updated and published temple profile (bypassed draft workflow)"
            )
            
            await db.commit()
            await db.refresh(profile)
            return profile
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def get_profile_completeness(db: AsyncSession, temple_id: UUID) -> dict:
        profile = await TempleProfileService.get_live_profile(db, temple_id)
        if not profile:
            return {
                "score": 0, 
                "breakdown": {
                    k: {"satisfied": False, "points": 0, "max_points": v} 
                    for k, v in TempleProfileService.PROFILE_COMPLETENESS_RULES.items()
                }
            }
        
        breakdown = {}
        
        # 1. Description
        has_description = bool(profile.description and profile.description.strip())
        breakdown["description"] = {
            "satisfied": has_description,
            "points": TempleProfileService.PROFILE_COMPLETENESS_RULES["description"] if has_description else 0,
            "max_points": TempleProfileService.PROFILE_COMPLETENESS_RULES["description"]
        }
        
        # 2. History
        has_history = bool(profile.history and profile.history.strip())
        breakdown["history"] = {
            "satisfied": has_history,
            "points": TempleProfileService.PROFILE_COMPLETENESS_RULES["history"] if has_history else 0,
            "max_points": TempleProfileService.PROFILE_COMPLETENESS_RULES["history"]
        }
        
        # 3. Location
        has_location = bool((profile.location and profile.location.strip()) or (profile.latitude is not None and profile.longitude is not None))
        breakdown["location"] = {
            "satisfied": has_location,
            "points": TempleProfileService.PROFILE_COMPLETENESS_RULES["location"] if has_location else 0,
            "max_points": TempleProfileService.PROFILE_COMPLETENESS_RULES["location"]
        }
        
        # 4. Contact
        has_contact = bool((profile.contact_number and profile.contact_number.strip()) or (profile.email and profile.email.strip()))
        breakdown["contact"] = {
            "satisfied": has_contact,
            "points": TempleProfileService.PROFILE_COMPLETENESS_RULES["contact"] if has_contact else 0,
            "max_points": TempleProfileService.PROFILE_COMPLETENESS_RULES["contact"]
        }
        
        # 5. Gallery
        from app.models.domain import TempleImage
        img_stmt = select(TempleImage).filter(
            TempleImage.temple_id == temple_id, 
            TempleImage.category == "GALLERY", 
            TempleImage.is_visible == True
        ).limit(1)
        img_res = await db.execute(img_stmt)
        has_gallery = img_res.scalars().first() is not None
        breakdown["gallery"] = {
            "satisfied": has_gallery,
            "points": TempleProfileService.PROFILE_COMPLETENESS_RULES["gallery"] if has_gallery else 0,
            "max_points": TempleProfileService.PROFILE_COMPLETENESS_RULES["gallery"]
        }
        
        # 6. Activities
        from app.models.domain import TempleActivity
        act_stmt = select(TempleActivity).filter(
            TempleActivity.temple_id == temple_id, 
            TempleActivity.is_active == True
        ).limit(1)
        act_res = await db.execute(act_stmt)
        has_activities = act_res.scalars().first() is not None
        breakdown["activities"] = {
            "satisfied": has_activities,
            "points": TempleProfileService.PROFILE_COMPLETENESS_RULES["activities"] if has_activities else 0,
            "max_points": TempleProfileService.PROFILE_COMPLETENESS_RULES["activities"]
        }
        
        # 7. Festivals
        from app.models.domain import TempleFestival
        fest_stmt = select(TempleFestival).filter(
            TempleFestival.temple_id == temple_id, 
            TempleFestival.is_active == True
        ).limit(1)
        fest_res = await db.execute(fest_stmt)
        has_festivals = fest_res.scalars().first() is not None
        breakdown["festivals"] = {
            "satisfied": has_festivals,
            "points": TempleProfileService.PROFILE_COMPLETENESS_RULES["festivals"] if has_festivals else 0,
            "max_points": TempleProfileService.PROFILE_COMPLETENESS_RULES["festivals"]
        }
        
        # 8. Key Personnel
        from app.models.domain import TempleKeyPersonnel
        kp_stmt = select(TempleKeyPersonnel).filter(
            TempleKeyPersonnel.temple_id == temple_id, 
            TempleKeyPersonnel.is_active == True
        ).limit(1)
        kp_res = await db.execute(kp_stmt)
        has_kp = kp_res.scalars().first() is not None
        breakdown["key_personnel"] = {
            "satisfied": has_kp,
            "points": TempleProfileService.PROFILE_COMPLETENESS_RULES["key_personnel"] if has_kp else 0,
            "max_points": TempleProfileService.PROFILE_COMPLETENESS_RULES["key_personnel"]
        }
        
        total_score = sum(item["points"] for item in breakdown.values())
        return {
            "score": total_score,
            "breakdown": breakdown
        }

