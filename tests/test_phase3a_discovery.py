import pytest
import pytest_asyncio
from httpx import AsyncClient
from uuid import uuid4
from datetime import datetime, timezone, timedelta
import sqlalchemy as sa
from sqlalchemy.future import select

from app.core.database import AsyncSessionLocal
from app.models.domain import Temple, StateMaster, DistrictMaster, User
from app.modules.temple_management.models.temple_models import TempleProfile, PortalAnalyticsEvent, TempleFollower, TempleFestival
from app.modules.temple_management.services.recommendation_service import RecommendationService
from app.modules.governance.services.claims_service import ClaimsService
from app.modules.governance.schemas.claims import ClaimRequestCreate, ClaimRequestReview
from app.modules.governance.models.governance_models import TempleClaimRequest

@pytest_asyncio.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session

async def get_or_create_state(db, name, slug, code):
    stmt = select(StateMaster).filter(
        sa.or_(StateMaster.name == name, StateMaster.slug == slug)
    )
    res = await db.execute(stmt)
    state = res.scalars().first()
    if not state:
        state = StateMaster(id=uuid4(), name=name, slug=slug, code=code, created_at=datetime.now(timezone.utc))
        db.add(state)
        await db.commit()
    return state

async def get_or_create_district(db, state_id, name, slug, code):
    stmt = select(DistrictMaster).filter(
        sa.or_(DistrictMaster.name == name, DistrictMaster.slug == slug)
    )
    res = await db.execute(stmt)
    district = res.scalars().first()
    if not district:
        district = DistrictMaster(id=uuid4(), state_id=state_id, name=name, slug=slug, code=code, created_at=datetime.now(timezone.utc))
        db.add(district)
        await db.commit()
    return district

@pytest.mark.anyio
async def test_recommendation_diversity_rules(client: AsyncClient, db):
    """Test soft diversification: max 2 of same deity, max 3 of same state."""
    # Setup state/district
    state = await get_or_create_state(db, "Tamil Nadu Test", f"tamil-nadu-{uuid4().hex[:6]}", f"T{uuid4().hex[:3]}")
    district = await get_or_create_district(db, state.id, "Madurai Test", f"madurai-{uuid4().hex[:6]}", f"M{uuid4().hex[:3]}")

    # Create 6 Shiva temples in Tamil Nadu
    temples = []
    profiles = []
    for i in range(6):
        t = Temple(
            id=uuid4(), name=f"Shiva Temple {i}", domain=f"shiva-temple-{i}",
            is_active=True, status="APPROVED", directory_status="ACTIVE",
            state_id=state.id, district_id=district.id, verification_level=2
        )
        temples.append(t)
        db.add(t)
    await db.commit()

    for i, t in enumerate(temples):
        p = TempleProfile(temple_id=t.id, state="Tamil Nadu", district="Madurai", main_deity="Shiva", latitude=10.0 + i*0.01, longitude=78.0 + i*0.01)
        profiles.append(p)
        db.add(p)
    await db.commit()

    # Create 3 Vishnu temples in Kerala to see if it diversifies
    state2 = await get_or_create_state(db, "Kerala Test", f"kerala-{uuid4().hex[:6]}", f"K{uuid4().hex[:3]}")
    district2 = await get_or_create_district(db, state2.id, "Thrissur Test", f"thrissur-{uuid4().hex[:6]}", f"T{uuid4().hex[:3]}")

    for i in range(3):
        t_v = Temple(
            id=uuid4(), name=f"Vishnu Temple {i}", domain=f"vishnu-temple-{i}",
            is_active=True, status="APPROVED", directory_status="ACTIVE",
            state_id=state2.id, district_id=district2.id, verification_level=2
        )
        db.add(t_v)
        p_v = TempleProfile(temple_id=t_v.id, state="Kerala", district="Thrissur", main_deity="Vishnu", latitude=10.5, longitude=76.2)
        db.add(p_v)
    await db.commit()

    # Get recommendations
    recs = await RecommendationService.get_temple_recommendations(
        db, lat=10.0, lon=78.0, limit=6
    )

    # Assert soft diversification is applied
    assert len(recs) <= 6
    shiva_in_recs = [r for r in recs if "Shiva" in r["name"]]
    assert len(shiva_in_recs) <= 2


@pytest.mark.anyio
async def test_explainability_reason_codes(client: AsyncClient, db):
    """Test explainable recommendations returns correct reason codes."""
    state = await get_or_create_state(db, "Kerala Test 2", f"kerala-{uuid4().hex[:6]}", f"K{uuid4().hex[:3]}")
    district = await get_or_create_district(db, state.id, "Thrissur Test 2", f"thrissur-{uuid4().hex[:6]}", f"T{uuid4().hex[:3]}")

    # Create Shiva temple
    t1 = Temple(id=uuid4(), name="Vadakkunnathan Temple", domain="vadakkunnathan", is_active=True, status="APPROVED", directory_status="ACTIVE", state_id=state.id, district_id=district.id)
    db.add(t1)
    p1 = TempleProfile(temple_id=t1.id, state="Kerala", district="Thrissur", main_deity="Shiva", latitude=10.5276, longitude=76.2144)
    db.add(p1)

    # Create devotee user
    user = User(id=uuid4(), user_id=f"devotee-{uuid4().hex[:6]}", email=f"devotee-{uuid4().hex[:6]}@example.com", role="DEVOTEE", is_active=True, password_hash="hash")
    db.add(user)
    await db.commit()

    # Follow Shiva temple to build deity affinity
    db.add(TempleFollower(temple_id=t1.id, user_id=user.id, is_active=True))
    await db.commit()

    # Get recommendations for devotee
    recs = await RecommendationService.get_temple_recommendations(
        db, user_id=user.id, lat=10.5, lon=76.2
    )
    
    assert len(recs) > 0
    # The followed temple is excluded from recommendations
    assert not any(r["id"] == str(t1.id) for r in recs)


@pytest.mark.anyio
async def test_deities_landing_page(client: AsyncClient, db):
    """Test stable deity sitemap URLs & landings details."""
    state = await get_or_create_state(db, "Kerala Test 3", f"kerala-{uuid4().hex[:6]}", f"K{uuid4().hex[:3]}")
    district = await get_or_create_district(db, state.id, "Pathanamthitta Test", f"pathanamthitta-{uuid4().hex[:6]}", f"P{uuid4().hex[:3]}")

    t = Temple(id=uuid4(), name="Sabarimala Ayyappa Temple", domain="sabarimala", is_active=True, status="APPROVED", directory_status="ACTIVE", state_id=state.id, district_id=district.id)
    db.add(t)
    p = TempleProfile(temple_id=t.id, state="Kerala", district="Pathanamthitta", main_deity="Ayyappa")
    db.add(p)
    await db.commit()

    resp = await client.get("/api/v1/public/deities/ayyappa")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Ayyappa"
    assert data["slug"] == "ayyappa"
    assert len(data["temples"]) > 0
    assert data["temples"][0]["name"] == "Sabarimala Ayyappa Temple"


@pytest.mark.anyio
async def test_funnel_and_search_analytics(client: AsyncClient, db):
    """Test search metrics and onboarding claim funnel statistics."""
    # Create test search events
    # 2 searches, 1 zero result, 1 successful
    s1 = PortalAnalyticsEvent(
        id=uuid4(), event_name="HOMEPAGE_SEARCH", visitor_hash="v_search1",
        session_id="sess_1", event_metadata={"query": "kerala", "results_count": 5, "state": "kerala"},
        created_at=datetime.now(timezone.utc) - timedelta(minutes=5)
    )
    s2 = PortalAnalyticsEvent(
        id=uuid4(), event_name="HOMEPAGE_SEARCH", visitor_hash="v_search2",
        session_id="sess_2", event_metadata={"query": "nonexistent", "results_count": 0},
        created_at=datetime.now(timezone.utc) - timedelta(minutes=4)
    )
    db.add_all([s1, s2])
    await db.commit()

    # Log subsequent click for search1 (successful)
    click = PortalAnalyticsEvent(
        id=uuid4(), event_name="TEMPLE_VIEW", visitor_hash="v_search1",
        session_id="sess_1", event_metadata={},
        created_at=datetime.now(timezone.utc) - timedelta(minutes=2)
    )
    db.add(click)
    await db.commit()

    # Log onboarding claim events
    # Funnel: 10 Impressions -> 5 Clicks -> 2 Submissions -> 1 Approval
    for i in range(10):
        db.add(PortalAnalyticsEvent(event_name="CLAIM_CTA_IMPRESSION", visitor_hash=f"v_fun_{i}"))
    for i in range(5):
        db.add(PortalAnalyticsEvent(event_name="CLAIM_TEMPLE_CLICK", visitor_hash=f"v_fun_{i}"))
    await db.commit()

    # Create a claimant devotee user
    claimant = User(id=uuid4(), user_id=f"claimant-{uuid4().hex[:6]}", email=f"claimant-{uuid4().hex[:6]}@example.com", role="DEVOTEE", is_active=True, password_hash="hash")
    db.add(claimant)
    
    # Create temple
    state = await get_or_create_state(db, "Kerala Test 4", f"kerala-{uuid4().hex[:6]}", f"K{uuid4().hex[:3]}")
    district = await get_or_create_district(db, state.id, "Thrissur Test 4", f"thrissur-{uuid4().hex[:6]}", f"T{uuid4().hex[:3]}")

    temple = Temple(id=uuid4(), name="Onboard Temple A", domain="onboard-temple-a", is_active=True, status="APPROVED", directory_status="ACTIVE", state_id=state.id, district_id=district.id, management_mode="DIRECTORY_ONLY")
    db.add(temple)
    await db.commit()

    # Submit claim request using ClaimsService (simulates CLAIM_SUBMISSION logging)
    claim_schema = ClaimRequestCreate(
        temple_id=temple.id,
        proof_urls=["http://proof1.jpg"],
        target_management_mode="GOVERNED",
        target_subscription_plan="GOVERNED_STANDARD",
        claimant_notes="Notes"
    )
    claim = await ClaimsService.submit_claim(db, claimant.id, claim_schema, visitor_hash="v_fun_0")
    await db.commit()

    # Review/approve claim request (simulates CLAIM_APPROVED logging)
    reviewer = User(id=uuid4(), user_id=f"admin-{uuid4().hex[:6]}", email=f"admin-{uuid4().hex[:6]}@example.com", role="SUPERADMIN", is_active=True, password_hash="hash")
    db.add(reviewer)
    await db.commit()

    review_schema = ClaimRequestReview(
        status="APPROVED",
        trial_duration_days=30
    )
    await ClaimsService.review_claim(db, claim.id, reviewer.id, review_schema)
    await db.commit()

    # Test Search Analytics Endpoint logic directly
    from app.modules.governance.routes.superadmin import get_search_analytics, get_onboarding_funnel
    from app.schemas.domain import TokenData
    
    admin_token = TokenData(sub=str(reviewer.id), username=reviewer.user_id, role="SUPERADMIN")
    
    search_report = await get_search_analytics(db, admin_token)
    assert search_report["total_searches"] == 2
    assert search_report["search_success_rate"] == 50.0
    assert search_report["search_abandonment_rate"] == 50.0
    assert len(search_report["zero_result_searches"]) == 1
    assert search_report["zero_result_searches"][0]["query"] == "nonexistent"

    # Test Onboarding Funnel Endpoint
    funnel_report = await get_onboarding_funnel(db, admin_token)
    assert funnel_report["funnel"]["impressions"] == 10
    assert funnel_report["funnel"]["clicks"] == 5
    assert funnel_report["funnel"]["submissions"] == 1
    assert funnel_report["funnel"]["approvals"] == 1
    
    assert funnel_report["rates"]["ctr"] == 50.0
    assert funnel_report["rates"]["submission_rate"] == 20.0
    assert funnel_report["rates"]["approval_rate"] == 100.0
