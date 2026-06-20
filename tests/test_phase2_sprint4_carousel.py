import pytest
from httpx import AsyncClient
from uuid import uuid4
from datetime import datetime, timezone
import sqlalchemy as sa
from sqlalchemy.future import select
from app.core.database import AsyncSessionLocal
from app.models.domain import Temple, StateMaster, DistrictMaster
from app.modules.temple_management.models.temple_models import TempleProfile, TempleFestival
from app.modules.governance.models.governance_models import PlatformGlobalSetting
from app.core.cache import GlobalConfigurationCache

@pytest.mark.anyio
async def test_homepage_carousel_draft_flow(client: AsyncClient, superadmin_auth_headers: dict):
    # 1. Get empty draft
    res = await client.get("/api/v1/superadmin/homepage-carousel/draft", headers=superadmin_auth_headers)
    assert res.status_code == 200
    assert res.json() == {"slides": []}

    # 2. Put invalid slide type
    invalid_payload = {"slides": [{"type": "INVALID_TYPE", "is_active": True}]}
    res = await client.put("/api/v1/superadmin/homepage-carousel/draft", json=invalid_payload, headers=superadmin_auth_headers)
    assert res.status_code == 400
    assert "invalid type" in res.json()["error"]["message"].lower()

    # 3. Put missing temple_id for FEATURED_TEMPLE
    invalid_payload2 = {"slides": [{"type": "FEATURED_TEMPLE", "is_active": True}]}
    res = await client.put("/api/v1/superadmin/homepage-carousel/draft", json=invalid_payload2, headers=superadmin_auth_headers)
    assert res.status_code == 400
    assert "specify temple_id" in res.json()["error"]["message"].lower()

    # 4. Put non-existent temple_id
    non_existent_uuid = str(uuid4())
    invalid_payload3 = {"slides": [{"type": "FEATURED_TEMPLE", "temple_id": non_existent_uuid, "is_active": True}]}
    res = await client.put("/api/v1/superadmin/homepage-carousel/draft", json=invalid_payload3, headers=superadmin_auth_headers)
    assert res.status_code == 400
    assert "does not exist" in res.json()["error"]["message"].lower()


@pytest.mark.anyio
async def test_homepage_carousel_publish_and_resolve(client: AsyncClient, superadmin_auth_headers: dict):
    async with AsyncSessionLocal() as db:
        # Create State & District
        state = StateMaster(id=uuid4(), name="Carousel State", slug="carousel-state", code="CS", created_at=datetime.now(timezone.utc))
        district = DistrictMaster(id=uuid4(), state_id=state.id, name="Carousel District", slug="carousel-district", code="CD", created_at=datetime.now(timezone.utc))
        db.add(state)
        db.add(district)
        await db.commit()

        # Create Temple
        temple = Temple(
            id=uuid4(), name="Carousel Test Temple", domain="carousel-temple", is_active=True, status="APPROVED",
            directory_status="ACTIVE", state_id=state.id, district_id=district.id
        )
        db.add(temple)
        await db.commit()

        # Profile
        profile = TempleProfile(temple_id=temple.id, location="Carousel Loc", state="Carousel State", district="Carousel District")
        db.add(profile)
        await db.commit()

        # Create Festival
        festival = TempleFestival(
            id=uuid4(), temple_id=temple.id, name="Carousel Test Festival", is_active=True,
            start_date=datetime.now(timezone.utc).date(), end_date=datetime.now(timezone.utc).date()
        )
        db.add(festival)
        await db.commit()

        temple_id = str(temple.id)
        festival_id = str(festival.id)

    # 1. Update draft with valid FEATURED_TEMPLE, FESTIVAL, and CUSTOM slides
    valid_payload = {
        "slides": [
            {
                "type": "FEATURED_TEMPLE",
                "temple_id": temple_id,
                "is_active": True
            },
            {
                "type": "FESTIVAL",
                "festival_id": festival_id,
                "is_active": True
            },
            {
                "type": "CUSTOM",
                "title": "Custom Banner Title",
                "subtitle": "Custom Banner Subtitle",
                "image_url": "https://images.com/custom.png",
                "target_url": "https://images.com/custom-target",
                "is_active": True
            }
        ]
    }
    
    put_res = await client.put("/api/v1/superadmin/homepage-carousel/draft", json=valid_payload, headers=superadmin_auth_headers)
    assert put_res.status_code == 200
    assert len(put_res.json()["slides"]) == 3

    # 2. Publish draft
    pub_res = await client.post("/api/v1/superadmin/homepage-carousel/publish", headers=superadmin_auth_headers)
    assert pub_res.status_code == 200
    assert pub_res.json()["version"] >= 1

    # 3. Fetch consolidated homepage and verify carousel contains resolved slides
    hp_res = await client.get("/api/v1/public/homepage")
    assert hp_res.status_code == 200
    hp_data = hp_res.json()
    assert "carousel" in hp_data
    carousel = hp_data["carousel"]
    assert len(carousel) == 3

    # FEATURED_TEMPLE resolved details
    slide1 = carousel[0]
    assert slide1["type"] == "FEATURED_TEMPLE"
    assert slide1["title"] == "Carousel Test Temple"
    assert slide1["subtitle"] == "Carousel District, Carousel State"
    assert slide1["image_url"] == "/static/default-temple.jpg"  # image fallback
    assert slide1["target_url"] == "/carousel-temple/portal"

    # FESTIVAL resolved details
    slide2 = carousel[1]
    assert slide2["type"] == "FESTIVAL"
    assert slide2["title"] == "Carousel Test Festival"
    assert "Carousel Test Temple" in slide2["subtitle"]
    assert slide2["image_url"] == "/static/default-temple.jpg"  # festival fallback to temple image (missing), then to default
    assert slide2["target_url"] == "/carousel-temple/portal"

    # CUSTOM slide details
    slide3 = carousel[2]
    assert slide3["type"] == "CUSTOM"
    assert slide3["title"] == "Custom Banner Title"
    assert slide3["subtitle"] == "Custom Banner Subtitle"
    assert slide3["image_url"] == "https://images.com/custom.png"
    assert slide3["target_url"] == "https://images.com/custom-target"


@pytest.mark.anyio
async def test_homepage_carousel_optional_target_url(client: AsyncClient, superadmin_auth_headers: dict):
    # 1. Update draft with a CUSTOM slide where target_url is omitted or empty
    payload = {
        "slides": [
            {
                "type": "CUSTOM",
                "title": "Optional Link Slide",
                "subtitle": "Should not have target_url required",
                "image_url": "https://images.com/custom.png",
                "target_url": "",
                "is_active": True
            },
            {
                "type": "CUSTOM",
                "title": "Omitted Link Slide",
                "subtitle": "Should not have target_url required",
                "image_url": "https://images.com/custom.png",
                "is_active": True
            }
        ]
    }
    
    put_res = await client.put("/api/v1/superadmin/homepage-carousel/draft", json=payload, headers=superadmin_auth_headers)
    assert put_res.status_code == 200
    
    # 2. Publish draft
    pub_res = await client.post("/api/v1/superadmin/homepage-carousel/publish", headers=superadmin_auth_headers)
    assert pub_res.status_code == 200
    
    # 3. Fetch consolidated homepage and verify resolved slides
    hp_res = await client.get("/api/v1/public/homepage")
    assert hp_res.status_code == 200
    carousel = hp_res.json()["carousel"]
    assert len(carousel) == 2
    
    assert carousel[0]["title"] == "Optional Link Slide"
    assert carousel[0]["target_url"] is None
    
    assert carousel[1]["title"] == "Omitted Link Slide"
    assert carousel[1]["target_url"] is None

