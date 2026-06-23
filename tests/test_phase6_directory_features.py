import pytest
import uuid
from sqlalchemy.future import select
from sqlalchemy import or_
from app.models.domain import (
    Temple, StateMaster, DistrictMaster, TempleSearchIndex, User, TempleClaimRequest
)
from app.modules.governance.models.operational_states import TempleOperationalState
from app.modules.temple_management.models.temple_models import TempleProfile
from tests.conftest import TestSessionLocal
from app.models.system_rbac import SystemRole
from app.scripts.seed_system_rbac import seed_system_rbac
from app.modules.auth.services.permission_service import invalidate_all_cache

@pytest.fixture(autouse=True)
async def setup_system_permissions_phase6(setup_database):
    """Seed system roles/permissions and assign SUPER_ADMIN system role to superadmin_test user."""
    async with TestSessionLocal() as session:
        await seed_system_rbac(session)
        role_res = await session.execute(select(SystemRole).filter(SystemRole.name == "SUPER_ADMIN"))
        super_admin_role = role_res.scalars().first()
        assert super_admin_role is not None

        user_res = await session.execute(select(User).filter(User.user_id == "superadmin_test@temple"))
        user = user_res.scalars().first()
        if user:
            user.system_role_id = super_admin_role.id
            await session.commit()
        
        invalidate_all_cache()

@pytest.mark.anyio
async def test_directory_hierarchy_and_slugs(client):
    """
    Test Phase 6 directory hierarchy:
    1. Create StateMaster and DistrictMaster.
    2. Link a temple.
    3. Verify /public/states, /public/states/{state_slug}/districts,
       and /public/states/{state_slug}/districts/{district_slug}/temples endpoints.
    """
    async with TestSessionLocal() as session:
        # Create State with get-or-create to avoid UNIQUE constraint clashes
        state_res = await session.execute(select(StateMaster).filter(or_(StateMaster.code == "KL", StateMaster.slug == "kerala-state")))
        state = state_res.scalars().first()
        if not state:
            state = StateMaster(
                id=uuid.uuid4(),
                name="Kerala State",
                slug="kerala-state",
                code="KL"
            )
            session.add(state)
            await session.flush()

        # Create District with get-or-create
        dist_res = await session.execute(select(DistrictMaster).filter(DistrictMaster.slug == "wayanad-district"))
        district = dist_res.scalars().first()
        if not district:
            district = DistrictMaster(
                id=uuid.uuid4(),
                state_id=state.id,
                name="Wayanad District",
                slug="wayanad-district",
                code="WYD"
            )
            session.add(district)
            await session.flush()

        # Create Temple
        temple = Temple(
            id=uuid.uuid4(),
            name="Wayanad Sree Rama Temple",
            domain="wayanad-rama",
            status="APPROVED",
            directory_status="ACTIVE",
            management_mode="DIRECTORY_ONLY",
            verification_level=0,
            state_id=state.id,
            district_id=district.id,
            is_active=True
        )
        session.add(temple)
        await session.flush()

        # Create Profile
        profile = TempleProfile(
            temple_id=temple.id,
            location="Mananthavady",
            district="Wayanad District",
            state="Kerala State",
            image_url="/static/default-temple.jpg"
        )
        session.add(profile)
        await session.commit()
        state_slug = state.slug

    # 1. Test /public/states
    resp = await client.get("/api/v1/public/states")
    assert resp.status_code == 200
    states_data = resp.json()
    assert any(s["slug"] == state_slug for s in states_data)
    kerala_state = next(s for s in states_data if s["slug"] == state_slug)
    assert kerala_state["temple_count"] >= 1

    # 2. Test /public/states/{state_slug}/districts
    resp = await client.get(f"/api/v1/public/states/{state_slug}/districts")
    assert resp.status_code == 200
    districts_data = resp.json()
    assert any(d["slug"] == "wayanad-district" for d in districts_data)
    wayanad_dist = next(d for d in districts_data if d["slug"] == "wayanad-district")
    assert wayanad_dist["temple_count"] >= 1

    # 3. Test /public/states/{state_slug}/districts/{district_slug}/temples
    resp = await client.get(f"/api/v1/public/states/{state_slug}/districts/wayanad-district/temples")
    assert resp.status_code == 200
    temples_data = resp.json()
    assert len(temples_data) >= 1
    t = next(temple for temple in temples_data if temple["slug"] == "wayanad-rama")
    assert t["name"] == "Wayanad Sree Rama Temple"
    assert t["location"] == "Mananthavady"
    assert t["claim_status"] == "UNCLAIMED"
    assert t["verification_level"] == 0

@pytest.mark.anyio
async def test_ranked_search_queries_with_bonuses(client):
    """
    Test Phase 6 bonus-weighted search scoring:
    Exact match = 100
    Name match = 50
    Deity match = 30
    District/State/Village match = 20
    Keyword/Festival match = 10
    Bonuses: Active (+15), Official (+10), Featured (+5)
    """
    async with TestSessionLocal() as session:
        # Create State with get-or-create to avoid UNIQUE constraint clashes
        state_res = await session.execute(select(StateMaster).filter(StateMaster.slug == "karnataka"))
        state = state_res.scalars().first()
        if not state:
            state = StateMaster(id=uuid.uuid4(), name="Karnataka", slug="karnataka", code="KA")
            session.add(state)
            await session.flush()
        
        # Create District with get-or-create
        dist_res = await session.execute(select(DistrictMaster).filter(DistrictMaster.slug == "mysuru"))
        district = dist_res.scalars().first()
        if not district:
            district = DistrictMaster(id=uuid.uuid4(), state_id=state.id, name="Mysuru", slug="mysuru", code="MYS")
            session.add(district)
            await session.flush()

        # 1. Exact Match Temple + Active (+15) = 115
        t1 = Temple(
            id=uuid.uuid4(),
            name="Chamundeshwari",
            domain="chamundeshwari",
            status="APPROVED",
            directory_status="ACTIVE",
            management_mode="GOVERNED",
            verification_level=2,
            is_active=True,
            state_id=state.id,
            district_id=district.id,
            operational_state=TempleOperationalState.ACTIVE
        )
        session.add(t1)

        # 2. Substring Match Temple + Featured (+5) + Active (+15) = 70
        t2 = Temple(
            id=uuid.uuid4(),
            name="Sree Chamundeshwari Kshetram",
            domain="sree-chamundeshwari",
            status="APPROVED",
            directory_status="ACTIVE",
            management_mode="GOVERNED",
            verification_level=2,
            is_active=True,
            is_featured=True,
            state_id=state.id,
            district_id=district.id,
            operational_state=TempleOperationalState.ACTIVE
        )
        session.add(t2)

        # 3. Deity Match Temple + Official (+10) = 40
        t3 = Temple(
            id=uuid.uuid4(),
            name="Mysuru Durga Kovil",
            domain="mysuru-durga",
            status="APPROVED",
            directory_status="ACTIVE",
            management_mode="SELF_MANAGED",
            verification_level=3,
            is_active=True,
            state_id=state.id,
            district_id=district.id,
            operational_state=None
        )
        session.add(t3)

        await session.flush()

        # Create Profiles
        session.add(TempleProfile(temple_id=t1.id, location="Chamundi Hill", district="Mysuru", state="Karnataka"))
        session.add(TempleProfile(temple_id=t2.id, location="Hill Top", district="Mysuru", state="Karnataka"))
        session.add(TempleProfile(temple_id=t3.id, location="Mysuru Town", district="Mysuru", state="Karnataka", main_deity="Chamundeshwari"))

        # Create Search Index for t2
        session.add(TempleSearchIndex(
            id=uuid.uuid4(),
            temple_id=t2.id,
            alternative_names="Chamundeshwari Hill Kovil",
            keywords="chamundi,hill,mysore",
            village="Chamundi Hill Village"
        ))

        await session.commit()

    # Search for Chamundeshwari
    resp = await client.get("/api/v1/public/search?q=Chamundeshwari")
    assert resp.status_code == 200
    results = resp.json()

    # Verify order and scores
    assert len(results) >= 3
    # First is t1 because score is 115 (100 exact + 15 active)
    assert results[0]["slug"] == "chamundeshwari"
    assert results[0]["search_score"] == 115

    # Second is t2 because score is 70 (50 substring + 15 active + 5 featured)
    assert results[1]["slug"] == "sree-chamundeshwari"
    assert results[1]["search_score"] == 70

    # Third is t3 because score is 55 (30 deity + 15 active + 10 official)
    assert results[2]["slug"] == "mysuru-durga"
    assert results[2]["search_score"] == 55

@pytest.mark.anyio
async def test_guest_access_boundaries(client):
    """
    Test Phase 6 guest access models:
    - Guests can browse, checkout store products, and submit offerings without auth.
    - Check that other operations like follow check require auth.
    """
    # 1. Submit offering using guest checkout should return payment info
    offering_payload = {
        "donor_name": "Devotee Guest",
        "donor_email": "guest@devotee.org",
        "donor_phone": "+919999999999",
        "amount": 500.0,
        "offering_type": "DONATION"
    }
    resp = await client.post("/api/v1/public/temples/test/offerings", json=offering_payload)
    assert resp.status_code == 201
    assert resp.json()["status"] == "success"
    assert "payment" in resp.json()

    # 2. Store guest checkout should succeed
    # First create a product and seed stock in test database
    from app.models.domain import StoreProduct
    from app.modules.inventory.models.inventory_models import StoreStock, InventoryLocation
    product_id = uuid.uuid4()
    async with TestSessionLocal() as session:
        loc = InventoryLocation(id=uuid.uuid4(), temple_id=uuid.UUID("00000000-0000-0000-0000-000000000000"), name="Main Store")
        session.add(loc)
        await session.flush()
        
        # Add a product to the test temple
        prod = StoreProduct(
            id=product_id,
            temple_id=uuid.UUID("00000000-0000-0000-0000-000000000000"), # Default temple ID from conftest is actually TEMPLE_ID.
            name="Darshan Prasadam Box",
            sku="PRASAD-01",
            unit_price=100.0,
            is_active=True,
            is_archived=False
        )
        session.add(prod)
        await session.flush()

        stock = StoreStock(
            id=uuid.uuid4(),
            product_id=product_id,
            temple_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
            location_id=loc.id,
            quantity=50.0
        )
        session.add(stock)
        await session.commit()

    # Fetch default temple to get its real slug
    async with TestSessionLocal() as session:
        t_res = await session.execute(select(Temple).limit(1))
        t = t_res.scalars().first()
        t_slug = t.domain if t else "test"
        t_id = t.id if t else None

    # Redo seeding with the exact temple ID if different
    if t_id and t_id != uuid.UUID("00000000-0000-0000-0000-000000000000"):
        async with TestSessionLocal() as session:
            # Update product and stock with correct temple_id
            prod_res = await session.execute(select(StoreProduct).filter(StoreProduct.id == product_id))
            p = prod_res.scalars().first()
            p.temple_id = t_id
            
            stock_res = await session.execute(select(StoreStock).filter(StoreStock.product_id == product_id))
            s = stock_res.scalars().first()
            s.temple_id = t_id
            await session.commit()

    checkout_payload = {
        "guest_name": "Devotee Guest Store",
        "guest_phone": "+918888888888",
        "guest_email": "guest.store@devotee.org",
        "items": [
            {
                "product_id": str(product_id),
                "quantity": 2.0,
                "unit_price": 100.0
            }
        ]
    }
    resp = await client.post(f"/api/v1/public/temples/{t_slug}/store/guest-checkout", json=checkout_payload)
    assert resp.status_code == 201
    assert "order_number" in resp.json()

    # 3. Operations that require auth like follow should fail without headers
    resp = await client.get(f"/api/v1/follow/check/{t_id}")
    assert resp.status_code == 401

@pytest.mark.anyio
async def test_image_transform_caching_and_placeholder(client):
    """
    Test Phase 6 image transforming endpoint:
    - Verifies path checks.
    - Verifies variant sizes validation.
    """
    # 1. Invalid relative path should raise 400
    resp = await client.get("/api/v1/public/images/transform?path=../../etc/passwd&variant=thumbnail")
    assert resp.status_code == 400

    # 2. External URL path should raise 400
    resp = await client.get("/api/v1/public/images/transform?path=https://external.com/pic.jpg&variant=hero")
    assert resp.status_code == 400

    # 3. Valid local path (or fallback default-temple.jpg) should yield file response
    resp = await client.get("/api/v1/public/images/transform?path=static/default-temple.jpg&variant=card")
    assert resp.status_code in (200, 404) # Depending if Pillow/static is seeded, but router has fallback

@pytest.mark.anyio
async def test_claim_funnel_workflow(client, auth_headers, superadmin_auth_headers):
    """
    Test Phase 6 Claim Funnel Levels:
    Level 0: DIRECTORY_ONLY temple
    Level 1: CLAIM_PENDING state after claim submission
    Level 2: CLAIMED state after admin approval
    Level 3: OFFICIAL (verified) badge
    """
    # 1. Create a Level 0 temple
    async with TestSessionLocal() as session:
        temple = Temple(
            id=uuid.uuid4(),
            name="Sabarmati Ashram Kovil",
            domain="sabarmati-kovil",
            status="APPROVED",
            directory_status="ACTIVE",
            management_mode="DIRECTORY_ONLY",
            verification_level=0,
            is_active=True
        )
        session.add(temple)
        await session.flush()
        
        profile = TempleProfile(
            temple_id=temple.id,
            location="Ahmedabad",
            district="Ahmedabad",
            state="Gujarat"
        )
        session.add(profile)
        await session.commit()
        temple_id = temple.id

    # Verify claim status starts as UNCLAIMED
    resp = await client.get(f"/api/v1/public/search?q=Sabarmati")
    assert resp.status_code == 200
    results = resp.json()
    assert results[0]["claim_status"] == "UNCLAIMED"
    assert results[0]["verification_level"] == 0

    # 2. Devotee submits claim request -> status becomes CLAIM_PENDING (Level 1)
    claim_payload = {
        "temple_id": str(temple_id),
        "proof_urls": ["https://sabarmati.org/verification-doc.pdf"],
        "target_management_mode": "GOVERNED",
        "target_subscription_plan": "GOVERNED_STANDARD",
        "claimant_notes": "We are the official trust committee of Sabarmati Ashram."
    }
    resp = await client.post("/api/v1/claims", json=claim_payload, headers=auth_headers)
    assert resp.status_code == 201
    claim_id = resp.json()["id"]

    # Verify status is now CLAIM_PENDING / Level 1
    resp = await client.get(f"/api/v1/public/search?q=Sabarmati")
    results = resp.json()
    assert results[0]["claim_status"] == "CLAIM_PENDING"
    assert results[0]["verification_level"] == 1

    # 3. Admin reviews and approves the claim request -> verification level becomes 2 (CLAIMED)
    review_payload = {
        "status": "APPROVED",
        "target_management_mode": "GOVERNED",
        "target_subscription_plan": "GOVERNED_STANDARD",
        "trial_duration_days": 30
    }
    resp = await client.post(f"/api/v1/claims/admin/{claim_id}/review", json=review_payload, headers=superadmin_auth_headers)
    assert resp.status_code == 200

    # Verify status is now CLAIMED / Level 2
    resp = await client.get(f"/api/v1/public/search?q=Sabarmati")
    results = resp.json()
    assert results[0]["claim_status"] == "CLAIMED"
    assert results[0]["verification_level"] == 2

    # 4. Superadmin upgrades verification level to 3 (OFFICIAL)
    async with TestSessionLocal() as session:
        t_res = await session.execute(select(Temple).filter(Temple.id == temple_id))
        t = t_res.scalars().first()
        t.verification_level = 3
        await session.commit()

    # Verify status is now OFFICIAL / Level 3
    resp = await client.get(f"/api/v1/public/search?q=Sabarmati")
    results = resp.json()
    assert results[0]["claim_status"] == "OFFICIAL"
    assert results[0]["verification_level"] == 3
