import pytest
from uuid import uuid4
from sqlalchemy.future import select
from app.models.domain import User, TempleLead
from app.models.system_rbac import SystemRole
from app.scripts.seed_system_rbac import seed_system_rbac
from app.modules.auth.services.permission_service import invalidate_all_cache

@pytest.fixture(autouse=True)
async def setup_system_permissions(setup_database):
    """Seed system roles/permissions and assign SUPER_ADMIN system role to superadmin_test user."""
    from tests.conftest import TestSessionLocal
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

@pytest.mark.anyio
async def test_crm_leads_permissions_guard(client, auth_headers, superadmin_auth_headers):
    """Verify that only users with MANAGE_LEADS permission can access CRM leads."""
    # 1. Non-admin or regular temple admin user (auth_headers) should get 403
    resp = await client.get("/api/v1/admin/leads", headers=auth_headers)
    assert resp.status_code == 403

    # 2. Super admin (superadmin_auth_headers) has SUPER_ADMIN system role (so has MANAGE_LEADS) and should get 200
    resp = await client.get("/api/v1/admin/leads", headers=superadmin_auth_headers)
    assert resp.status_code == 200
    assert "leads" in resp.json()

@pytest.mark.anyio
async def test_crm_leads_crud_lifecycle(client, superadmin_auth_headers):
    """Test full CRUD lifecycle of a temple lead."""
    # 1. Create a lead
    lead_payload = {
        "temple_name": "Test Sabarimala Branch",
        "contact_person": "Adithya Varma",
        "phone": "+919876543210",
        "email": "adithya@sabarimala.org",
        "state": "Kerala",
        "district": "Pathanamthitta",
        "interested_plan": "SELF_MANAGED_PRO",
        "lead_source": "Website Campaign",
        "notes": "Interested in direct pooja publishing and booking splits."
    }

    create_resp = await client.post(
        "/api/v1/admin/leads",
        json=lead_payload,
        headers=superadmin_auth_headers
    )
    assert create_resp.status_code == 201
    lead_data = create_resp.json()
    assert lead_data["temple_name"] == "Test Sabarimala Branch"
    assert lead_data["status"] == "NEW"
    lead_id = lead_data["id"]

    # 2. Get lead detail
    detail_resp = await client.get(
        f"/api/v1/admin/leads/{lead_id}",
        headers=superadmin_auth_headers
    )
    assert detail_resp.status_code == 200
    assert detail_resp.json()["contact_person"] == "Adithya Varma"

    # 3. Update lead (transition status to CONTACTED)
    update_payload = {
        "status": "CONTACTED",
        "notes": "Followed up via phone. Scheduled demo."
    }
    update_resp = await client.put(
        f"/api/v1/admin/leads/{lead_id}",
        json=update_payload,
        headers=superadmin_auth_headers
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["status"] == "CONTACTED"
    assert updated["notes"] == "Followed up via phone. Scheduled demo."

    # 4. List leads (filtering by status)
    list_resp = await client.get(
        "/api/v1/admin/leads?status=CONTACTED",
        headers=superadmin_auth_headers
    )
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data["total"] >= 1
    assert list_data["leads"][0]["id"] == lead_id

    # 5. Delete lead
    delete_resp = await client.delete(
        f"/api/v1/admin/leads/{lead_id}",
        headers=superadmin_auth_headers
    )
    assert delete_resp.status_code == 204

    # 6. Verify lead is gone
    get_gone_resp = await client.get(
        f"/api/v1/admin/leads/{lead_id}",
        headers=superadmin_auth_headers
    )
    assert get_gone_resp.status_code == 404


@pytest.mark.anyio
async def test_governed_mode_cannot_publish_directly(client, auth_headers):
    """Confirm that direct website publishing is blocked for GOVERNED temples."""
    from tests.conftest import TestSessionLocal, TEMPLE_ID
    from app.models.domain import Temple, TempleWebsiteSettings

    async with TestSessionLocal() as session:
        # 1. Update temple to GOVERNED mode
        res = await session.execute(select(Temple).filter(Temple.id == TEMPLE_ID))
        temple = res.scalars().first()
        assert temple is not None
        temple.management_mode = "GOVERNED"

        # 2. Make sure draft website settings exist
        ws_res = await session.execute(select(TempleWebsiteSettings).filter(TempleWebsiteSettings.temple_id == TEMPLE_ID))
        ws = ws_res.scalars().first()
        if not ws:
            ws = TempleWebsiteSettings(temple_id=TEMPLE_ID, theme_name="default", primary_color="#ff6600")
            session.add(ws)
        
        await session.commit()

    # 3. Call direct publish endpoint - should return 400 Bad Request
    resp = await client.post(
        "/api/v1/manager/website-settings/publish",
        headers=auth_headers
    )
    assert resp.status_code == 400
    assert "Direct website publishing is disabled for GOVERNED temples" in str(resp.json())

    # 4. Clean up (reset to SELF_MANAGED)
    async with TestSessionLocal() as session:
        res = await session.execute(select(Temple).filter(Temple.id == TEMPLE_ID))
        temple = res.scalars().first()
        temple.management_mode = "SELF_MANAGED"
        await session.commit()


@pytest.mark.anyio
async def test_convert_lead_to_temple_workflow(client, superadmin_auth_headers):
    """Confirm CRM Lead conversion registers a temple and creates manager user and ownership history."""
    from tests.conftest import TestSessionLocal
    from app.models.domain import TempleLead, Temple, User, TempleOwnershipHistory

    # 1. Create a lead to convert
    async with TestSessionLocal() as session:
        lead = TempleLead(
            id=uuid4(),
            temple_name="Sree Padmanabha CRM Lead",
            contact_person="Marthanda Varma",
            phone="+919446000111",
            email="padmanabha@lead.org",
            state="Kerala",
            district="Trivandrum",
            interested_plan="SELF_MANAGED_PRO",
            status="NEW"
        )
        session.add(lead)
        await session.commit()
        lead_id = lead.id

    # 2. Call conversion endpoint
    convert_payload = {
        "domain": "padmanabha-crm-converted",
        "manager_password": "PadmanabhaPass@2026"
    }
    
    resp = await client.post(
        f"/api/v1/admin/leads/{lead_id}/convert",
        json=convert_payload,
        headers=superadmin_auth_headers
    )
    assert resp.status_code == 200
    res_data = resp.json()["data"]
    assert res_data["temple_name"] == "Sree Padmanabha CRM Lead"
    assert res_data["domain"] == "padmanabha-crm-converted"
    assert res_data["manager_email"] == "padmanabha@lead.org"

    # 3. Verify database states
    async with TestSessionLocal() as session:
        # Check temple exists
        t_res = await session.execute(select(Temple).filter(Temple.domain == "padmanabha-crm-converted"))
        temple = t_res.scalars().first()
        assert temple is not None
        assert temple.management_mode == "SELF_MANAGED"
        assert temple.subscription_plan == "SELF_MANAGED_PRO"

        # Check manager exists
        u_res = await session.execute(select(User).filter(User.email == "padmanabha@lead.org"))
        manager = u_res.scalars().first()
        assert manager is not None
        assert manager.temple_id == temple.id

        # Check ownership history is logged
        h_res = await session.execute(select(TempleOwnershipHistory).filter(TempleOwnershipHistory.temple_id == temple.id))
        history = h_res.scalars().first()
        assert history is not None
        assert history.new_management_mode == "SELF_MANAGED"
        assert history.new_subscription_plan == "SELF_MANAGED_PRO"
        assert "CRM Lead conversion" in history.reason

        # Check lead is marked CONVERTED
        l_res = await session.execute(select(TempleLead).filter(TempleLead.id == lead_id))
        lead_db = l_res.scalars().first()
        assert lead_db.status == "CONVERTED"
