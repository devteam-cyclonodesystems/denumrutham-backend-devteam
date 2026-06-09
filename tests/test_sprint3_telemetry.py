import pytest
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy.exc import IntegrityError
from sqlalchemy.future import select

from tests.conftest import TestSessionLocal, TEMPLE_ID
from app.models.domain import (
    CartItem,
    ServiceRecommendation,
    PlatformAdvertisement,
    TempleAdvertisement,
    AdvertisementAnalytics,
    PortalAnalyticsEvent,
    TempleService,
    StoreProduct,
)
from app.modules.analytics.services.analytics_service import AnalyticsService


@pytest.mark.asyncio
async def test_cart_item_constraints():
    """Verify that CartItem requires either service_id or product_id."""
    async with TestSessionLocal() as db:
        # Create a cart first
        from app.models.domain import Cart, User
        # Find the seeded user
        user_res = await db.execute(select(User).filter(User.user_id == "superadmin@temple"))
        user = user_res.scalars().first()
        assert user is not None

        cart = Cart(user_id=user.id, temple_id=TEMPLE_ID)
        db.add(cart)
        await db.commit()
        await db.refresh(cart)

        cart_id = cart.id

        # 1. Invalid CartItem: neither is set
        invalid_item = CartItem(
            cart_id=cart_id,
            item_name="Invalid Item",
            quantity=1,
            unit_price=10.0,
            service_id=None,
            product_id=None
        )
        db.add(invalid_item)
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

        # 2. Valid CartItem: has service_id (mock service)
        service = TempleService(
            temple_id=TEMPLE_ID,
            service_name="Mock Pooja",
            service_type="ARCHANA",
            price=100.0
        )
        db.add(service)
        await db.commit()
        await db.refresh(service)

        valid_item = CartItem(
            cart_id=cart_id,
            item_name="Valid Service Item",
            quantity=1,
            unit_price=100.0,
            service_id=service.id,
            product_id=None
        )
        db.add(valid_item)
        await db.commit()
        assert valid_item.id is not None

        # Clean up
        await db.delete(valid_item)
        await db.delete(service)
        await db.delete(cart)
        await db.commit()


@pytest.mark.asyncio
async def test_service_recommendation_constraints():
    """Verify source and target constraints on ServiceRecommendation."""
    async with TestSessionLocal() as db:
        # Create a mock service and a mock product
        service = TempleService(
            temple_id=TEMPLE_ID,
            service_name="Test Rec Service",
            service_type="ARCHANA",
            price=50.0
        )
        product = StoreProduct(
            temple_id=TEMPLE_ID,
            name="Test Rec Product",
            category="Flowers",
            unit="bunch",
            unit_price=20.0
        )
        db.add(service)
        db.add(product)
        await db.commit()
        await db.refresh(service)
        await db.refresh(product)

        service_id = service.id
        product_id = product.id

        # 1. Violate target constraint: both target recommended_service and recommended_product set
        invalid_rec_target = ServiceRecommendation(
            temple_id=TEMPLE_ID,
            source_service_id=service_id,
            recommendation_source_type="SERVICE",
            recommended_service_id=service_id,
            recommended_product_id=product_id
        )
        db.add(invalid_rec_target)
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

        # 2. Violate source constraint: both source_service_id and source_product_id set
        invalid_rec_source = ServiceRecommendation(
            temple_id=TEMPLE_ID,
            source_service_id=service_id,
            source_product_id=product_id,
            recommendation_source_type="SERVICE",
            recommended_service_id=service_id
        )
        db.add(invalid_rec_source)
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

        # Clean up mock items
        await db.delete(service)
        await db.delete(product)
        await db.commit()


@pytest.mark.asyncio
async def test_advertisement_media_type_validation():
    """Verify that IMAGE type ad expects 1 media URL and CAROUSEL expects >= 2."""
    async with TestSessionLocal() as db:
        now = datetime.now(timezone.utc)
        # 1. Invalid: IMAGE type with 2 urls
        invalid_img_ad = PlatformAdvertisement(
            placement="HEADER_LEADERBOARD",
            media_type="IMAGE",
            media_urls=["https://url1.com", "https://url2.com"],
            target_url="https://target.com",
            start_date=now,
            end_date=now + timedelta(days=1),
            is_active=True
        )
        db.add(invalid_img_ad)
        with pytest.raises(ValueError, match="IMAGE platform advertisement must contain exactly 1 media URL"):
            await db.commit()
        await db.rollback()

        # 2. Invalid: CAROUSEL type with 1 url
        invalid_carousel_ad = PlatformAdvertisement(
            placement="HEADER_LEADERBOARD",
            media_type="CAROUSEL",
            media_urls=["https://url1.com"],
            target_url="https://target.com",
            start_date=now,
            end_date=now + timedelta(days=1),
            is_active=True
        )
        db.add(invalid_carousel_ad)
        with pytest.raises(ValueError, match="CAROUSEL platform advertisement must contain at least 2 media URLs"):
            await db.commit()
        await db.rollback()


@pytest.mark.asyncio
async def test_analytics_deduplication_window():
    """Verify rolling 1-hour window deduplication for impressions only."""
    async with TestSessionLocal() as db:
        now = datetime.now(timezone.utc)
        ad = PlatformAdvertisement(
            placement="HEADER_LEADERBOARD",
            media_type="IMAGE",
            media_urls=["https://url1.com"],
            target_url="https://target.com",
            start_date=now,
            end_date=now + timedelta(days=1),
            is_active=True
        )
        db.add(ad)
        await db.commit()
        await db.refresh(ad)

        visitor = "test-visitor-1"
        session = "session-1"

        # 1. Log first impression -> should write successfully
        w1 = await AnalyticsService.log_advertisement_event(
            db=db,
            advertisement_id=ad.id,
            advertisement_type="PLATFORM",
            event_type="IMPRESSION",
            visitor_hash=visitor,
            session_id=session
        )
        assert w1 is True

        # 2. Log second impression within the hour -> should deduplicate (return False)
        w2 = await AnalyticsService.log_advertisement_event(
            db=db,
            advertisement_id=ad.id,
            advertisement_type="PLATFORM",
            event_type="IMPRESSION",
            visitor_hash=visitor,
            session_id=session
        )
        assert w2 is False

        # 3. Log click -> should always record (return True)
        c1 = await AnalyticsService.log_advertisement_event(
            db=db,
            advertisement_id=ad.id,
            advertisement_type="PLATFORM",
            event_type="CLICK",
            visitor_hash=visitor,
            session_id=session
        )
        assert c1 is True

        c2 = await AnalyticsService.log_advertisement_event(
            db=db,
            advertisement_id=ad.id,
            advertisement_type="PLATFORM",
            event_type="CLICK",
            visitor_hash=visitor,
            session_id=session
        )
        assert c2 is True

        # Clean up
        from sqlalchemy import delete
        await db.execute(delete(AdvertisementAnalytics).where(
            (AdvertisementAnalytics.platform_advertisement_id == ad.id) |
            (AdvertisementAnalytics.temple_advertisement_id == ad.id)
        ))
        await db.delete(ad)
        await db.commit()


@pytest.mark.asyncio
async def test_telemetry_endpoints(client):
    """Test log event endpoints and Pydantic validation."""
    # 1. Post invalid event name -> expect HTTP 400
    resp = await client.post(
        "/api/v1/public/analytics/events",
        json={
            "temple_id": str(TEMPLE_ID),
            "event_name": "INVALID_EVENT_CLICK",
            "visitor_hash": "somehash",
            "session_id": "session"
        }
    )
    assert resp.status_code == 400
    assert "Invalid analytics event name" in resp.json()["error"]["message"]

    # 2. Post valid event name -> expect HTTP 200 (enqueued)
    resp2 = await client.post(
        "/api/v1/public/analytics/events",
        json={
            "temple_id": str(TEMPLE_ID),
            "event_name": "BOOK_POOJA_CLICK",
            "visitor_hash": "somehash",
            "session_id": "session"
        }
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "enqueued"


@pytest.mark.asyncio
async def test_recommendations_crud_and_resolver(client, auth_headers):
    """Test creation, CRUD, and resolver of recommendations."""
    async with TestSessionLocal() as db:
        # Create a mock service and product to work with
        service = TempleService(
            temple_id=TEMPLE_ID,
            service_name="Primary Pooja",
            service_type="ARCHANA",
            price=150.0
        )
        rec_product = StoreProduct(
            temple_id=TEMPLE_ID,
            name="Recommended Prasadam",
            category="Food",
            unit="box",
            unit_price=35.0
        )
        db.add(service)
        db.add(rec_product)
        await db.commit()
        await db.refresh(service)
        await db.refresh(rec_product)
        service_id = service.id
        rec_product_id = rec_product.id

    # 1. Create a recommendation relationship
    payload = {
        "source_service_id": str(service_id),
        "source_product_id": None,
        "recommendation_source_type": "SERVICE",
        "recommended_service_id": None,
        "recommended_product_id": str(rec_product_id),
        "display_order": 1,
        "is_active": True
    }
    resp = await client.post(
        "/api/v1/manager/recommendations",
        json=payload,
        headers=auth_headers
    )
    assert resp.status_code == 200
    rec_body = resp.json()
    assert rec_body["display_order"] == 1
    assert rec_body["recommended_product_id"] == str(rec_product_id)

    # 2. Resolve recommendations via public API
    resp_resolve = await client.get(
        f"/api/v1/public/temples/test/recommendations?service_id={service_id}"
    )
    assert resp_resolve.status_code == 200
    resolve_body = resp_resolve.json()
    assert resolve_body["source_type"] == "SERVICE"
    assert len(resolve_body["recommendations"]) == 1
    assert resolve_body["recommendations"][0]["recommendation_type"] == "PRODUCT"
    assert resolve_body["recommendations"][0]["product"]["name"] == "Recommended Prasadam"

    # Clean up recommendations and mock data
    async with TestSessionLocal() as db:
        # Resolve recommendation record by UUID from response
        rec_uuid = uuid.UUID(rec_body["id"])
        rec_db = await db.get(ServiceRecommendation, rec_uuid)
        if rec_db:
            await db.delete(rec_db)
        
        svc_db = await db.get(TempleService, service_id)
        if svc_db:
            await db.delete(svc_db)

        prod_db = await db.get(StoreProduct, rec_product_id)
        if prod_db:
            await db.delete(prod_db)

        await db.commit()
