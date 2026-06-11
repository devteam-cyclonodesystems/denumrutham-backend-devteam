"""
Auth Service Module

Purpose:
Handles user login verification, password hashing, and secure JWT operations.

Responsibilities:
- Decodes and validates JWT tokens
- Password encryption and verification
- Platform access controls

Operational Notes:
- Stateless execution assumptions
- Integrates with centralized security keys
- Enforces session security version validation
"""

from fastapi import HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.security import verify_password, get_password_hash, create_access_token
from app.models.domain import User, DevoteeProfile, PasswordResetToken
from app.schemas.devotee_portal import DevoteeRegister

class AuthService:

    @staticmethod
    async def request_password_reset(db: AsyncSession, email: str):
        """Request a password reset link."""
        import uuid as uuid_mod
        from datetime import datetime, timedelta, timezone

        # 1. Check if user exists (Fix PART 2.2)
        result = await db.execute(select(User).filter(User.email == email, User.is_active == True))
        user = result.scalars().first()
        
        # Security: Always return success message even if user not found (Fix PART 2.2)
        if not user:
            return {"message": "If the account exists, a reset link has been sent."}

        # 2. Generate secure token (Fix PART 2.2)
        token_str = str(uuid_mod.uuid4())
        
        # 3. Store token with expiry (15 mins) (Fix PART 2.3)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
        
        reset_token = PasswordResetToken(
            user_id=user.id,
            token=token_str,
            expires_at=expires_at
        )
        db.add(reset_token)
        await db.commit()

        # 4. Mock "Send" email (Fix PART 2.2)
        # Note: In production replace with real mailer
        reset_link = f"http://localhost:5173/reset-password?token={token_str}"
        # Print to stdout so we can see it in docker logs
        print(f"\n[SECURITY] Password reset link generated for {email}: {reset_link}\n")

        return {"message": "If the account exists, a reset link has been sent."}

    @staticmethod
    async def reset_password(db: AsyncSession, token: str, new_password: str):
        """Set new password using a valid token (Fix PART 2.3)."""
        from datetime import datetime, timezone

        # 1. Validate token (existence, expiry, usage)
        result = await db.execute(
            select(PasswordResetToken).filter(
                PasswordResetToken.token == token,
                PasswordResetToken.is_used == False,
                PasswordResetToken.expires_at > datetime.now(timezone.utc)
            )
        )
        reset_token = result.scalars().first()

        if not reset_token:
            raise HTTPException(status_code=400, detail="Invalid, expired, or already used token")

        # 2. Update user password
        user_result = await db.execute(select(User).filter(User.id == reset_token.user_id))
        user = user_result.scalars().first()
        
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        user.password_hash = get_password_hash(new_password)
        
        # 3. Mark token as used
        reset_token.is_used = True
        
        await db.commit()
        return {"message": "Password updated successfully. Please login."}

    @staticmethod
    async def login(db: AsyncSession, form_data: OAuth2PasswordRequestForm):
        result = await db.execute(select(User).filter(User.user_id == form_data.username, User.is_active == True))
        user = result.scalars().first()
        
        if user:
            from app.core.security import async_verify_password
            matches = await async_verify_password(form_data.password, user.password_hash)
            if not matches:
                raise HTTPException(status_code=400, detail="Incorrect username or password")
        else:
            raise HTTPException(status_code=400, detail="Incorrect username or password")

        security_version = None
        temple_management_mode = None
        subscription_plan = None
        if user.temple_id:
            from app.models.domain import Temple
            t_res = await db.execute(select(Temple).filter(Temple.id == user.temple_id))
            temple = t_res.scalars().first()
            if temple:
                security_version = temple.security_version
                temple_management_mode = temple.management_mode
                subscription_plan = temple.subscription_plan

        access_token = create_access_token(
            subject=user.id,
            temple_id=str(user.temple_id) if user.temple_id else None,
            role=user.role,
            username=user.user_id,
            security_version=security_version,
            temple_management_mode=temple_management_mode,
            subscription_plan=subscription_plan
        )
        return {"access_token": access_token, "token_type": "bearer"}

    @staticmethod
    async def devotee_register(db: AsyncSession, data: DevoteeRegister):
        """Register a new devotee user with phone number and password."""
        result = await db.execute(select(User).filter(User.user_id == data.phone_number, User.is_active == True))
        existing = result.scalars().first()
        if existing:
            raise HTTPException(status_code=400, detail="Phone number already registered")

        user = User(
            user_id=data.phone_number,
            password_hash=get_password_hash(data.password),
            role="DEVOTEE",
            temple_id=None,
        )
        db.add(user)
        await db.flush()

        profile = DevoteeProfile(
            user_id=user.id,
            name=data.name,
        )
        db.add(profile)
        await db.commit()
        await db.refresh(user)

        access_token = create_access_token(
            subject=user.id,
            temple_id=None,
            role="DEVOTEE",
            username=user.user_id
        )
        return {"access_token": access_token, "token_type": "bearer"}
