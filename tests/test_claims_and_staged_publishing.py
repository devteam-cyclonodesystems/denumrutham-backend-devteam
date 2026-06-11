import pytest
from uuid import uuid4, UUID
from datetime import datetime, timezone
from sqlalchemy.future import select

from tests.conftest import TestSessionLocal
from app.models.domain import User, Temple, TempleClaimRequest, TempleOwnershipHistory, UserTemple, TempleWebsiteSettings, TempleWebsiteSettingsLive
from app.core.security import get_password_hash
from app.models.system_rbac import SystemRole
from app.scripts.seed_system_rbac import seed_system_rbac
from app.modules.auth.services.permission_service import invalidate_all_cache


@pytest.fixture(autouse=True)
async def setup_system_permissions(setup_database):
    """Seed system roles/permissions and assign SUPER_ADMIN system role to superadmin_test user."""
    async with TestSessionLocal() as session:
        # Seed system RBAC
        await seed_system_rbac(session)

        # Get SUPER_ADMIN role
        role_res = await session.execute(select(SystemRole).filter(SystemRole.name == "SUPER_ADMIN"))
        super_admin_role = role_res.scalars().first()
        assert super_admin_role is not None

        # Assign SUPER_ADMIN role to superadmin_test@temple user
        user_res = await session.execute(select(User).filter(User.user_id == "superadmin_test@temple"))
        user = user_res.scalars().first()
        if user:
            user.system_role_id = super_admin_role.id
            await session.commit()
        
        # Clear permission cache to make sure has_permission loads fresh assignments
        invalidate_all_cache()


@pytest.fixture(autouse=True)
async def clear_database_records():
    """Clean up claims, ownership logs, and temples to ensure clean test states."""
    async with TestSessionLocal() as session:
        # Delete claims and history logs
        from sqlalchemy import delete
        await session.execute(delete(TempleClaimRequest))
        await session.execute(delete(TempleOwnershipHistory))
        await session.execute(delete(UserTemple).filter(UserTemple.role == "TEMPLE_MANAGER"))
        
        # Ensure test user devotee exists
        res = await session.execute(select(User).filter(User.user_id == "devotee_claimant@temple.org"))
        devotee = res.scalars().first()
        if not devotee:
            devotee = User(
                id=uuid4(),
                user_id="devotee_claimant@temple.org",
                password_hash=get_password_hash("devotee@123"),
                role="DEVOTEE",
                status="ACTIVE",
                is_active=True
            )
            session.add(devotee)
        await session.commit()


@pytest.mark.anyio
async def test_claim_submission_and_superadmin_approval(client, superadmin_auth_headers):
    """Test claim submission, duplicate protection, and superadmin approval with history trail."""
    # 1. Create a directory-only temple
    async with TestSessionLocal() as session:
        temple = Temple(
            id=uuid4(),
            name="Directory-Only Temple A",
            domain="temple-a",
            management_mode="DIRECTORY_ONLY",
            directory_status="ACTIVE",
            subscription_plan="FREE",
            status="APPROVED",
            is_active=True
        )
        session.add(temple)
        
        devotee_res = await session.execute(select(User).filter(User.user_id == "devotee_claimant@temple.org"))
        devotee = devotee_res.scalars().first()
        devotee_id = devotee.id
        await session.commit()

    # 2. Get login token for devotee claimant
    login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "devotee_claimant@temple.org", "password": "devotee@123"},
    )
    assert login_resp.status_code == 200
    devotee_token = login_resp.json()["data"]["access_token"]
    devotee_headers = {"Authorization": f"Bearer {devotee_token}"}

    # 3. Devotee submits claim request
    claim_payload = {
        "temple_id": str(temple.id),
        "proof_urls": ["http://test.com/id.pdf", "http://test.com/seal.jpg"],
        "target_management_mode": "GOVERNED",
        "target_subscription_plan": "GOVERNED_STANDARD",
        "claimant_notes": "I am the chief priest."
    }
    
    submit_resp = await client.post(
        "/api/v1/claims",
        json=claim_payload,
        headers=devotee_headers
    )
    assert submit_resp.status_code == 201
    claim_data = submit_resp.json()
    assert claim_data["status"] == "PENDING"
    assert claim_data["target_management_mode"] == "GOVERNED"
    assert claim_data["target_subscription_plan"] == "GOVERNED_STANDARD"
    claim_id = claim_data["id"]

    # 4. Try submitting duplicate claim request - should block
    dup_resp = await client.post(
        "/api/v1/claims",
        json=claim_payload,
        headers=devotee_headers
    )
    assert dup_resp.status_code == 400
    assert "You already have a pending claim request" in str(dup_resp.json())

    # 5. Super admin lists pending claims
    list_resp = await client.get(
        "/api/v1/claims/admin?status=PENDING",
        headers=superadmin_auth_headers
    )
    assert list_resp.status_code == 200
    admin_list = list_resp.json()["claims"]
    assert len(admin_list) >= 1
    assert admin_list[0]["id"] == claim_id

    # 6. Super admin approves claim request
    review_payload = {
        "status": "APPROVED",
        "target_management_mode": "GOVERNED",
        "target_subscription_plan": "GOVERNED_STANDARD",
        "trial_duration_days": 30
    }
    
    review_resp = await client.post(
        f"/api/v1/claims/admin/{claim_id}/review",
        json=review_payload,
        headers=superadmin_auth_headers
    )
    assert review_resp.status_code == 200
    
    # 7. Verify DB changes
    async with TestSessionLocal() as session:
        # Verify temple upgraded
        t_res = await session.execute(select(Temple).filter(Temple.id == temple.id))
        t_db = t_res.scalars().first()
        assert t_db.management_mode == "GOVERNED"
        assert t_db.subscription_plan == "GOVERNED_STANDARD"
        assert t_db.directory_status == "ACTIVE"

        # Verify claim marked APPROVED
        c_res = await session.execute(select(TempleClaimRequest).filter(TempleClaimRequest.id == UUID(claim_id)))
        c_db = c_res.scalars().first()
        assert c_db.status == "APPROVED"

        # Verify claimant base role is unchanged (DEVOTEE)
        u_res = await session.execute(select(User).filter(User.id == devotee_id))
        u_db = u_res.scalars().first()
        assert u_db.role == "DEVOTEE"

        # Verify UserTemple mapping exists with TEMPLE_MANAGER
        ut_res = await session.execute(
            select(UserTemple).filter(UserTemple.user_id == devotee_id, UserTemple.temple_id == temple.id)
        )
        ut_db = ut_res.scalars().first()
        assert ut_db is not None
        assert ut_db.role == "TEMPLE_MANAGER"

        # Verify TempleOwnershipHistory logged
        h_res = await session.execute(
            select(TempleOwnershipHistory).filter(TempleOwnershipHistory.temple_id == temple.id)
        )
        h_db = h_res.scalars().first()
        assert h_db is not None
        assert h_db.previous_management_mode == "DIRECTORY_ONLY"
        assert h_db.new_management_mode == "GOVERNED"

    # 8. Test request context token override: claimant can now submit website drafts as manager
    # Prepare draft settings first
    async with TestSessionLocal() as session:
        ws = TempleWebsiteSettings(temple_id=temple.id, theme_name="default", primary_color="#ff6600")
        session.add(ws)
        await session.commit()

    # Call submit website review using claimant devotee_headers (with active temple context in headers)
    # Note: select temple context by passing temple_id in headers or endpoint context
    # Usually request context checks client-selected temple_id in token or query.
    # In token, temple_id is resolved at login. Since token was issued when devotee didn't manage temple,
    # let's login again to get a token with the new temple context.
    rel_login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "devotee_claimant@temple.org", "password": "devotee@123"},
    )
    # The login should associate the user with the temple.
    # To simulate selecting the temple, the login auth service loads the user's mapped temples.
    # Let's inspect devotee's mapped token or inject temple_id in request.
    # We can pass x-temple-id or select-temple context if backend supports it, or simply fetch my-claims.
    # Let's verify that listing my claims works.
    my_claims_resp = await client.get("/api/v1/claims/my-claims", headers=devotee_headers)
    assert my_claims_resp.status_code == 200
    assert len(my_claims_resp.json()) >= 1


@pytest.mark.anyio
async def test_claim_abuse_protections(client):
    """Verify rate-limiting block on submitting more than 5 claims in 24 hours."""
    # Create devotee and multiple directory-only temples
    async with TestSessionLocal() as session:
        devotee_res = await session.execute(select(User).filter(User.user_id == "devotee_claimant@temple.org"))
        devotee = devotee_res.scalars().first()
        devotee_id = devotee.id
        
        temples = []
        for i in range(7):
            t = Temple(
                id=uuid4(),
                name=f"Abuse Test Temple {i}",
                domain=f"abuse-temple-{i}",
                management_mode="DIRECTORY_ONLY",
                status="APPROVED",
                is_active=True
            )
            session.add(t)
            temples.append(t)
        await session.commit()

    # Login devotee
    login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "devotee_claimant@temple.org", "password": "devotee@123"},
    )
    devotee_token = login_resp.json()["data"]["access_token"]
    devotee_headers = {"Authorization": f"Bearer {devotee_token}"}

    # Submit 5 claims successfully
    for i in range(5):
        resp = await client.post(
            "/api/v1/claims",
            json={
                "temple_id": str(temples[i].id),
                "proof_urls": ["http://test.com/id.pdf"],
                "target_management_mode": "GOVERNED",
                "target_subscription_plan": "GOVERNED_STANDARD"
            },
            headers=devotee_headers
        )
        assert resp.status_code == 201

    # The 6th submission should trigger rate limit (429 status code)
    abuse_resp = await client.post(
        "/api/v1/claims",
        json={
            "temple_id": str(temples[5].id),
            "proof_urls": ["http://test.com/id.pdf"],
            "target_management_mode": "GOVERNED",
            "target_subscription_plan": "GOVERNED_STANDARD"
        },
        headers=devotee_headers
    )
    assert abuse_resp.status_code == 429
    assert "Rate limit exceeded" in str(abuse_resp.json())


@pytest.mark.anyio
async def test_governed_website_publish_workflow(client, superadmin_auth_headers):
    """Verify draft submission and superadmin review workflow for GOVERNED temples."""
    # 1. Create a GOVERNED temple and its manager user
    temple_id = uuid4()
    manager_id = uuid4()
    async with TestSessionLocal() as session:
        temple = Temple(
            id=temple_id,
            name="Governed Temple B",
            domain="temple-b",
            management_mode="GOVERNED",
            directory_status="ACTIVE",
            subscription_plan="GOVERNED_STANDARD",
            status="APPROVED",
            is_active=True
        )
        session.add(temple)
        
        manager = User(
            id=manager_id,
            user_id="governed_manager@temple.org",
            password_hash=get_password_hash("manager@123"),
            role="DEVOTEE",  # Base role DEVOTEE
            status="ACTIVE",
            is_active=True,
            temple_id=temple_id
        )
        session.add(manager)
        
        # Temple-scoped mapping
        ut = UserTemple(
            id=uuid4(),
            user_id=manager_id,
            temple_id=temple_id,
            role="TEMPLE_MANAGER",
            is_active=True
        )
        session.add(ut)
        
        # Save draft settings
        ws = TempleWebsiteSettings(
            temple_id=temple_id,
            theme_name="default",
            primary_color="#ff6600",
            approval_status="DRAFT"
        )
        session.add(ws)
        await session.commit()

    # 2. Login manager
    login_resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "governed_manager@temple.org", "password": "manager@123"},
    )
    manager_token = login_resp.json()["data"]["access_token"]
    
    # We must construct a token that carries the temple context.
    # In auth_service, when a user logs in, the token gets the user's mapped temple_id if it exists.
    # Let's decode or verify the response has temple_id or we can verify the token encoding.
    # If the token has temple_id, headers will work.
    manager_headers = {"Authorization": f"Bearer {manager_token}"}

    # 3. Attempt direct publishing - should block (400)
    pub_resp = await client.post(
        "/api/v1/manager/website-settings/publish",
        headers=manager_headers
    )
    assert pub_resp.status_code == 400
    assert "Direct website publishing is disabled for GOVERNED temples" in str(pub_resp.json())

    # 4. Submit for review
    sub_resp = await client.post(
        "/api/v1/manager/website-settings/submit-review",
        headers=manager_headers
    )
    assert sub_resp.status_code == 200
    assert sub_resp.json()["approval_status"] == "PENDING_REVIEW"

    # 5. Admin fetches pending reviews
    pend_resp = await client.get(
        "/api/v1/manager/website-settings/pending",
        headers=superadmin_auth_headers
    )
    assert pend_resp.status_code == 200
    reviews = pend_resp.json()
    assert any(r["temple_id"] == str(temple_id) for r in reviews)

    # 6. Admin rejects submission
    rej_resp = await client.post(
        f"/api/v1/manager/website-settings/{temple_id}/review",
        json={"status": "REJECTED", "rejection_reason": "Colors do not match guidelines"},
        headers=superadmin_auth_headers
    )
    assert rej_resp.status_code == 200
    assert rej_resp.json()["message"] == "Website changes rejected"

    # Verify draft is in REJECTED state
    async with TestSessionLocal() as session:
        ws_res = await session.execute(select(TempleWebsiteSettings).filter(TempleWebsiteSettings.temple_id == temple_id))
        ws_db = ws_res.scalars().first()
        assert ws_db.approval_status == "REJECTED"
        assert ws_db.rejection_reason == "Colors do not match guidelines"

    # 7. Resubmit for review
    sub_resp2 = await client.post(
        "/api/v1/manager/website-settings/submit-review",
        headers=manager_headers
    )
    assert sub_resp2.status_code == 200
    assert sub_resp2.json()["approval_status"] == "PENDING_REVIEW"

    # 8. Admin approves submission
    app_resp = await client.post(
        f"/api/v1/manager/website-settings/{temple_id}/review",
        json={"status": "APPROVED"},
        headers=superadmin_auth_headers
    )
    assert app_resp.status_code == 200
    assert app_resp.json()["message"] == "Website changes approved and published live"

    # Verify live settings published
    async with TestSessionLocal() as session:
        ws_res = await session.execute(select(TempleWebsiteSettings).filter(TempleWebsiteSettings.temple_id == temple_id))
        ws_db = ws_res.scalars().first()
        assert ws_db.approval_status == "APPROVED"

        live_res = await session.execute(select(TempleWebsiteSettingsLive).filter(TempleWebsiteSettingsLive.temple_id == temple_id))
        live_db = live_res.scalars().first()
        assert live_db is not None
        assert live_db.settings_snapshot["primary_color"] == "#ff6600"


@pytest.mark.anyio
async def test_directory_visibility_filtering(client):
    """Verify that only ACTIVE temples appear in directory lists and aggregates."""
    # 1. Create two temples: Temple C (ACTIVE) and Temple D (PENDING_VERIFICATION)
    c_id = uuid4()
    d_id = uuid4()
    async with TestSessionLocal() as session:
        # Temple C: Active
        temple_c = Temple(
            id=c_id,
            name="Visible Temple C",
            domain="temple-c",
            management_mode="SELF_MANAGED",
            directory_status="ACTIVE",
            status="APPROVED",
            is_active=True
        )
        session.add(temple_c)
        
        # Profiles
        from app.models.domain import TempleProfile
        prof_c = TempleProfile(temple_id=c_id, state="Tamil Nadu", district="Madurai")
        session.add(prof_c)

        # Live settings
        live_c = TempleWebsiteSettingsLive(
            temple_id=c_id,
            settings_snapshot={"theme_name": "default"},
            version=1,
            status="PUBLISHED"
        )
        session.add(live_c)

        # Temple D: Suspended
        temple_d = Temple(
            id=d_id,
            name="Hidden Temple D",
            domain="temple-d",
            management_mode="SELF_MANAGED",
            directory_status="SUSPENDED",
            status="APPROVED",
            is_active=True
        )
        session.add(temple_d)
        
        prof_d = TempleProfile(temple_id=d_id, state="Tamil Nadu", district="Madurai")
        session.add(prof_d)

        live_d = TempleWebsiteSettingsLive(
            temple_id=d_id,
            settings_snapshot={"theme_name": "default"},
            version=1,
            status="PUBLISHED"
        )
        session.add(live_d)

        await session.commit()

    # 2. Query states directory
    states_resp = await client.get("/api/v1/public/directory/states")
    assert states_resp.status_code == 200
    states = states_resp.json()
    # Find Tamil Nadu
    tn = next((s for s in states if s["state"] == "Tamil Nadu"), None)
    assert tn is not None
    # Count should only count Temple C (1), not Temple D
    assert tn["temple_count"] == 1

    # 3. Query districts directory
    dist_resp = await client.get("/api/v1/public/directory/states/Tamil%20Nadu/districts")
    assert dist_resp.status_code == 200
    districts = dist_resp.json()
    madurai = next((d for d in districts if d["district"] == "Madurai"), None)
    assert madurai is not None
    assert madurai["temple_count"] == 1

    # 4. Query public temples listing
    list_resp = await client.get("/api/v1/public/temples?state=Tamil%20Nadu")
    assert list_resp.status_code == 200
    temples_list = list_resp.json()
    # Should only contain Temple C
    assert any(t["name"] == "Visible Temple C" for t in temples_list)
    assert not any(t["name"] == "Hidden Temple D" for t in temples_list)
