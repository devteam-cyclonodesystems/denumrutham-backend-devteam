"""
Authentication & Registration Routes — Unified registration, OTP, and login with redirect.
"""
from uuid import UUID
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.limiter import limiter

from app.api.deps import get_db, get_current_user
from app.schemas.domain import Token, TokenData
from app.schemas.auth import (
    UnifiedRegister, TempleManagerRegister,
    OTPRequest, OTPVerify, LoginResponse,
    RegistrationResponse,
    ForgotPasswordRequest, ResetPasswordRequest, ForceResetPasswordRequest,
    UserResponse,
)
from app.schemas.devotee_portal import DevoteeRegister
from app.services.auth_service import AuthService
from app.services.registration_service import RegistrationService
from app.core.response import api_response

router = APIRouter()


# ── Legacy Login (backward compatible) ────────────────────────────────
@router.post("/login")
@limiter.limit("10/minute")
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Legacy login endpoint — returns token without redirect."""
    token = await AuthService.login(db, form_data)
    return api_response(data=token.model_dump() if hasattr(token, 'model_dump') else token, message="Login successful")


# ── Enhanced Login with Redirect ──────────────────────────────────────
@router.post("/login/redirect")
@limiter.limit("10/minute")
async def login_with_redirect(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """
    Login with role-based redirect URL.
    
    Returns:
    - DEVOTEE → /temples (pre-login temple listing)
    - TEMPLE_MANAGER → /dashboard 
    - STAFF → /dashboard (restricted)
    - SUPER_ADMIN → /admin/dashboard
    """
    result = await RegistrationService.login_with_redirect(
        db, form_data.username, form_data.password
    )
    return api_response(data=result.model_dump() if hasattr(result, 'model_dump') else result, message="Login successful")


# ── Unified Registration ─────────────────────────────────────────────
@router.post("/register")
@limiter.limit("5/minute")
async def register(
    request: Request,
    data: UnifiedRegister,
    db: AsyncSession = Depends(get_db),
):
    """
    Unified registration with 3 entry roles: DEVOTEE, TEMPLE_MANAGER, STAFF.
    
    - Field: email_or_phone — auto-detects and stores separately
    - DEVOTEE: immediate ACTIVE status
    - STAFF: requires temple_domain, status=PENDING (needs TEMPLE_MANAGER approval)
    - TEMPLE_MANAGER: use /register/temple-manager instead
    """
    if data.role == "TEMPLE_MANAGER":
        return api_response(
            data={"user_id": "", "role": "TEMPLE_MANAGER", "status": ""},
            message="Use /register/temple-manager endpoint for temple registration",
            success=False,
            status_code=400
        )
    
    from app.core.config import settings
    if data.role == "STAFF" and not settings.ENABLE_STAFF_SELF_REGISTRATION:
        return api_response(
            data={"user_id": "", "role": "STAFF", "status": ""},
            message="Staff self-registration is disabled. Please contact your temple manager.",
            success=False,
            status_code=403
        )
    
    result = await RegistrationService.register(
        db=db,
        email_or_phone=data.email_or_phone,
        password=data.password,
        name=data.name,
        role=data.role,
        temple_domain=data.temple_domain,
        temple_id=data.temple_id,
        temple_code=data.temple_code,
        confirm_password=data.confirm_password,
        invite_token=data.invite_token,
        onboarding_method=data.onboarding_method,
    )
    return api_response(data=result.model_dump() if hasattr(result, 'model_dump') else result, message="Registration successful", status_code=201)


# ── Temple Manager Registration (DEPRECATED → use /onboarding/register-temple) ─
@router.post("/register/temple-manager")
@limiter.limit("3/minute")
async def register_temple_manager(
    request: Request,
    data: TempleManagerRegister,
    db: AsyncSession = Depends(get_db),
):
    """
    DEPRECATED: Use POST /api/v1/onboarding/register-temple instead.

    This endpoint now delegates to the new staging-table onboarding flow.
    Temple + Manager are created in staging tables (temple_requests + user_requests)
    and require Super Admin approval before activation.
    """
    from app.services.onboarding_service import OnboardingService
    import re
    import unicodedata

    # Generate domain from temple name (backward compat)
    def _slugify(text: str) -> str:
        text = unicodedata.normalize("NFKD", text)
        text = text.encode("ascii", "ignore").decode("ascii")
        text = re.sub(r"[^\w\s-]", "", text.lower())
        return re.sub(r"[-\s]+", "-", text).strip("-")

    email, phone = None, None
    email_or_phone = data.email_or_phone.strip()
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if re.match(email_pattern, email_or_phone):
        email = email_or_phone
    else:
        phone = email_or_phone

    domain = _slugify(data.temple_name.strip())

    result = await OnboardingService.register_temple(
        db=db,
        temple_name=data.temple_name,
        domain=domain,
        manager_name=data.name,
        manager_email=email,
        manager_phone=phone,
        password=data.password,
        contact=data.temple_contact_number or "",
        temple_email=data.temple_email or "",
        state=data.temple_state or "",
        district=data.temple_district or "",
        address=data.temple_location or "",
        pincode=data.temple_pincode or "",
    )
    return api_response(
        data=result,
        message="Temple registration submitted. Awaiting Super Admin approval.",
        status_code=201,
    )


# ── Legacy Devotee Registration (backward compatible) ─────────────────
@router.post("/devotee/register")
@limiter.limit("5/minute")
async def devotee_register(
    request: Request,
    data: DevoteeRegister,
    db: AsyncSession = Depends(get_db),
):
    """Register a new devotee user with phone number and password (legacy)."""
    token = await AuthService.devotee_register(db, data)
    return api_response(data=token.model_dump() if hasattr(token, 'model_dump') else token, message="Devotee registration successful", status_code=201)


# ── OTP Endpoints ─────────────────────────────────────────────────────
@router.post("/otp/request")
@limiter.limit("5/minute")
async def request_otp(
    request: Request,
    data: OTPRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Request OTP verification code.
    Mock implementation: OTP is returned in response for development.
    """
    result = await RegistrationService.request_otp(db, data.email_or_phone)
    return api_response(data=result, message="OTP requested successfully")


@router.post("/otp/verify")
@limiter.limit("10/minute")
async def verify_otp(
    request: Request,
    data: OTPVerify,
    db: AsyncSession = Depends(get_db),
):
    """Verify OTP code and return access token if valid."""
    result = await RegistrationService.verify_otp(db, data.email_or_phone, data.otp_code)
    return api_response(data=result.model_dump() if hasattr(result, 'model_dump') else result, message="OTP verified successfully")


# ── Password Reset Endpoints ──────────────────────────────────────────

@router.post("/forgot-password")
@limiter.limit("5/minute")
async def forgot_password(
    request: Request,
    data: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Request a password reset link (Fix PART 2.2)."""
    result = await AuthService.request_password_reset(db, data.email)
    return api_response(data=result, message="Instruction sent if account exists")


@router.post("/reset-password")
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Reset password using token (Fix PART 2.3)."""
    result = await AuthService.reset_password(db, data.token, data.new_password)
    return api_response(data=result, message="Password reset successful")


@router.post("/reset-password-force")
async def reset_password_force(
    data: ForceResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """Force password reset for newly created accounts."""
    from app.services.staff_service import StaffService
    
    # We only need the password from data, token is not needed here as user is authenticated
    result = await StaffService.complete_force_password_reset(
        db=db, 
        user_id=UUID(current_user.sub), 
        new_password=data.new_password
    )
    return api_response(data=result, message="Password updated successfully")


@router.get("/me")
async def get_me(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
):
    """Retrieve current user's profile with live management mode & subscription plan."""
    from sqlalchemy.future import select
    from app.models import Temple
    from app.modules.auth.models.auth_models import User
    
    stmt = select(User).filter(User.id == UUID(current_user.sub))
    res = await db.execute(stmt)
    user = res.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    response_data = {
        "id": str(user.id),
        "name": user.name,
        "email": user.email,
        "phone": user.phone,
        "role": user.role,
        "status": user.status,
        "temple_id": str(user.temple_id) if user.temple_id else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "temple_management_mode": None,
        "subscription_plan": None,
    }
    
    if user.temple_id:
        temple_stmt = select(Temple).filter(Temple.id == user.temple_id)
        temple_res = await db.execute(temple_stmt)
        temple = temple_res.scalars().first()
        if temple:
            response_data["temple_management_mode"] = temple.management_mode
            response_data["subscription_plan"] = temple.subscription_plan
            
    return api_response(data=response_data, message="Profile retrieved successfully")

