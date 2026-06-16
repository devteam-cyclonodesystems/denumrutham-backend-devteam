import pytest
import json
import asyncio
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4
from sqlalchemy.future import select
from httpx import AsyncClient

from app.models.domain import (
    Temple, StoreProduct, StoreStock, PlatformAdvertisement, TempleAdvertisement
)
from app.modules.temple_management.models.offering import Offering
from app.modules.inventory.models.inventory_models import StoreSalesOrder, InventoryStockLedger
from app.modules.governance.models.governance_models import PlatformGlobalSetting
from app.modules.billing.models.billing_models import Payment, PaymentStatus
from app.core.security.encryption import encrypt_data, decrypt_data
from app.core.payments.providers import UPIQRAdapter
from app.core.cache import GlobalConfigurationCache

@pytest.mark.anyio
async def test_fcm_adapter_and_encryption(client: AsyncClient, superadmin_auth_headers: dict):
    # Test encryption utility functions
    credentials = {"project_id": "denumrutham-test", "private_key": "some-private-key-data"}
    raw_str = json.dumps(credentials)
    encrypted = encrypt_data(raw_str)
    assert encrypted != raw_str
    
    decrypted = decrypt_data(encrypted)
    assert decrypted == raw_str
    
    # Save FCM credentials through superadmin API
    payload = {"value": credentials}
    resp = await client.put("/api/v1/superadmin/global-settings/fcm_credentials", json=payload, headers=superadmin_auth_headers)
    assert resp.status_code == 200
    
    # Verify database value is encrypted
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(PlatformGlobalSetting).filter(PlatformGlobalSetting.key == "fcm_credentials"))
        setting = res.scalar_one()
        assert "encrypted_credentials" in setting.value
        assert setting.value["encrypted_credentials"] != raw_str
        
    # Get FCM credentials through API - must be masked
    get_resp = await client.get("/api/v1/superadmin/global-settings/fcm_credentials", headers=superadmin_auth_headers)
    assert get_resp.status_code == 200
    val = get_resp.json()["value"]
    assert val["encrypted_credentials"] == "********"


@pytest.mark.anyio
async def test_upi_qr_adapter():
    adapter = UPIQRAdapter()
    ref_id = uuid4()
    resp = await adapter.create_payment(amount=250.50, reference_id=ref_id)
    assert resp["status"] == "SUCCESS"
    assert resp["provider"] == "UPI_QR"
    assert "upi://pay" in resp["upi_link"]
    assert "pa=temple%40upi" or "pa=temple@upi" in resp["upi_link"]
    assert f"am=250.50" in resp["upi_link"]


@pytest.mark.anyio
async def test_guest_checkout_e2e(client: AsyncClient, auth_headers: dict):
    # Setup temple & product
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        # Fetch active temple
        t_res = await db.execute(select(Temple).filter(Temple.is_active == True))
        temple = t_res.scalars().first()
        assert temple is not None
        temple_slug = temple.domain
        temple_id = temple.id

    # Create a product
    prod_data = {
        "name": "Sandalwood Paste Box",
        "category": "Pooja Material",
        "unit": "box",
        "unit_price": 120.0,
        "sku": f"SW-{uuid4().hex[:6]}"
    }
    resp = await client.post("/api/v1/store/products", json=prod_data, headers=auth_headers)
    assert resp.status_code == 200
    product = resp.json()
    product_id = product["id"]

    # Adjust stock
    async with AsyncSessionLocal() as db:
        stock_res = await db.execute(select(StoreStock).filter(StoreStock.product_id == UUID(product_id)))
        stock = stock_res.scalar_one()
        stock.quantity = 15.0
        await db.commit()

    # Guest Checkout
    checkout_payload = {
        "guest_name": "Devotee Suresh",
        "guest_phone": "9876543210",
        "guest_email": "suresh@example.com",
        "items": [
            {
                "product_id": product_id,
                "quantity": 3.0,
                "unit_price": 120.0
            }
        ]
    }
    checkout_resp = await client.post(
        f"/api/v1/public/temples/{temple_slug}/store/guest-checkout",
        json=checkout_payload
    )
    assert checkout_resp.status_code == 201
    checkout_res = checkout_resp.json()
    assert checkout_res["items_count"] == 1
    assert checkout_res["total_amount"] == 360.0
    order_id = UUID(checkout_res["order_id"])

    # Verify stock decremented to 12.0 and ledger movement recorded
    async with AsyncSessionLocal() as db:
        stock_res = await db.execute(select(StoreStock).filter(StoreStock.product_id == UUID(product_id)))
        assert stock_res.scalar_one().quantity == 12.0
        
        # Verify order exists with status PENDING
        order_res = await db.execute(select(StoreSalesOrder).filter(StoreSalesOrder.id == order_id))
        order = order_res.scalar_one()
        assert order.payment_status == "PENDING"
        
        # Verify ledger movement
        ledger_res = await db.execute(
            select(InventoryStockLedger).filter(
                InventoryStockLedger.store_product_id == UUID(product_id),
                InventoryStockLedger.remarks.like("%Guest checkout%")
            )
        )
        assert ledger_res.scalars().first() is not None

    # Simulate webhook payment callback
    webhook_resp = await client.post(f"/api/v1/payments/verify/{order_id}")
    assert webhook_resp.status_code == 200
    
    # Verify order is PAID
    async with AsyncSessionLocal() as db:
        order_res = await db.execute(select(StoreSalesOrder).filter(StoreSalesOrder.id == order_id))
        assert order_res.scalar_one().payment_status == "PAID"


@pytest.mark.anyio
async def test_public_offerings_e2e(client: AsyncClient, auth_headers: dict):
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        t_res = await db.execute(select(Temple).filter(Temple.is_active == True))
        temple = t_res.scalars().first()
        temple_slug = temple.domain

    offering_payload = {
        "donor_name": "Ramesh Kumar",
        "donor_email": "ramesh@example.com",
        "donor_phone": "9998887776",
        "donor_address": "Kochi, Kerala",
        "amount": 1000.0,
        "offering_type": "DONATION",
        "notification_mode": "EMAIL",
        "offering_metadata": {" gothram": "Kashyapa", "remarks": "Family wellbeing"}
    }
    
    resp = await client.post(
        f"/api/v1/public/temples/{temple_slug}/offerings",
        json=offering_payload
    )
    assert resp.status_code == 201
    res = resp.json()
    assert res["status"] == "success"
    assert "payment" in res
    assert "upi_link" in res["payment"]
    offering_id = UUID(res["offering_id"])
    
    # Verify offering created in database in CREATED status
    async with AsyncSessionLocal() as db:
        off_res = await db.execute(select(Offering).filter(Offering.id == offering_id))
        offering = off_res.scalar_one()
        assert offering.payment_status == "CREATED"
        assert offering.offering_type == "DONATION"
        assert offering.donor_email == "ramesh@example.com"
        
    # Verify webhook payment transitions status to PAID
    webhook_resp = await client.post(f"/api/v1/payments/verify/{offering_id}")
    assert webhook_resp.status_code == 200
    
    async with AsyncSessionLocal() as db:
        off_res = await db.execute(select(Offering).filter(Offering.id == offering_id))
        offering = off_res.scalar_one()
        assert offering.payment_status == "PAID"
        assert offering.paid_amount == 1000.0
        assert offering.balance_amount == 0.0


@pytest.mark.anyio
async def test_global_website_publish_with_cache(client: AsyncClient, superadmin_auth_headers: dict):
    # Set draft setting
    draft_config = {
        "header": {"menu": ["Home", "Poojas", "Store"]},
        "footer": {"copyright": "Copyright 2026 Denumrutham"},
        "directory_layout": "grid",
        "ad_placements": ["HEADER_LEADERBOARD", "TEMPLE_LIST_INLINE"]
    }
    
    # Save draft
    put_resp = await client.put(
        "/api/v1/superadmin/global-settings/global_website_builder_draft",
        json={"value": draft_config},
        headers=superadmin_auth_headers
    )
    assert put_resp.status_code == 200
    
    # Verify cache starts clean
    GlobalConfigurationCache.invalidate_all()
    assert GlobalConfigurationCache.get("global_website_builder_live") is None
    
    # Publish setting
    pub_resp = await client.post(
        "/api/v1/superadmin/global-settings/global_website_builder/publish",
        headers=superadmin_auth_headers
    )
    assert pub_resp.status_code == 200
    pub_res = pub_resp.json()
    assert pub_res["status"] == "success"
    version = pub_res["version"]
    assert version >= 1
    
    # Retrieve public settings - should store in cache
    get_resp = await client.get(
        "/api/v1/public/temples/global-settings/global_website_builder_live"
    )
    assert get_resp.status_code == 200
    live_config = get_resp.json()["value"]
    assert live_config["version"] == version
    assert live_config["directory_layout"] == "grid"
    
    # Verify cache now contains the key
    assert GlobalConfigurationCache.get("global_website_builder_live") is not None
    
    # Publish again and check cache gets invalidated
    pub_resp2 = await client.post(
        "/api/v1/superadmin/global-settings/global_website_builder/publish",
        headers=superadmin_auth_headers
    )
    assert pub_resp2.status_code == 200
    assert GlobalConfigurationCache.get("global_website_builder_live") is None


@pytest.mark.anyio
async def test_ad_approval_rejection_and_caps(client: AsyncClient, superadmin_auth_headers: dict):
    from app.core.database import AsyncSessionLocal
    # Create campaign
    async with AsyncSessionLocal() as db:
        t_res = await db.execute(select(Temple).filter(Temple.is_active == True))
        temple = t_res.scalars().first()
        temple_id = temple.id

    # Create Platform Ad
    ad_payload = {
        "placement": "HEADER_LEADERBOARD",
        "media_type": "IMAGE",
        "media_urls": ["https://example.com/ad.png"],
        "target_url": "https://sponsor-website.com",
        "is_active": True,
        "start_date": datetime.now(timezone.utc).isoformat(),
        "end_date": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }
    
    create_resp = await client.post(
        "/api/v1/superadmin/platform-advertisements",
        json=ad_payload,
        headers=superadmin_auth_headers
    )
    assert create_resp.status_code == 201
    ad = create_resp.json()
    ad_id = UUID(ad["id"])
    
    # Verify ad initialized with status APPROVED or PENDING
    # Let's approve it using our approve endpoint, setting caps
    approve_payload = {
        "priority": "HIGH",
        "cpm_rate": 10.0,
        "cpc_rate": 0.50,
        "impression_cap": 5,
        "click_cap": 2,
        "billing_contact": "sponsor@example.com"
    }
    
    app_resp = await client.post(
        f"/api/v1/superadmin/advertisements/{ad_id}/approve",
        json=approve_payload,
        headers=superadmin_auth_headers
    )
    assert app_resp.status_code == 200
    
    # Fetch database value to ensure approved
    async with AsyncSessionLocal() as db:
        stmt = select(PlatformAdvertisement).filter(PlatformAdvertisement.id == ad_id)
        ad_db = (await db.execute(stmt)).scalar_one()
        assert ad_db.approval_status == "APPROVED"
        assert ad_db.click_cap == 2
        
    # Log click telemetry event 1
    click_payload = {
        "advertisement_id": str(ad_id),
        "advertisement_type": "PLATFORM",
        "event_type": "CLICK",
        "visitor_hash": "visitor1",
        "session_id": "session1"
    }
    
    clk_resp1 = await client.post("/api/v1/public/advertisements/events", json=click_payload)
    assert clk_resp1.status_code == 200
    
    # Wait briefly for background task calculations
    await asyncio.sleep(0.5)
    
    # Log click telemetry event 2 (reaches cap)
    click_payload["visitor_hash"] = "visitor2"
    click_payload["session_id"] = "session2"
    clk_resp2 = await client.post("/api/v1/public/advertisements/events", json=click_payload)
    assert clk_resp2.status_code == 200
    
    await asyncio.sleep(0.5)
    
    # Verify campaign transitioned to EXPIRED due to cap exhaustion
    async with AsyncSessionLocal() as db:
        stmt = select(PlatformAdvertisement).filter(PlatformAdvertisement.id == ad_id)
        ad_db = (await db.execute(stmt)).scalar_one()
        assert ad_db.approval_status == "EXPIRED"
        
        # Verify CampaignRevenueMetrics recorded
        from app.modules.temple_management.models.temple_models import CampaignRevenueMetrics
        metrics_stmt = select(CampaignRevenueMetrics).filter(CampaignRevenueMetrics.campaign_id == ad_id)
        metrics = (await db.execute(metrics_stmt)).scalar_one_or_none()
        assert metrics is not None
        assert metrics.total_clicks >= 2
        assert metrics.estimated_revenue == 0.50 * metrics.total_clicks

    # Verify we can fetch the audit history for this ad
    audit_resp = await client.get(
        f"/api/v1/superadmin/advertisements/{ad_id}/audit-history",
        headers=superadmin_auth_headers
    )
    assert audit_resp.status_code == 200
    audit_history = audit_resp.json()
    assert isinstance(audit_history, list)
    assert len(audit_history) >= 1



@pytest.mark.anyio
async def test_advertisement_reports(client: AsyncClient, superadmin_auth_headers: dict):
    # Retrieve platform ad reports
    resp = await client.get(
        "/api/v1/superadmin/advertisements/reports",
        headers=superadmin_auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
