import pytest
import uuid
from datetime import date, time
from sqlalchemy.future import select

from app.core.database import AsyncSessionLocal
from app.models.domain import (
    Temple,
    TempleWebsiteSettings,
    TempleAnnouncement,
    TempleActivity,
    TempleImage,
    AuditLog,
    ImageCategory,
    ActivityStatus,
)
from tests.conftest import TEMPLE_ID, ADMIN_USER_ID


@pytest.mark.asyncio
async def test_get_settings(client, auth_headers):
    """GET /manager/website-settings returns default settings if none exist."""
    resp = await client.get("/api/v1/manager/website-settings", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["theme_name"] == "default"
    assert data["primary_color"] == "#ff6600"
    assert data["secondary_color"] == "#ffcc00"
    assert data["hero_layout"] == "split"
    assert "hero" in data["section_order"]


@pytest.mark.asyncio
async def test_update_settings_valid(client, auth_headers):
    """PUT /manager/website-settings successfully updates settings with valid HEX colors."""
    payload = {
        "theme_name": "custom-sunset",
        "primary_color": "#ff0000",
        "secondary_color": "#fff",
        "hero_layout": "full-screen",
        "notice_board_content": {
            "rules": ["No footwear inside"],
            "dress_code": "Traditional",
            "photography_restrictions": "Sanctum prohibited",
            "parking_instructions": "Free outside"
        }
    }
    resp = await client.put("/api/v1/manager/website-settings", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["theme_name"] == "custom-sunset"
    assert data["primary_color"] == "#ff0000"
    assert data["secondary_color"] == "#fff"
    assert data["hero_layout"] == "full-screen"
    assert data["notice_board_content"]["rules"] == ["No footwear inside"]

    # Verify audit log was created
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AuditLog)
            .filter(AuditLog.temple_id == TEMPLE_ID, AuditLog.action == "UPDATE_WEBSITE_SETTINGS")
            .order_by(AuditLog.created_at.desc())
        )
        audit = result.scalars().first()
        assert audit is not None
        assert audit.new_value["theme_name"] == "custom-sunset"


@pytest.mark.asyncio
async def test_update_settings_invalid_colors(client, auth_headers):
    """PUT /manager/website-settings fails when provided with invalid non-HEX colors."""
    invalid_colors = ["red", "rgb(255,0,0)", "hsl(0, 100%, 50%)", "#ff00000", "ff0"]
    for color in invalid_colors:
        payload = {"primary_color": color}
        resp = await client.put("/api/v1/manager/website-settings", json=payload, headers=auth_headers)
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_announcement_crud(client, auth_headers):
    """Verify full CRUD lifecycle for Announcements including pinned sorting."""
    # 1. Create Pinned Announcement
    payload1 = {
        "title": "Important Festival Alert",
        "content": "Due to solar eclipse, temple hours are modified.",
        "is_active": True,
        "is_pinned": True,
        "priority": 10,
        "display_order": 1
    }
    resp1 = await client.post("/api/v1/manager/announcements", json=payload1, headers=auth_headers)
    assert resp1.status_code == 201
    ann_pinned = resp1.json()
    assert ann_pinned["title"] == "Important Festival Alert"
    assert ann_pinned["is_pinned"] is True

    # 2. Create Normal Announcement
    payload2 = {
        "title": "Prasadam Counter Update",
        "content": "New timings for payasam distribution.",
        "is_active": True,
        "is_pinned": False,
        "priority": 1,
        "display_order": 2
    }
    resp2 = await client.post("/api/v1/manager/announcements", json=payload2, headers=auth_headers)
    assert resp2.status_code == 201
    ann_normal = resp2.json()

    # 3. List announcements, verify pinned is first
    list_resp = await client.get("/api/v1/manager/announcements", headers=auth_headers)
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert len(items) >= 2
    assert items[0]["id"] == ann_pinned["id"]  # Pinned first
    assert items[1]["id"] == ann_normal["id"]

    # 4. Update Announcement
    update_payload = {"title": "Solar Eclipse Hours", "is_pinned": False}
    up_resp = await client.put(
        f"/api/v1/manager/announcements/{ann_pinned['id']}",
        json=update_payload,
        headers=auth_headers
    )
    assert up_resp.status_code == 200
    assert up_resp.json()["title"] == "Solar Eclipse Hours"
    assert up_resp.json()["is_pinned"] is False

    # 5. Delete Announcement
    del_resp = await client.delete(
        f"/api/v1/manager/announcements/{ann_normal['id']}",
        headers=auth_headers
    )
    assert del_resp.status_code == 200
    
    # Confirm deletion
    list_resp2 = await client.get("/api/v1/manager/announcements", headers=auth_headers)
    assert not any(i["id"] == ann_normal["id"] for i in list_resp2.json())


@pytest.mark.asyncio
async def test_activity_crud(client, auth_headers):
    """Verify full CRUD lifecycle for Activities including status updates."""
    # 1. Create Activity
    payload = {
        "title": "Maha Shivaratri Pooja",
        "description": "All-night vigils and offerings.",
        "activity_date": "2026-06-15",
        "start_time": "18:00:00",
        "end_time": "06:00:00",
        "location": "Main Sanctum",
        "is_active": True,
        "status": "UPCOMING",
        "livestream_url": "https://youtube.com/live/example"
    }
    resp = await client.post("/api/v1/manager/activities", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    act = resp.json()
    assert act["title"] == "Maha Shivaratri Pooja"
    assert act["status"] == "UPCOMING"
    assert act["livestream_url"] == "https://youtube.com/live/example"

    # 2. List
    list_resp = await client.get("/api/v1/manager/activities", headers=auth_headers)
    assert list_resp.status_code == 200
    assert any(i["id"] == act["id"] for i in list_resp.json())

    # 3. Update Status
    up_payload = {"status": "ACTIVE"}
    up_resp = await client.put(
        f"/api/v1/manager/activities/{act['id']}",
        json=up_payload,
        headers=auth_headers
    )
    assert up_resp.status_code == 200
    assert up_resp.json()["status"] == "ACTIVE"

    # 4. Delete
    del_resp = await client.delete(
        f"/api/v1/manager/activities/{act['id']}",
        headers=auth_headers
    )
    assert del_resp.status_code == 200


@pytest.mark.asyncio
async def test_image_gallery_crud(client, auth_headers):
    """Verify Image gallery actions enforce image category validation."""
    # 1. Create Image with Category
    payload = {
        "image_url": "https://images.example.com/banner.jpg",
        "caption": "Main Entrance Desktop Banner",
        "category": "HERO_DESKTOP"
    }
    resp = await client.post("/api/v1/manager/images", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    img = resp.json()
    assert img["category"] == "HERO_DESKTOP"
    assert img["image_url"] == "https://images.example.com/banner.jpg"

    # 2. List images
    list_resp = await client.get("/api/v1/manager/images", headers=auth_headers)
    assert list_resp.status_code == 200
    assert any(i["id"] == img["id"] for i in list_resp.json())

    # 3. Update category
    up_payload = {"category": "HERO_MOBILE"}
    up_resp = await client.put(
        f"/api/v1/manager/images/{img['id']}",
        json=up_payload,
        headers=auth_headers
    )
    assert up_resp.status_code == 200
    assert up_resp.json()["category"] == "HERO_MOBILE"

    # 4. Delete image
    del_resp = await client.delete(
        f"/api/v1/manager/images/{img['id']}",
        headers=auth_headers
    )
    assert del_resp.status_code == 200


@pytest.mark.asyncio
async def test_tenant_isolation(client, auth_headers):
    """Verify that a manager cannot view or modify digital experience entities of another temple."""
    # 1. Create a different temple and announcements directly in the DB
    other_temple_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        other_temple = Temple(id=other_temple_id, name="Isolated Temple", domain="isolated")
        db.add(other_temple)
        
        announcement = TempleAnnouncement(
            id=uuid.uuid4(),
            temple_id=other_temple_id,
            title="Isolated Announcement",
            content="Should not be visible to TEMPLE_ID",
            is_active=True
        )
        db.add(announcement)
        await db.commit()
        ann_id = str(announcement.id)

    # 2. Attempt to update another temple's announcement (should fail with 404 since it's filtered out)
    resp_up = await client.put(
        f"/api/v1/manager/announcements/{ann_id}",
        json={"title": "Hack Attempt"},
        headers=auth_headers
    )
    assert resp_up.status_code == 404

    # 3. Attempt to delete (should fail with 404)
    resp_del = await client.delete(
        f"/api/v1/manager/announcements/{ann_id}",
        headers=auth_headers
    )
    assert resp_del.status_code == 404


@pytest.mark.asyncio
async def test_public_portal_endpoint(client, auth_headers):
    """Verify that GET /api/v1/public/temples/{slug}/portal returns consolidated profile, settings, announcements, and activities."""
    # Update test temple status to APPROVED in database to allow publication
    async with AsyncSessionLocal() as db:
        stmt = select(Temple).filter(Temple.id == TEMPLE_ID)
        res = await db.execute(stmt)
        t = res.scalars().first()
        if t:
            t.status = "APPROVED"
            await db.commit()

    # 1. Create one active announcement and activity so they are returned
    payload_ann = {
        "title": "Public Pinned Announcement",
        "content": "This is public content.",
        "is_active": True,
        "is_pinned": True,
        "priority": 5,
        "display_order": 1
    }
    resp1 = await client.post("/api/v1/manager/announcements", json=payload_ann, headers=auth_headers)
    assert resp1.status_code == 201

    payload_act = {
        "title": "Public Shivaratri Activity",
        "description": "Public ritual.",
        "activity_date": "2026-06-15",
        "start_time": "18:00:00",
        "end_time": "22:00:00",
        "location": "Temple Hall",
        "is_active": True,
        "status": "UPCOMING",
        "livestream_url": "https://youtube.com/live/example"
    }
    resp2 = await client.post("/api/v1/manager/activities", json=payload_act, headers=auth_headers)
    assert resp2.status_code == 201

    # 2. Request public portal details before publishing (should be 404)
    resp_before = await client.get("/api/v1/public/temples/test/portal")
    assert resp_before.status_code == 404

    # 3. Verify public temples list does not contain it yet
    list_before = await client.get("/api/v1/public/temples")
    assert list_before.status_code == 200
    assert not any(t["slug"] == "test" for t in list_before.json())

    # 4. Fetch status (should indicate not published)
    status_before = await client.get("/api/v1/manager/website-settings/status", headers=auth_headers)
    assert status_before.status_code == 200
    assert status_before.json()["isPublished"] is False

    # 5. Publish website
    pub_resp = await client.post("/api/v1/manager/website-settings/publish", headers=auth_headers)
    assert pub_resp.status_code == 200
    assert pub_resp.json()["status"] == "success"

    # 6. Fetch status again (should indicate published)
    status_after = await client.get("/api/v1/manager/website-settings/status", headers=auth_headers)
    assert status_after.status_code == 200
    assert status_after.json()["isPublished"] is True

    # 7. Request public portal details after publishing (should be 200)
    resp = await client.get("/api/v1/public/temples/test/portal")
    assert resp.status_code == 200
    
    data = resp.json()
    assert "profile" in data
    assert "settings" in data
    assert "announcements" in data
    assert "activities" in data
    
    # Assert specific fields
    assert data["profile"]["domain"] == "test"
    assert data["settings"]["theme_name"] in ("default", "custom-sunset")
    assert any(a["title"] == "Public Pinned Announcement" for a in data["announcements"])
    assert any(a["title"] == "Public Shivaratri Activity" for a in data["activities"])
    
    # 8. Verify public temples list contains the published temple
    list_after = await client.get("/api/v1/public/temples")
    assert list_after.status_code == 200
    assert any(t["slug"] == "test" for t in list_after.json())

    # 9. Unpublish website
    unpub_resp = await client.post("/api/v1/manager/website-settings/unpublish", headers=auth_headers)
    assert unpub_resp.status_code == 200
    assert unpub_resp.json()["status"] == "success"

    # 10. Fetch status and portal after unpublishing (should be unpublished / 404)
    status_unpub = await client.get("/api/v1/manager/website-settings/status", headers=auth_headers)
    assert status_unpub.json()["isPublished"] is False

    resp_unpub = await client.get("/api/v1/public/temples/test/portal")
    assert resp_unpub.status_code == 404


@pytest.mark.asyncio
async def test_public_bootstrap_endpoint(client, auth_headers):
    """Verify GET /api/v1/public/temples/{slug}/bootstrap and feature visibility configurations."""
    # 1. Update test temple status to APPROVED
    async with AsyncSessionLocal() as db:
        stmt = select(Temple).filter(Temple.id == TEMPLE_ID)
        res = await db.execute(stmt)
        t = res.scalars().first()
        if t:
            t.status = "APPROVED"
            await db.commit()

    # 2. Clear out feature_visibility draft settings and publish first
    reset_payload = {
        "feature_visibility": None
    }
    resp_reset = await client.put("/api/v1/manager/website-settings", json=reset_payload, headers=auth_headers)
    assert resp_reset.status_code == 200

    pub_resp = await client.post("/api/v1/manager/website-settings/publish", headers=auth_headers)
    assert pub_resp.status_code == 200

    # 3. Request bootstrap, verify safe default fallback values
    resp = await client.get("/api/v1/public/temples/test/bootstrap")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "2.0"
    assert "generatedAt" in data
    assert "profile" in data
    assert "settings" in data
    assert "featureVisibility" in data
    assert "publicActions" in data
    
    # Assert fallbacks are all True
    fv = data["featureVisibility"]
    assert fv["enablePoojaBooking"] is True
    assert fv["enableOfferings"] is True
    assert fv["enableStore"] is True
    assert fv["enableAnnouncements"] is True

    # 4. Save custom feature visibility configuration to draft settings
    custom_payload = {
        "feature_visibility": {
            "enablePoojaBooking": False,
            "enableOfferings": True,
            "enableStore": False,
            "enableGallery": False,
            "enableAnnouncements": True
        }
    }
    resp_save = await client.put("/api/v1/manager/website-settings", json=custom_payload, headers=auth_headers)
    assert resp_save.status_code == 200

    # 5. Publish to live snapshot
    pub_resp2 = await client.post("/api/v1/manager/website-settings/publish", headers=auth_headers)
    assert pub_resp2.status_code == 200

    # 6. Request bootstrap again and verify custom values are active
    resp2 = await client.get("/api/v1/public/temples/test/bootstrap")
    assert resp2.status_code == 200
    data2 = resp2.json()
    
    fv2 = data2["featureVisibility"]
    assert fv2["enablePoojaBooking"] is False
    assert fv2["enableOfferings"] is True
    assert fv2["enableStore"] is False
    assert fv2["enableGallery"] is False
    assert fv2["enableAnnouncements"] is True

    # 7. Check publicActions dynamic rendering based on toggles
    actions = data2["publicActions"]
    # enablePoojaBooking is False, so Book Pooja should not be in publicActions
    assert not any(a["name"] == "Book Pooja" for a in actions)
    # enableOfferings is True, so Submit Offering should be in publicActions
    assert any(a["name"] == "Submit Offering" for a in actions)


@pytest.mark.asyncio
async def test_festival_crud(client, auth_headers):
    """Verify full CRUD lifecycle for the dedicated TempleFestival entity."""
    # 1. Create Festival
    payload = {
        "name": "Makaravilakku Festival",
        "description": "Annual festival with special poojas.",
        "start_date": "2026-01-14",
        "end_date": "2026-01-18",
        "priority": 5,
        "banner_image": "https://images.example.com/fest.jpg",
        "catalogue_urls": ["https://images.example.com/brochure.pdf"],
        "is_active": True
    }
    resp = await client.post("/api/v1/manager/festivals", json=payload, headers=auth_headers)
    assert resp.status_code == 201
    fest = resp.json()
    assert fest["name"] == "Makaravilakku Festival"
    assert fest["priority"] == 5
    assert "id" in fest

    # 2. List
    list_resp = await client.get("/api/v1/manager/festivals", headers=auth_headers)
    assert list_resp.status_code == 200
    items = list_resp.json()
    assert any(i["id"] == fest["id"] for i in items)

    # 3. Update
    up_payload = {"name": "Makaravilakku Festival Refined", "priority": 10}
    up_resp = await client.put(f"/api/v1/manager/festivals/{fest['id']}", json=up_payload, headers=auth_headers)
    assert up_resp.status_code == 200
    assert up_resp.json()["name"] == "Makaravilakku Festival Refined"
    assert up_resp.json()["priority"] == 10

    # 4. Delete
    del_resp = await client.delete(f"/api/v1/manager/festivals/{fest['id']}", headers=auth_headers)
    assert del_resp.status_code == 200

    # Confirm deletion
    list_resp2 = await client.get("/api/v1/manager/festivals", headers=auth_headers)
    assert not any(i["id"] == fest["id"] for i in list_resp2.json())


@pytest.mark.asyncio
async def test_status_engine_timings_and_activities(client, auth_headers):
    """Verify that multi-session timings and activities are saved, published, and resolve correctly in bootstrap."""
    # Update settings draft with location, timings, and activities settings
    settings_payload = {
        "location_settings": {
            "google_maps_url": "https://maps.google.com/test",
            "latitude": 9.5,
            "longitude": 76.5,
            "location_label": "Navigate to Temple"
        },
        "timings_settings": [
            {
                "session_name": "Morning Darshan",
                "day_of_week": "Daily",
                "opening_time": "05:00 AM",
                "closing_time": "12:00 PM",
                "is_special": False
            },
            {
                "session_name": "Evening Darshan",
                "day_of_week": "Daily",
                "opening_time": "05:00 PM",
                "closing_time": "08:30 PM",
                "is_special": False
            }
        ],
        "daily_activities_settings": [
            {
                "activity_name": "Nirmalyam",
                "time": "04:30 AM",
                "repeat_days": ["Daily"],
                "description": "First offering of the day"
            },
            {
                "activity_name": "Deeparadhana",
                "time": "06:30 PM",
                "repeat_days": ["Daily"],
                "description": "Evening light worship"
            }
        ]
    }
    
    # Save settings draft
    resp = await client.put("/api/v1/manager/website-settings", json=settings_payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["location_settings"]["location_label"] == "Navigate to Temple"
    assert len(data["timings_settings"]) == 2
    assert len(data["daily_activities_settings"]) == 2

    # Publish settings
    pub_resp = await client.post("/api/v1/manager/website-settings/publish", headers=auth_headers)
    assert pub_resp.status_code == 200

    # Get bootstrap and check settings are present
    boot_resp = await client.get("/api/v1/public/temples/test/bootstrap")
    assert boot_resp.status_code == 200
    boot_data = boot_resp.json()
    
    boot_settings = boot_data["settings"]
    assert boot_settings["location_settings"]["google_maps_url"] == "https://maps.google.com/test"
    assert len(boot_settings["timings_settings"]) == 2
    assert len(boot_settings["daily_activities_settings"]) == 2


