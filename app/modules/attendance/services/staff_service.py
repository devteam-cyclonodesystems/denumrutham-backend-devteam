import logging
from uuid import UUID
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, or_
from fastapi import HTTPException

from app.models.domain import User, UserTemple, AuditLog, Temple
from app.core.security import get_password_hash
from app.schemas.staff import StaffCreate, StaffUpdate

logger = logging.getLogger("tms.services.staff_service")

class StaffService:
    @staticmethod
    async def create_staff(db: AsyncSession, staff_in: StaffCreate, temple_id: UUID, creator_id: UUID) -> User:
        # Check uniqueness
        from app.services.registration_service import _detect_email_or_phone
        email, phone = _detect_email_or_phone(staff_in.email_or_phone)
        login_id = email or phone

        existing = await db.execute(
            select(User).filter(or_(User.user_id == login_id, User.email == email, User.phone == phone))
        )
        if existing.scalars().first():
            raise HTTPException(status_code=400, detail="User already exists with this email/phone")

        # Create user
        user = User(
            user_id=login_id,
            name=staff_in.name,
            email=email,
            phone=phone,
            password_hash=get_password_hash(staff_in.temporary_password),
            role="STAFF",
            status="ACTIVE",
            temple_id=temple_id,
            onboarding_method="ADMIN_CREATED",
            approval_status="APPROVED",
            force_password_change=True
        )
        db.add(user)
        await db.flush()

        # Add to UserTemple mapping
        mapping = UserTemple(
            user_id=user.id,
            temple_id=temple_id,
            role="STAFF",
        )
        db.add(mapping)

        # Audit log
        audit = AuditLog(
            temple_id=temple_id,
            user_id=creator_id,
            action="STAFF_CREATED",
            action_type="CREATE",
            entity_id=str(user.id),
            new_value={"name": user.name, "role": user.role, "onboarding_method": "ADMIN_CREATED"},
            details=f"Staff {user.name} created by manager."
        )
        db.add(audit)

        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def get_staff_list(db: AsyncSession, temple_id: UUID) -> list[User]:
        result = await db.execute(
            select(User).filter(User.temple_id == temple_id, User.role == "STAFF")
        )
        return result.scalars().all()

    @staticmethod
    async def update_staff_status(db: AsyncSession, staff_id: UUID, status: str, temple_id: UUID, actor_id: UUID) -> User:
        result = await db.execute(
            select(User).filter(User.id == staff_id, User.temple_id == temple_id)
        )
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="Staff not found")

        old_status = user.status
        user.status = status
        
        # Audit log
        audit = AuditLog(
            temple_id=temple_id,
            user_id=actor_id,
            action="STAFF_STATUS_UPDATED",
            action_type="UPDATE",
            entity_id=str(user.id),
            old_value={"status": old_status},
            new_value={"status": status},
            details=f"Staff {user.name} status updated from {old_status} to {status}."
        )
        db.add(audit)
        
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def reset_password(db: AsyncSession, staff_id: UUID, new_password: str, temple_id: UUID, actor_id: UUID) -> User:
        result = await db.execute(
            select(User).filter(User.id == staff_id, User.temple_id == temple_id)
        )
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="Staff not found")

        user.password_hash = get_password_hash(new_password)
        user.force_password_change = True
        
        # Audit log
        audit = AuditLog(
            temple_id=temple_id,
            user_id=actor_id,
            action="STAFF_PASSWORD_RESET",
            action_type="UPDATE",
            entity_id=str(user.id),
            details=f"Staff {user.name} password reset by manager."
        )
        db.add(audit)
        
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def get_staff_counts(db: AsyncSession, temple_id: UUID) -> dict:
        stmt = select(User.status, func.count(User.id)).filter(
            User.temple_id == temple_id, User.role == "STAFF"
        ).group_by(User.status)
        result = await db.execute(stmt)
        counts = {row[0]: row[1] for row in result.all()}
        
        # Also need "on leave" from Employee model if linked
        # For now, let's just return what we have from User
        return {
            "total": sum(counts.values()),
            "active": counts.get("ACTIVE", 0),
            "suspended": counts.get("SUSPENDED", 0),
            "on_leave": 0 # placeholder
        }

    @staticmethod
    async def complete_force_password_reset(db: AsyncSession, user_id: UUID, new_password: str) -> dict:
        result = await db.execute(select(User).filter(User.id == user_id))
        user = result.scalars().first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.password_hash = get_password_hash(new_password)
        user.force_password_change = False
        
        # Audit log
        audit = AuditLog(
            temple_id=user.temple_id,
            user_id=user.id,
            action="PASSWORD_CHANGED_FIRST_LOGIN",
            action_type="UPDATE",
            entity_id=str(user.id),
            details="User completed mandatory password reset on first login."
        )
        db.add(audit)
        
        await db.commit()
        return {"status": "success", "message": "Password updated"}
