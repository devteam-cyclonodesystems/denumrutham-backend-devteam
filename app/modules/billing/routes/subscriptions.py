import logging
import hmac
import hashlib
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user, get_current_superadmin, get_current_temple_id
from app.core.config import settings
from app.core.response import api_response
from app.schemas.domain import TokenData
from app.modules.billing.services.subscription_service import SubscriptionService
from app.modules.billing.schemas.subscriptions import SubscriptionResponse, RevenueReportResponse

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/razorpay/webhook", status_code=status.HTTP_200_OK)
async def razorpay_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Public webhook receiver for Razorpay subscription events.
    Verifies signature in production and updates state logs.
    """
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")

    if settings.ENVIRONMENT.lower() == "production":
        if not signature:
            logger.error("Signature missing in production environment")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Webhook signature missing")
        expected = hmac.new(
            settings.RAZORPAY_WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            logger.error("Signature verification failed in production")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Signature verification failed")
    else:
        # In development, check signature only if secret is defined
        if settings.RAZORPAY_WEBHOOK_SECRET:
            if not signature:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Webhook signature missing")
            expected = hmac.new(
                settings.RAZORPAY_WEBHOOK_SECRET.encode(),
                body,
                hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(expected, signature):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Signature verification failed")
        else:
            logger.warning("Bypassing webhook signature verification (RAZORPAY_WEBHOOK_SECRET not configured in development)")

    # Parse payload
    try:
        payload = await request.json()
    except Exception as e:
        logger.error("Failed to parse JSON body: %s", str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")

    event_name = payload.get("event")
    if not event_name:
        logger.error("Webhook payload missing 'event' field")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing event field")

    try:
        await SubscriptionService.handle_webhook_event(db, event_name, payload)
    except ValueError as e:
        logger.error("Webhook processing error: %s", str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("Unexpected error during webhook handling: %s", str(e))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal processing error")

    return api_response(
        data={"status": "SUCCESS"},
        message="Webhook processed successfully"
    )

@router.get("/status", response_model=SubscriptionResponse)
async def get_my_subscription_status(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
    temple_id: str = Depends(get_current_temple_id)
):
    """
    Check subscription plan, state, grace periods and locks for the authenticated temple manager.
    """
    try:
        temple_uuid = UUID(temple_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid temple UUID context")

    status_info = await SubscriptionService.get_subscription_status(db, temple_uuid)
    return SubscriptionResponse(**status_info)

@router.get("/report", response_model=RevenueReportResponse)
async def get_subscriptions_revenue_report(
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_superadmin)
):
    """
    Superadmin billing and revenue forecasting analytics dashboard.
    """
    report = await SubscriptionService.get_revenue_report(db)
    return RevenueReportResponse(**report)
