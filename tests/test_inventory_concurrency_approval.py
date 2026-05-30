import pytest
import pytest_asyncio
from httpx import AsyncClient
from uuid import UUID
from app.core.database import AsyncSessionLocal
from app.models.domain import InventoryItem, Supplier, PriceApprovalRequest, AuditLog, Notification, SupplierPriceHistory
from sqlalchemy.future import select

@pytest_asyncio.fixture
async def secondary_manager_headers(client: AsyncClient):
    from app.core.security import get_password_hash
    from app.models.domain import User
    from app.models.rbac import Role, UserRole
    from tests.conftest import TestSessionLocal, TEMPLE_ID
    
    async with TestSessionLocal() as session:
        res = await session.execute(select(User).filter(User.user_id == "manager2@temple"))
        manager2 = res.scalars().first()
        if not manager2:
            manager2 = User(
                user_id="manager2@temple",
                password_hash=get_password_hash("manager@123"),
                role="TEMPLE_MANAGER",
                temple_id=TEMPLE_ID,
            )
            session.add(manager2)
            await session.flush()
            
            role_res = await session.execute(
                select(Role).filter(Role.temple_id == TEMPLE_ID, Role.name == "Manager")
            )
            manager_role = role_res.scalars().first()
            if manager_role:
                ur = UserRole(
                    user_id=manager2.id,
                    role_id=manager_role.id,
                    temple_id=TEMPLE_ID
                )
                session.add(ur)
            await session.commit()

    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "manager2@temple", "password": "manager@123"},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}

@pytest.mark.asyncio
async def test_manual_price_update_concurrency(client: AsyncClient, auth_headers, secondary_manager_headers):
    # 1. Create inventory item
    item_resp = await client.post(
        "/api/v1/inventory/items",
        json={
            "name": "Test Concurrency Item",
            "category": "Ritual Supplies",
            "unit": "piece",
            "qty": 100,
            "min_stock": 10,
            "unit_price": 10.0,
            "remarks": "Concurrency Test"
        },
        headers=auth_headers,
    )
    assert item_resp.status_code == 200
    item_data = item_resp.json()
    item_id = item_data["id"]
    
    # Check that default version is 1 or None (which maps to 1 on update)
    
    # 2. Perform first update with correct version
    update_resp1 = await client.patch(
        f"/api/v1/inventory/items/{item_id}",
        json={
            "unit_price": 12.0,
            "version": 1
        },
        headers=auth_headers,
    )
    assert update_resp1.status_code == 200
    
    # 3. Perform second update using stale version (1)
    update_resp2 = await client.patch(
        f"/api/v1/inventory/items/{item_id}",
        json={
            "unit_price": 15.0,
            "version": 1
        },
        headers=auth_headers,
    )
    assert update_resp2.status_code == 409
    res_json = update_resp2.json()
    err_msg = res_json.get("detail") or res_json.get("error", {}).get("message", "")
    assert "was modified by another user" in err_msg

    # 4. Perform third update using correct version (2)
    update_resp3 = await client.patch(
        f"/api/v1/inventory/items/{item_id}",
        json={
            "unit_price": 15.0,
            "version": 2
        },
        headers=auth_headers,
    )
    assert update_resp3.status_code == 200
    
    # Since manual price updates require approval, active price remains 10.0
    items_resp = await client.get("/api/v1/inventory/items", headers=auth_headers)
    item_active = next(itm for itm in items_resp.json() if itm["id"] == item_id)
    assert item_active["unit_price"] == 10.0
    
    # Approve the 15.0 price change request using secondary manager headers
    approvals_resp = await client.get("/api/v1/inventory/price-approvals", headers=auth_headers)
    assert approvals_resp.status_code == 200
    approvals = approvals_resp.json()
    item_app = next(app for app in approvals if app["inventory_item_id"] == item_id and app["new_price"] == 15.0)
    
    approve_resp = await client.post(
        f"/api/v1/inventory/price-approvals/{item_app['id']}/approve",
        headers=secondary_manager_headers
    )
    assert approve_resp.status_code == 200
    
    # Verify inventory price is now 15.0
    items_resp = await client.get("/api/v1/inventory/items", headers=auth_headers)
    item_active = next(itm for itm in items_resp.json() if itm["id"] == item_id)
    assert item_active["unit_price"] == 15.0


@pytest.mark.asyncio
async def test_supplier_price_sync_auto_approvals(client: AsyncClient, auth_headers, secondary_manager_headers):
    # Debug: Print existing price approval requests
    from tests.conftest import TestSessionLocal
    from sqlalchemy import text
    async with TestSessionLocal() as session:
        res = await session.execute(text("SELECT * FROM price_approval_requests"))
        rows = res.fetchall()
        print("DEBUG PRE-TEST ROWS COUNT:", len(rows))
        for r in rows:
            print("  PRE-TEST ROW:", r._mapping)
            for k, v in r._mapping.items():
                print(f"    {k}: {v} (type: {type(v)})")

    # 1. Register a supplier with sugar
    sup_resp = await client.post(
        "/api/v1/inventory/suppliers",
        json={
            "name": "Auto Approved Supplier Ltd",
            "contact": "1234567890",
            "items_supplied": "Sugar (KG) @ ₹50 [Min: 10]"
        },
        headers=auth_headers,
    )
    assert sup_resp.status_code == 200
    supplier_id = sup_resp.json()["id"]

    # Retrieve the automatically created item - initial price should be 0.0 (pending approval)
    items_resp = await client.get("/api/v1/inventory/items", headers=auth_headers)
    items = items_resp.json()
    sugar_item = next(itm for itm in items if itm["name"].lower() == "sugar")
    assert sugar_item["unit_price"] == 0.0

    # Retrieve the pending price approval for initial setup
    try:
        approvals_resp = await client.get("/api/v1/inventory/price-approvals", headers=auth_headers)
        approvals = approvals_resp.json()
    except Exception as e:
        print("EXCEPTION ENCOUNTERED:", e)
        import traceback
        traceback.print_exc()
        # Query database directly to see raw data
        from tests.conftest import TestSessionLocal
        from sqlalchemy import text
        async with TestSessionLocal() as session:
            res = await session.execute(text("SELECT * FROM price_approval_requests"))
            for r in res.fetchall():
                print("RAW ROW:", r._mapping)
                for k, v in r._mapping.items():
                    print(f"  {k}: {v} (type: {type(v)})")
        raise e
    sugar_app = next(app for app in approvals if app["item_name"].lower() == "sugar" and app["new_price"] == 50.0)
    
    # Approve the initial price request
    approve_resp = await client.post(
        f"/api/v1/inventory/price-approvals/{sugar_app['id']}/approve",
        headers=secondary_manager_headers
    )
    assert approve_resp.status_code == 200

    # Verify inventory price is now 50.0
    items_resp = await client.get("/api/v1/inventory/items", headers=auth_headers)
    sugar_item = next(itm for itm in items_resp.json() if itm["name"].lower() == "sugar")
    assert sugar_item["unit_price"] == 50.0

    # 2. Update supplier with sugar price increased to 52 (4%, <=10%)
    update_sup_resp1 = await client.post(
        f"/api/v1/inventory/vendor-update/{supplier_id}",
        json={
            "name": "Auto Approved Supplier Ltd",
            "contact": "1234567890",
            "items_supplied": "Sugar (KG) @ ₹52 [Min: 10]"
        },
        headers=auth_headers,
    )
    assert update_sup_resp1.status_code == 200

    # Verify active price is still 50.0 (pending approval)
    items_resp = await client.get("/api/v1/inventory/items", headers=auth_headers)
    sugar_item = next(itm for itm in items_resp.json() if itm["name"].lower() == "sugar")
    assert sugar_item["unit_price"] == 50.0

    # Retrieve and approve the 52.0 request
    approvals_resp = await client.get("/api/v1/inventory/price-approvals", headers=auth_headers)
    sugar_app2 = next(app for app in approvals_resp.json() if app["item_name"].lower() == "sugar" and app["new_price"] == 52.0)
    
    approve_resp2 = await client.post(
        f"/api/v1/inventory/price-approvals/{sugar_app2['id']}/approve",
        headers=secondary_manager_headers
    )
    assert approve_resp2.status_code == 200

    # Verify inventory price is now 52.0
    items_resp = await client.get("/api/v1/inventory/items", headers=auth_headers)
    sugar_item = next(itm for itm in items_resp.json() if itm["name"].lower() == "sugar")
    assert sugar_item["unit_price"] == 52.0

    # 3. Update supplier with sugar price increased to 60 (+15.38%, 10%-25%)
    update_sup_resp2 = await client.post(
        f"/api/v1/inventory/vendor-update/{supplier_id}",
        json={
            "name": "Auto Approved Supplier Ltd",
            "contact": "1234567890",
            "items_supplied": "Sugar (KG) @ ₹60 [Min: 10]"
        },
        headers=auth_headers,
    )
    assert update_sup_resp2.status_code == 200

    # Verify active price is still 52.0 (pending approval)
    items_resp = await client.get("/api/v1/inventory/items", headers=auth_headers)
    sugar_item = next(itm for itm in items_resp.json() if itm["name"].lower() == "sugar")
    assert sugar_item["unit_price"] == 52.0

    # Retrieve and approve the 60.0 request
    approvals_resp = await client.get("/api/v1/inventory/price-approvals", headers=auth_headers)
    sugar_app3 = next(app for app in approvals_resp.json() if app["item_name"].lower() == "sugar" and app["new_price"] == 60.0)
    
    approve_resp3 = await client.post(
        f"/api/v1/inventory/price-approvals/{sugar_app3['id']}/approve",
        headers=secondary_manager_headers
    )
    assert approve_resp3.status_code == 200

    # Verify inventory price is now 60.0
    items_resp = await client.get("/api/v1/inventory/items", headers=auth_headers)
    sugar_item = next(itm for itm in items_resp.json() if itm["name"].lower() == "sugar")
    assert sugar_item["unit_price"] == 60.0


@pytest.mark.asyncio
async def test_supplier_price_sync_pending_approvals(client: AsyncClient, auth_headers, secondary_manager_headers):
    # 1. Register a supplier with Rice
    sup_resp = await client.post(
        "/api/v1/inventory/suppliers",
        json={
            "name": "Rice Supplier Ltd",
            "contact": "1234567890",
            "items_supplied": "Rice (KG) @ ₹100 [Min: 10]"
        },
        headers=auth_headers,
    )
    assert sup_resp.status_code == 200
    supplier_id = sup_resp.json()["id"]

    # Verify item exists with unit price 0.0 (pending approval)
    items_resp = await client.get("/api/v1/inventory/items", headers=auth_headers)
    rice_item = next(itm for itm in items_resp.json() if itm["name"].lower() == "rice")
    assert rice_item["unit_price"] == 0.0

    # Retrieve and approve the initial price request (100.0)
    approvals_resp = await client.get("/api/v1/inventory/price-approvals", headers=auth_headers)
    approvals = approvals_resp.json()
    rice_app_init = next(app for app in approvals if app["item_name"].lower() == "rice" and app["new_price"] == 100.0)
    
    approve_resp_init = await client.post(
        f"/api/v1/inventory/price-approvals/{rice_app_init['id']}/approve",
        headers=secondary_manager_headers
    )
    assert approve_resp_init.status_code == 200

    # Verify active price is now 100.0
    items_resp = await client.get("/api/v1/inventory/items", headers=auth_headers)
    rice_item = next(itm for itm in items_resp.json() if itm["name"].lower() == "rice")
    assert rice_item["unit_price"] == 100.0

    # 2. Update supplier with Rice price increased to 150 (+50%, 25%-100%)
    update_sup_resp = await client.post(
        f"/api/v1/inventory/vendor-update/{supplier_id}",
        json={
            "name": "Rice Supplier Ltd",
            "contact": "1234567890",
            "items_supplied": "Rice (KG) @ ₹150 [Min: 10]"
        },
        headers=auth_headers,
    )
    assert update_sup_resp.status_code == 200

    # Verify inventory item price did NOT update
    items_resp = await client.get("/api/v1/inventory/items", headers=auth_headers)
    rice_item = next(itm for itm in items_resp.json() if itm["name"].lower() == "rice")
    assert rice_item["unit_price"] == 100.0

    # 3. Retrieve pending price approvals
    approvals_resp = await client.get("/api/v1/inventory/price-approvals", headers=auth_headers)
    assert approvals_resp.status_code == 200
    approvals = approvals_resp.json()
    rice_app = next(app for app in approvals if app["item_name"].lower() == "rice" and app["new_price"] == 150.0)
    assert rice_app["approval_type"] == "WARNING"
    assert rice_app["status"] == "PENDING_APPROVAL"

    # 4. Approve the pending change request
    approve_resp = await client.post(
        f"/api/v1/inventory/price-approvals/{rice_app['id']}/approve",
        headers=secondary_manager_headers
    )
    assert approve_resp.status_code == 200

    # Verify item price is now updated
    items_resp = await client.get("/api/v1/inventory/items", headers=auth_headers)
    rice_item = next(itm for itm in items_resp.json() if itm["name"].lower() == "rice")
    assert rice_item["unit_price"] == 150.0

    # Verify AuditLog record is created
    async with AsyncSessionLocal() as session:
        audit_res = await session.execute(
            select(AuditLog).filter(
                AuditLog.action == "PRICE_APPROVAL_DECISION",
                AuditLog.entity_id == str(rice_app["id"])
            )
        )
        audit = audit_res.scalars().first()
        assert audit is not None
        assert "APPROVED" in audit.details


@pytest.mark.asyncio
async def test_supplier_price_sync_critical_alert_and_reject(client: AsyncClient, auth_headers, secondary_manager_headers):
    # 1. Register supplier with Oil
    sup_resp = await client.post(
        "/api/v1/inventory/suppliers",
        json={
            "name": "Oil Supplier Ltd",
            "contact": "1234567890",
            "items_supplied": "Oil (L) @ ₹100 [Min: 10]"
        },
        headers=auth_headers,
    )
    assert sup_resp.status_code == 200
    supplier_id = sup_resp.json()["id"]

    # Verify item exists with unit price 0.0 (pending approval)
    items_resp = await client.get("/api/v1/inventory/items", headers=auth_headers)
    oil_item = next(itm for itm in items_resp.json() if itm["name"].lower() == "oil")
    assert oil_item["unit_price"] == 0.0

    # Retrieve and approve the initial price request (100.0)
    approvals_resp = await client.get("/api/v1/inventory/price-approvals", headers=auth_headers)
    oil_app_init = next(app for app in approvals_resp.json() if app["item_name"].lower() == "oil" and app["new_price"] == 100.0)
    
    approve_resp_init = await client.post(
        f"/api/v1/inventory/price-approvals/{oil_app_init['id']}/approve",
        headers=secondary_manager_headers
    )
    assert approve_resp_init.status_code == 200

    # Verify active price is now 100.0
    items_resp = await client.get("/api/v1/inventory/items", headers=auth_headers)
    oil_item = next(itm for itm in items_resp.json() if itm["name"].lower() == "oil")
    assert oil_item["unit_price"] == 100.0

    # 2. Update supplier with Oil price increased to 250 (+150%, >100%)
    update_sup_resp = await client.post(
        f"/api/v1/inventory/vendor-update/{supplier_id}",
        json={
            "name": "Oil Supplier Ltd",
            "contact": "1234567890",
            "items_supplied": "Oil (L) @ ₹250 [Min: 10]"
        },
        headers=auth_headers,
    )
    assert update_sup_resp.status_code == 200

    # Verify inventory item price did NOT update
    items_resp = await client.get("/api/v1/inventory/items", headers=auth_headers)
    oil_item = next(itm for itm in items_resp.json() if itm["name"].lower() == "oil")
    assert oil_item["unit_price"] == 100.0

    # Verify PriceApprovalRequest exists with type CRITICAL
    approvals_resp = await client.get("/api/v1/inventory/price-approvals", headers=auth_headers)
    oil_app = next(app for app in approvals_resp.json() if app["item_name"].lower() == "oil")
    assert oil_app["approval_type"] == "CRITICAL"

    # Verify critical procurement alert notification exists
    async with AsyncSessionLocal() as session:
        notif_res = await session.execute(
            select(Notification).filter(Notification.title == "CRITICAL PROCUREMENT ALERT")
        )
        notifs = notif_res.scalars().all()
        assert len(notifs) >= 1

    # 3. Reject price change request
    reject_resp = await client.post(
        f"/api/v1/inventory/price-approvals/{oil_app['id']}/reject",
        json={"reason": "Rejected price is way too high!"},
        headers=secondary_manager_headers
    )
    assert reject_resp.status_code == 200

    # Verify item price remains 100
    items_resp = await client.get("/api/v1/inventory/items", headers=auth_headers)
    oil_item = next(itm for itm in items_resp.json() if itm["name"].lower() == "oil")
    assert oil_item["unit_price"] == 100.0

    # Verify request status in DB is REJECTED and has reason
    async with AsyncSessionLocal() as session:
        req_res = await session.execute(
            select(PriceApprovalRequest).filter(PriceApprovalRequest.id == UUID(oil_app["id"]))
        )
        req = req_res.scalars().first()
        assert req.status == "REJECTED"
        assert req.reason == "Rejected price is way too high!"

        # Verify audit log is logged
        audit_res = await session.execute(
            select(AuditLog).filter(
                AuditLog.action == "PRICE_APPROVAL_DECISION",
                AuditLog.entity_id == str(oil_app["id"])
            )
        )
        audit = audit_res.scalars().first()
        assert audit is not None
        assert "REJECTED" in audit.details


@pytest.mark.asyncio
async def test_self_approval_prevention(client: AsyncClient, auth_headers, secondary_manager_headers):
    # 1. Create inventory item
    item_resp = await client.post(
        "/api/v1/inventory/items",
        json={
            "name": "Self Approval Test Item",
            "category": "Ritual Supplies",
            "unit": "piece",
            "qty": 100,
            "min_stock": 10,
            "unit_price": 10.0,
            "remarks": "Segregation of Duties Test"
        },
        headers=auth_headers,
    )
    assert item_resp.status_code == 200
    item_id = item_resp.json()["id"]

    # 2. Update price manually (this should trigger pending price request)
    update_resp = await client.patch(
        f"/api/v1/inventory/items/{item_id}",
        json={
            "unit_price": 15.0,
            "version": 1
        },
        headers=auth_headers,
    )
    assert update_resp.status_code == 200

    # Verify active price is still 10.0
    items_resp = await client.get("/api/v1/inventory/items", headers=auth_headers)
    item_active = next(itm for itm in items_resp.json() if itm["id"] == item_id)
    assert item_active["unit_price"] == 10.0

    # 3. Retrieve pending price approvals
    approvals_resp = await client.get("/api/v1/inventory/price-approvals", headers=auth_headers)
    assert approvals_resp.status_code == 200
    approvals = approvals_resp.json()
    item_app = next(app for app in approvals if app["inventory_item_id"] == item_id)
    assert item_app["new_price"] == 15.0
    assert item_app["status"] == "PENDING_APPROVAL"

    # 4. Attempt to approve using the same user headers (should block with 403 Forbidden)
    approve_resp = await client.post(
        f"/api/v1/inventory/price-approvals/{item_app['id']}/approve",
        headers=auth_headers
    )
    assert approve_resp.status_code == 403
    res_json = approve_resp.json()
    err_msg = res_json.get("detail") or res_json.get("error", {}).get("message", "")
    assert "Self approval is not permitted" in err_msg

    # 5. Attempt to reject using the same user headers (should block with 403 Forbidden)
    reject_resp = await client.post(
        f"/api/v1/inventory/price-approvals/{item_app['id']}/reject",
        json={"reason": "Self rejection test"},
        headers=auth_headers
    )
    assert reject_resp.status_code == 403
    res_json = reject_resp.json()
    err_msg = res_json.get("detail") or res_json.get("error", {}).get("message", "")
    assert "Self approval is not permitted" in err_msg

    # 6. Approve using secondary manager headers (should succeed)
    approve_resp2 = await client.post(
        f"/api/v1/inventory/price-approvals/{item_app['id']}/approve",
        headers=secondary_manager_headers
    )
    assert approve_resp2.status_code == 200

