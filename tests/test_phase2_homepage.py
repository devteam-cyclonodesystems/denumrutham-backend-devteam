import pytest
import pytest_asyncio
from httpx import AsyncClient
from uuid import uuid4
from datetime import datetime, timezone
import sqlalchemy as sa
from sqlalchemy.future import select
from app.core.database import AsyncSessionLocal
from app.models.domain import Temple, StateMaster, DistrictMaster
from app.modules.temple_management.models.temple_models import TempleProfile, PortalAnalyticsEvent, TempleFollower, TempleFestival
from app.modules.temple_management.services.homepage_service import HomepageService

@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session

@pytest.mark.anyio
async def test_trending_engine_scores(client: AsyncClient, db):
    # Setup test data
    # Create State and District
    state = StateMaster(id=uuid4(), name="Test State", slug="test-state", code="TS", created_at=datetime.now(timezone.utc))
    district = DistrictMaster(id=uuid4(), state_id=state.id, name="Test District", slug="test-district", code="TD", created_at=datetime.now(timezone.utc))
    db.add(state)
    db.add(district)
    await db.commit()

    # Create Temples
    temple1 = Temple(
        id=uuid4(), name="Golden Temple A", domain="trending-temple-a", is_active=True, status="APPROVED",
        directory_status="ACTIVE", state_id=state.id, district_id=district.id, verification_level=3, is_featured=True
    )
    temple2 = Temple(
        id=uuid4(), name="Golden Temple B", domain="trending-temple-b", is_active=True, status="APPROVED",
        directory_status="ACTIVE", state_id=state.id, district_id=district.id, verification_level=2, is_featured=False
    )
    db.add(temple1)
    db.add(temple2)
    await db.commit()

    # Add profiles
    profile1 = TempleProfile(temple_id=temple1.id, location="Loc A", state="Test State", district="Test District", main_deity="Shiva")
    profile2 = TempleProfile(temple_id=temple2.id, location="Loc B", state="Test State", district="Test District", main_deity="Vishnu")
    db.add(profile1)
    db.add(profile2)
    await db.commit()

    # Log views and searches
    # Temple 1: 5 views, 2 searches
    # Temple 2: 1 view, 0 searches
    for _ in range(5):
        db.add(PortalAnalyticsEvent(temple_id=temple1.id, event_name="TEMPLE_VIEW", visitor_hash="v1"))
    for _ in range(2):
        db.add(PortalAnalyticsEvent(temple_id=temple1.id, event_name="TEMPLE_CARD_CLICK", visitor_hash="v1"))
    
    db.add(PortalAnalyticsEvent(temple_id=temple2.id, event_name="TEMPLE_VIEW", visitor_hash="v1"))
    await db.commit()

    # Followers
    # Temple 1: 1 follower
    db.add(TempleFollower(temple_id=temple1.id, user_id=uuid4(), is_active=True))
    await db.commit()

    # 1. Fetch bulk followers map
    followers_map = {temple1.id: 1, temple2.id: 0}

    # 2. Test scores calculation
    scores = await HomepageService.calculate_trending_scores(db, followers_map)
    
    assert temple1.id in scores
    assert temple2.id in scores
    # Temple 1 should have maximum views/searches/followers, scoring it highly
    assert scores[temple1.id] > scores[temple2.id]
    
    # 3. Test consolidated homepage endpoint
    response = await client.get("/api/v1/public/homepage")
    assert response.status_code == 200
    data = response.json()
    assert "featured" in data
    assert "trending" in data
    assert "recently_added" in data
    assert "upcoming_festivals" in data
    assert "spotlight" in data


@pytest.mark.anyio
async def test_nearby_temples_api(client: AsyncClient, db):
    # Setup state/district
    # Setup state/district with get-or-create to avoid UNIQUE constraint clashes
    state_res = await db.execute(select(StateMaster).filter(StateMaster.slug == "karnataka"))
    state = state_res.scalars().first()
    if not state:
        state = StateMaster(id=uuid4(), name="Karnataka", slug="karnataka", code="KA", created_at=datetime.now(timezone.utc))
        db.add(state)
        await db.commit()
    
    dist_res = await db.execute(select(DistrictMaster).filter(DistrictMaster.slug == "bangalore"))
    district = dist_res.scalars().first()
    if not district:
        district = DistrictMaster(id=uuid4(), state_id=state.id, name="Bangalore", slug="bangalore", code="BLR", created_at=datetime.now(timezone.utc))
        db.add(district)
        await db.commit()

    # Create Temples
    # Temple 1: Bangalore center (12.9716, 77.5946)
    # Temple 2: Mysore (~140km away: 12.2958, 76.6394)
    # Temple 3: Chennai (~350km away: 13.0827, 80.2707)
    t1 = Temple(id=uuid4(), name="Bangalore Temple", domain="blr-temple", is_active=True, status="APPROVED", directory_status="ACTIVE", state_id=state.id, district_id=district.id)
    t2 = Temple(id=uuid4(), name="Mysore Temple", domain="mys-temple", is_active=True, status="APPROVED", directory_status="ACTIVE", state_id=state.id, district_id=district.id)
    t3 = Temple(id=uuid4(), name="Chennai Temple", domain="chn-temple", is_active=True, status="APPROVED", directory_status="ACTIVE", state_id=state.id, district_id=district.id)
    db.add_all([t1, t2, t3])
    await db.commit()

    db.add(TempleProfile(temple_id=t1.id, state="Karnataka", district="Bangalore", latitude=12.9716, longitude=77.5946))
    db.add(TempleProfile(temple_id=t2.id, state="Karnataka", district="Mysore", latitude=12.2958, longitude=76.6394))
    db.add(TempleProfile(temple_id=t3.id, state="Tamil Nadu", district="Chennai", latitude=13.0827, longitude=80.2707))
    await db.commit()

    # Query from Bangalore (12.97, 77.59) with radius 150km
    resp = await client.get("/api/v1/public/nearby-temples?latitude=12.9716&longitude=77.5946&radius=150")
    assert resp.status_code == 200
    results = resp.json()
    
    # Should find Bangalore and Mysore, but not Chennai
    assert len(results) == 2
    assert results[0]["name"] == "Bangalore Temple"
    assert results[1]["name"] == "Mysore Temple"
    assert results[0]["distance"] < results[1]["distance"]

    # Check bounds validation
    bad_resp = await client.get("/api/v1/public/nearby-temples?latitude=95.0&longitude=77.5946")
    assert bad_resp.status_code == 400


@pytest.mark.anyio
async def test_search_suggestions_api(client: AsyncClient, db):
    # Setup state/district
    # Setup state/district with get-or-create to avoid UNIQUE constraint clashes
    state_res = await db.execute(select(StateMaster).filter(sa.or_(StateMaster.code == "KL", StateMaster.slug == "kerala")))
    state = state_res.scalars().first()
    if not state:
        state = StateMaster(id=uuid4(), name="Kerala", slug="kerala", code="KL", created_at=datetime.now(timezone.utc))
        db.add(state)
        await db.commit()
    
    dist_res = await db.execute(select(DistrictMaster).filter(DistrictMaster.slug == "thrissur"))
    district = dist_res.scalars().first()
    if not district:
        district = DistrictMaster(id=uuid4(), state_id=state.id, name="Thrissur", slug="thrissur", code="TCR", created_at=datetime.now(timezone.utc))
        db.add(district)
        await db.commit()

    # Create temples and festivals
    t1 = Temple(id=uuid4(), name="Sabarimala Sree Ayyappa Temple", domain="sabarimala", is_active=True, status="APPROVED", directory_status="ACTIVE", state_id=state.id, district_id=district.id)
    t2 = Temple(id=uuid4(), name="Guruvayur Temple", domain="guruvayur", is_active=True, status="APPROVED", directory_status="ACTIVE", state_id=state.id, district_id=district.id)
    db.add_all([t1, t2])
    await db.commit()

    db.add(TempleProfile(temple_id=t1.id, state="Kerala", district="Pathanamthitta", main_deity="Ayyappa"))
    db.add(TempleProfile(temple_id=t2.id, state="Kerala", district="Thrissur", main_deity="Krishna"))

    db.add(TempleFestival(temple_id=t1.id, name="Makaravilakku", start_date=datetime.now(timezone.utc).date(), end_date=datetime.now(timezone.utc).date()))
    await db.commit()

    # 1. Search for Sabarimala
    resp = await client.get("/api/v1/public/search/suggest?q=Sabarimala")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["type"] == "TEMPLE"
    assert "Sabarimala" in data[0]["value"]

    # 2. Search deity "Ayyappa"
    resp = await client.get("/api/v1/public/search/suggest?q=Ayyappa")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["type"] == "DEITY"

    # 3. Search state "Kerala"
    resp = await client.get("/api/v1/public/search/suggest?q=Keral")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["type"] == "STATE"
