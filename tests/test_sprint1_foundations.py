import pytest
import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from tests.conftest import TestSessionLocal, TEMPLE_ID
from app.modules.temple_management.models.temple_models import (
    PlatformAdvertisement,
    TempleAdvertisement,
    AdvertisementAnalytics,
    TempleFollower,
    TempleFollowerPreference,
    ServiceRecommendation,
    TempleService,
    ServiceType
)
from app.modules.governance.models.governance_models import PlatformGlobalSetting
from app.modules.bookings.models.booking_models import ServiceBooking, GuestBooking, NotificationMode, BookingSource
from app.modules.auth.models.auth_models import User
from app.services.notification_service import NotificationService
from app.core.notifications import (
    PushNotificationProvider,
    EmailNotificationProvider,
    SMSNotificationProvider
)

@pytest.mark.asyncio
async def test_sprint1_models_persistence():
    """Verify that all Sprint 1 models can be created and persisted to SQLite."""
    async with TestSessionLocal() as db:
        # 1. Platform Global Setting
        setting = PlatformGlobalSetting(
            key="test_directory_layout",
            value={"layout": "grid", "visible_categories": ["pooja", "store"]}
        )
        db.add(setting)

        # Create a test user for relationships
        test_user = User(
            user_id="sprint1_test_devotee@temple",
            password_hash="mock_hash",
            role="DEVOTEE",
            temple_id=TEMPLE_ID
        )
        db.add(test_user)
        await db.flush()

        # 2. Temple Follower with is_active
        follower = TempleFollower(
            user_id=test_user.id,
            temple_id=TEMPLE_ID,
            is_active=True
        )
        db.add(follower)
        await db.flush()

        # 3. Temple Follower Preference
        pref = TempleFollowerPreference(
            follower_id=follower.id,
            push_enabled=True,
            festival_enabled=True,
            announcement_enabled=False,
            event_enabled=True,
            pooja_reminder_enabled=False,
            custom_categories={"custom_alert": True}
        )
        db.add(pref)

        # 4. Service Recommendation setup (requires services)
        src_service = TempleService(
            temple_id=TEMPLE_ID,
            service_name="Ganapathy Homam",
            service_type=ServiceType.ARCHANA,
            price=150.0,
            active=True
        )
        rec_service = TempleService(
            temple_id=TEMPLE_ID,
            service_name="Coconut Offering",
            service_type=ServiceType.OFFERING,
            price=30.0,
            active=True
        )
        db.add(src_service)
        db.add(rec_service)
        await db.flush()

        rec = ServiceRecommendation(
            temple_id=TEMPLE_ID,
            source_service_id=src_service.id,
            recommended_service_id=rec_service.id,
            display_order=1,
            is_active=True
        )
        db.add(rec)

        # 5. Platform and Temple Advertisements
        now = datetime.now(timezone.utc)
        platform_ad = PlatformAdvertisement(
            placement="HEADER_LEADERBOARD",
            media_urls=["https://platform.com/banner1.jpg"],
            target_url="https://platform.com/target",
            start_date=now,
            end_date=now + timedelta(days=5),
            is_active=True
        )
        db.add(platform_ad)

        temple_ad = TempleAdvertisement(
            temple_id=TEMPLE_ID,
            placement="TEMPLE_DETAILS_INLINE",
            media_urls=["https://temple.com/ad1.jpg"],
            target_url="https://temple.com/target",
            start_date=now,
            end_date=now + timedelta(days=5),
            display_order=0,
            is_active=True
        )
        db.add(temple_ad)
        await db.flush()

        # 6. Advertisement Analytics for Temple Ad
        analytics1 = AdvertisementAnalytics(
            advertisement_type="TEMPLE",
            temple_advertisement_id=temple_ad.id,
            event_type="IMPRESSION",
            visitor_hash="hash_abc123",
            session_id="session_1"
        )
        db.add(analytics1)

        # 7. Advertisement Analytics for Platform Ad
        analytics2 = AdvertisementAnalytics(
            advertisement_type="PLATFORM",
            platform_advertisement_id=platform_ad.id,
            event_type="CLICK",
            visitor_hash="hash_xyz987",
            session_id="session_2"
        )
        db.add(analytics2)

        # 8. Extended Bookings Fields
        s_booking = ServiceBooking(
            temple_id=TEMPLE_ID,
            devotee_user_id=test_user.id,
            service_id=src_service.id,
            booking_date=now,
            amount=150.0,
            notification_mode=NotificationMode.EMAIL,
            notification_destination="test@devotee.com",
            dakshina_amount=50.0,
            booking_source=BookingSource.WEB_PUBLIC,
            booking_metadata={"gotram": "Kashyapa", "nakshatra": "Rohini"}
        )
        db.add(s_booking)

        g_booking = GuestBooking(
            temple_id=TEMPLE_ID,
            service_id=src_service.id,
            guest_name="Guest Devotee",
            guest_phone="+919876543210",
            guest_email="guest@devotee.com",
            booking_date=now,
            amount=150.0,
            notification_mode=NotificationMode.SMS,
            notification_destination="+919876543210",
            dakshina_amount=20.0,
            booking_source=BookingSource.MOBILE_APP,
            booking_metadata={"nakshatra": "Bharani"}
        )
        db.add(g_booking)

        # Commit everything to SQLite
        await db.commit()

    # Query them back to verify persistence
    async with TestSessionLocal() as db:
        from sqlalchemy.orm import selectinload
        saved_setting = (await db.execute(select(PlatformGlobalSetting).filter(PlatformGlobalSetting.key == "test_directory_layout"))).scalar_one()
        assert saved_setting.value["layout"] == "grid"

        saved_follower = (await db.execute(
            select(TempleFollower)
            .options(selectinload(TempleFollower.preferences))
            .filter(TempleFollower.user_id == test_user.id)
        )).scalar_one()
        assert saved_follower.is_active is True
        assert saved_follower.preferences.push_enabled is True
        assert saved_follower.preferences.announcement_enabled is False

        saved_rec = (await db.execute(select(ServiceRecommendation).filter(ServiceRecommendation.source_service_id == src_service.id))).scalar_one()
        assert saved_rec.recommended_service_id == rec_service.id

        saved_analytics = (await db.execute(select(AdvertisementAnalytics).filter(AdvertisementAnalytics.advertisement_type == "TEMPLE"))).scalar_one()
        assert saved_analytics.visitor_hash == "hash_abc123"

        saved_s_booking = (await db.execute(select(ServiceBooking).filter(ServiceBooking.devotee_user_id == test_user.id))).scalar_one()
        assert saved_s_booking.dakshina_amount == 50.0
        assert saved_s_booking.booking_metadata["gotram"] == "Kashyapa"

        saved_g_booking = (await db.execute(select(GuestBooking).filter(GuestBooking.guest_name == "Guest Devotee"))).scalar_one()
        assert saved_g_booking.booking_source == BookingSource.MOBILE_APP


@pytest.mark.asyncio
async def test_advertisement_analytics_constraints():
    """Verify check constraints for advertisement analytics explicit ownership."""
    async with TestSessionLocal() as db:
        # Violate: both are set
        now = datetime.now(timezone.utc)
        platform_ad = PlatformAdvertisement(
            placement="HEADER_LEADERBOARD",
            media_urls=["https://platform.com/banner1.jpg"],
            target_url="https://platform.com/target",
            start_date=now,
            end_date=now + timedelta(days=5),
            is_active=True
        )
        temple_ad = TempleAdvertisement(
            temple_id=TEMPLE_ID,
            placement="TEMPLE_DETAILS_INLINE",
            media_urls=["https://temple.com/ad1.jpg"],
            target_url="https://temple.com/target",
            start_date=now,
            end_date=now + timedelta(days=5),
            display_order=0,
            is_active=True
        )
        db.add(platform_ad)
        db.add(temple_ad)
        await db.flush()

        bad_analytics1 = AdvertisementAnalytics(
            advertisement_type="TEMPLE",
            platform_advertisement_id=platform_ad.id,
            temple_advertisement_id=temple_ad.id,
            event_type="IMPRESSION",
            visitor_hash="visitor_bad1"
        )
        db.add(bad_analytics1)
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

    async with TestSessionLocal() as db:
        # Violate: both are NULL
        bad_analytics2 = AdvertisementAnalytics(
            advertisement_type="PLATFORM",
            platform_advertisement_id=None,
            temple_advertisement_id=None,
            event_type="IMPRESSION",
            visitor_hash="visitor_bad2"
        )
        db.add(bad_analytics2)
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


@pytest.mark.asyncio
async def test_service_recommendation_constraints():
    """Verify check constraints for service recommendation polymorphic target."""
    async with TestSessionLocal() as db:
        src_service = TempleService(
            temple_id=TEMPLE_ID,
            service_name="Source Pooja",
            service_type=ServiceType.ARCHANA,
            price=50.0,
            active=True
        )
        rec_service = TempleService(
            temple_id=TEMPLE_ID,
            service_name="Recommended Pooja",
            service_type=ServiceType.OFFERING,
            price=10.0,
            active=True
        )
        db.add(src_service)
        db.add(rec_service)
        await db.flush()

        # Violate: both recommended_service_id and recommended_product_id are set (or both NULL)
        bad_rec = ServiceRecommendation(
            temple_id=TEMPLE_ID,
            source_service_id=src_service.id,
            recommended_service_id=None,
            recommended_product_id=None
        )
        db.add(bad_rec)
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()


@pytest.mark.asyncio
async def test_notification_provider_routing():
    """Verify INotificationProvider resolution and NotificationService routing."""
    # 1. Verify provider interfaces
    push = PushNotificationProvider()
    email = EmailNotificationProvider()
    sms = SMSNotificationProvider()

    assert await push.send_notification("user1", "message text", {}) is True
    assert await email.send_notification("email@domain.com", "message text", {}) is True
    assert await sms.send_notification("+919999999999", "message text", {}) is True

    # 2. Test NotificationService unified routing
    async with TestSessionLocal() as db:
        recipient_uuid = str(uuid.uuid4())
        success = await NotificationService.route_notification(
            db=db,
            temple_id=TEMPLE_ID,
            mode="SMS",
            recipient=recipient_uuid,
            title="Unified Alert",
            message="Your booking is confirmed"
        )
        assert success is True
        await db.commit()

    # Query to check persistent notification log
    async with TestSessionLocal() as db:
        saved_notifs = await NotificationService.get_user_notifications(
            db=db,
            temple_id=TEMPLE_ID,
            user_id=uuid.UUID(recipient_uuid),
            role="DEVOTEE"
        )
        assert len(saved_notifs) == 1
        assert saved_notifs[0].title == "Unified Alert"
        assert saved_notifs[0].message == "Your booking is confirmed"
