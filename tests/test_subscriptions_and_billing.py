import pytest
import pytest_asyncio
import uuid
import os
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient
from sqlalchemy.future import select

from tests.conftest import TEMPLE_ID
from app.core.database.database import AsyncSessionLocal
from app.modules.billing.models.subscription_model import Subscription, SubscriptionEvent, SubscriptionStatus
from app.modules.temple_management.models.temple_models import Temple
from app.core.config.config import Settings

def utcnow():
    return datetime.now(timezone.utc)

@pytest.mark.anyio
async def test_webhook_subscription_activation(client: AsyncClient):
    """
    1. Verify webhook subscription.activated creates a Subscription,
       sets plan, updates Temple model plan, and inserts a SubscriptionEvent.
    """
    payload = {
        "event": "subscription.activated",
        "payload": {
            "subscription": {
                "entity": {
                    "id": "sub_test_12345",
                    "plan_id": "plan_governed",
                    "status": "active",
                    "current_start": int(utcnow().timestamp()),
                    "current_end": int((utcnow() + timedelta(days=30)).timestamp()),
                    "notes": {
                        "temple_id": str(TEMPLE_ID),
                        "subscription_plan": "GOVERNED_STANDARD"
                    }
                }
            }
        }
    }

    response = await client.post("/api/v1/subscriptions/razorpay/webhook", json=payload)
    assert response.status_code == 200, response.text
    
    # Query Database
    async with AsyncSessionLocal() as session:
        sub_stmt = select(Subscription).filter(Subscription.temple_id == TEMPLE_ID)
        res = await session.execute(sub_stmt)
        sub = res.scalars().first()
        assert sub is not None
        assert sub.status == SubscriptionStatus.ACTIVE.value
        assert sub.subscription_plan == "GOVERNED_STANDARD"
        assert sub.razorpay_subscription_id == "sub_test_12345"

        # Verify Temple sync
        temple_stmt = select(Temple).filter(Temple.id == TEMPLE_ID)
        temple_res = await session.execute(temple_stmt)
        temple = temple_res.scalars().first()
        assert temple.subscription_plan == "GOVERNED_STANDARD"

        # Verify audit log event
        evt_stmt = select(SubscriptionEvent).filter(SubscriptionEvent.subscription_id == sub.id)
        evt_res = await session.execute(evt_stmt)
        events = evt_res.scalars().all()
        assert len(events) == 1
        assert events[0].event_name == "subscription.activated"
        assert events[0].new_status == "ACTIVE"


@pytest.mark.anyio
async def test_webhook_payment_failure_grace_period(client: AsyncClient, auth_headers: dict):
    """
    2. Verify webhook subscription.pending transitions status to PAST_DUE,
       initiates a 7-day grace period, and allows logins with past_due_warning.
    """
    payload = {
        "event": "subscription.pending",
        "payload": {
            "subscription": {
                "entity": {
                    "id": "sub_test_12345",
                    "plan_id": "plan_governed",
                    "status": "pending",
                    "notes": {
                        "temple_id": str(TEMPLE_ID)
                    }
                }
            }
        }
    }

    response = await client.post("/api/v1/subscriptions/razorpay/webhook", json=payload)
    assert response.status_code == 200

    async with AsyncSessionLocal() as session:
        sub_stmt = select(Subscription).filter(Subscription.temple_id == TEMPLE_ID)
        res = await session.execute(sub_stmt)
        sub = res.scalars().first()
        assert sub.status == SubscriptionStatus.PAST_DUE.value
        assert sub.grace_period_ends_at is not None
        # Make sure ends_at is tz-aware for the test
        grace_ends = sub.grace_period_ends_at.replace(tzinfo=timezone.utc) if sub.grace_period_ends_at.tzinfo is None else sub.grace_period_ends_at
        # Should be roughly 7 days in the future
        time_diff = grace_ends - utcnow()
        assert 6 <= time_diff.days <= 7

    # Verify status API returns past due warnings but access is not locked
    status_response = await client.get("/api/v1/subscriptions/status", headers=auth_headers)
    assert status_response.status_code == 200
    data = status_response.json()
    assert data["status"] == "PAST_DUE"
    assert data["past_due_warning"] is True
    assert data["write_locked"] is False


@pytest.mark.anyio
async def test_grace_period_lockout_enforcement(client: AsyncClient, auth_headers: dict):
    """
    3. Verify that once the grace period expires, read operations remain active,
       but write operations return HTTP 402 Payment Required.
    """
    # Force expire the grace period in DB
    async with AsyncSessionLocal() as session:
        sub_stmt = select(Subscription).filter(Subscription.temple_id == TEMPLE_ID)
        res = await session.execute(sub_stmt)
        sub = res.scalars().first()
        sub.grace_period_ends_at = utcnow() - timedelta(hours=2)
        await session.commit()

    # Get status - should be write_locked
    status_response = await client.get("/api/v1/subscriptions/status", headers=auth_headers)
    assert status_response.status_code == 200
    assert status_response.json()["write_locked"] is True
    assert status_response.json()["past_due_warning"] is False

    # Perform Read - should succeed (GET website settings)
    read_response = await client.get("/api/v1/manager/website-settings", headers=auth_headers)
    assert read_response.status_code == 200

    # Perform Write - should be blocked with 402 Payment Required
    write_payload = {
        "title": "My Updated Website Title",
        "description": "Short description",
        "primary_color": "#ff0000"
    }
    write_response = await client.put("/api/v1/manager/website-settings", json=write_payload, headers=auth_headers)
    assert write_response.status_code == 402
    assert "locked due to unpaid or expired subscription" in str(write_response.json())


@pytest.mark.anyio
async def test_webhook_subscription_cancellation(client: AsyncClient, auth_headers: dict):
    """
    4. Verify that cancellation sets status to CANCELLED, preserves subscription_plan tier name,
       and blocks modifying operations.
    """
    payload = {
        "event": "subscription.cancelled",
        "payload": {
            "subscription": {
                "entity": {
                    "id": "sub_test_12345",
                    "plan_id": "plan_governed",
                    "status": "cancelled",
                    "notes": {
                        "temple_id": str(TEMPLE_ID)
                    }
                }
            }
        }
    }

    response = await client.post("/api/v1/subscriptions/razorpay/webhook", json=payload)
    assert response.status_code == 200

    async with AsyncSessionLocal() as session:
        sub_stmt = select(Subscription).filter(Subscription.temple_id == TEMPLE_ID)
        res = await session.execute(sub_stmt)
        sub = res.scalars().first()
        assert sub.status == SubscriptionStatus.CANCELLED.value
        # Revision 1: plan remains unchanged, not downgraded to FREE
        assert sub.subscription_plan == "GOVERNED_STANDARD"

    # Verify write lockout is active immediately on cancellation
    write_payload = {"title": "Cancelled Update"}
    write_response = await client.put("/api/v1/manager/website-settings", json=write_payload, headers=auth_headers)
    assert write_response.status_code == 402


@pytest.mark.anyio
async def test_revenue_reporting_dashboard(client: AsyncClient, superadmin_auth_headers: dict):
    """
    5. Verify revenue report aggregates counts and estimates MRR + expected renewal revenue.
    """
    response = await client.get("/api/v1/subscriptions/report", headers=superadmin_auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "status_counts" in data
    assert data["status_counts"]["CANCELLED"] == 1
    # MRR should be 0 because the only subscription is CANCELLED
    assert data["mrr"] == 0.0
    assert data["expected_renewal_revenue"] == 0.0


def test_production_configuration_check():
    """
    6. Verify that settings initialization throws a ValueError if environment is production
       and webhook secret is missing.
    """
    old_env = os.environ.get("ENVIRONMENT")
    old_secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET")
    old_db = os.environ.get("DATABASE_URL")
    old_key = os.environ.get("SECRET_KEY")
    old_jwt = os.environ.get("JWT_SECRET")
    
    os.environ["ENVIRONMENT"] = "production"
    os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5432/db"
    os.environ["SECRET_KEY"] = "changed_secret_key_123"
    os.environ["JWT_SECRET"] = "changed_jwt_secret_key_123"
    if "RAZORPAY_WEBHOOK_SECRET" in os.environ:
        del os.environ["RAZORPAY_WEBHOOK_SECRET"]

    with pytest.raises(ValueError) as excinfo:
        Settings()
    
    assert "RAZORPAY_WEBHOOK_SECRET" in str(excinfo.value)

    # Clean up environment variables
    if old_env:
        os.environ["ENVIRONMENT"] = old_env
    else:
        del os.environ["ENVIRONMENT"]
    
    if old_secret:
        os.environ["RAZORPAY_WEBHOOK_SECRET"] = old_secret
    else:
        if "RAZORPAY_WEBHOOK_SECRET" in os.environ:
            del os.environ["RAZORPAY_WEBHOOK_SECRET"]

    if old_db:
        os.environ["DATABASE_URL"] = old_db
    else:
        if "DATABASE_URL" in os.environ:
            del os.environ["DATABASE_URL"]

    if old_key:
        os.environ["SECRET_KEY"] = old_key
    else:
        if "SECRET_KEY" in os.environ:
            del os.environ["SECRET_KEY"]

    if old_jwt:
        os.environ["JWT_SECRET"] = old_jwt
    else:
        if "JWT_SECRET" in os.environ:
            del os.environ["JWT_SECRET"]

