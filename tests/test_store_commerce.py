import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from uuid import UUID, uuid4
from sqlalchemy.future import select
from httpx import AsyncClient

from app.models.domain import (
    StoreProduct, StoreStock, StoreSalesOrder, AuctionListing,
    StoreStockReservation, InventoryStockLedger, InventoryMovementType
)
from app.tasks.background_jobs import cleanup_expired_reservations
from app.utils.number_generator import get_ist_now

@pytest.mark.anyio
async def test_store_flow_e2e(client: AsyncClient, auth_headers: dict):
    # 1. Create a Store Product
    prod_data = {
        "name": "Panchaloha Deity Idol",
        "category": "Idols",
        "unit": "piece",
        "unit_price": 5000.0,
        "sku": "PL-DEITY-01"
    }
    resp = await client.post("/api/v1/store/products", json=prod_data, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    product = resp.json()
    product_id = UUID(product["id"])
    assert product["name"] == "Panchaloha Deity Idol"
    assert product["sku"] == "PL-DEITY-01"

    # Verify stock row was initialized to 0
    # Let's search products lists
    list_resp = await client.get("/api/v1/store/products", headers=auth_headers)
    assert list_resp.status_code == 200
    assert any(UUID(p["id"]) == product_id for p in list_resp.json())

    # 2. Add stock using stock adjustment movement (so we have inventory to sell)
    # We will test POS checkout: stock is 0.0, so sale should fail with 400
    order_data = {
        "customer_name": "Devotee Ram",
        "customer_phone": "9988776655",
        "items": [
            {
                "product_id": str(product_id),
                "quantity": 2.0,
                "unit_price": 5000.0
            }
        ],
        "payment_mode": "Card",
        "idempotency_key": f"key-pos-{uuid4()}"
    }
    pos_fail_resp = await client.post("/api/v1/store/orders", json=order_data, headers=auth_headers)
    assert pos_fail_resp.status_code == 400
    assert "Insufficient stock" in pos_fail_resp.json()["error"]["message"]

    # Now let's directly adjust stock in DB so we can test sale
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        # Load the StoreStock row
        stock_res = await session.execute(
            select(StoreStock).filter(StoreStock.product_id == product_id)
        )
        stock = stock_res.scalars().first()
        assert stock is not None
        stock.quantity = 10.0
        await session.commit()

    # 3. Test POS Checkout with Idempotency Key
    idempotency_key = f"key-pos-{uuid4()}"
    order_data["idempotency_key"] = idempotency_key
    
    pos_success_resp = await client.post("/api/v1/store/orders", json=order_data, headers=auth_headers)
    assert pos_success_resp.status_code == 200, pos_success_resp.text
    order1 = pos_success_resp.json()
    assert order1["order_number"].startswith("SO-")
    assert order1["total_amount"] == 10000.0

    # Verify stock decremented to 8.0
    async with AsyncSessionLocal() as session:
        stock_res = await session.execute(
            select(StoreStock).filter(StoreStock.product_id == product_id)
        )
        stock = stock_res.scalars().first()
        assert stock.quantity == 8.0

    # Replay same idempotency key - should return same order without double decrement
    pos_replay_resp = await client.post("/api/v1/store/orders", json=order_data, headers=auth_headers)
    assert pos_replay_resp.status_code == 200
    assert pos_replay_resp.json()["id"] == order1["id"]

    # Verify stock remains 8.0
    async with AsyncSessionLocal() as session:
        stock_res = await session.execute(
            select(StoreStock).filter(StoreStock.product_id == product_id)
        )
        stock = stock_res.scalars().first()
        assert stock.quantity == 8.0

    # 4. Test Auctions & Reservations
    auc_data = {
        "product_id": str(product_id),
        "quantity": 3.0,
        "start_price": 6000.0
    }
    auc_resp = await client.post("/api/v1/store/auctions", json=auc_data, headers=auth_headers)
    assert auc_resp.status_code == 200, auc_resp.text
    auction = auc_resp.json()
    auction_id = UUID(auction["id"])
    assert auction["status"] == "AVAILABLE"
    assert auction["auction_code"].startswith("AUC-")

    # Place a Bid - should place reservation and reduce available stock
    bid_resp = await client.post(
        f"/api/v1/store/auctions/{auction_id}/bid",
        json={"bid_amount": 7500.0},
        headers=auth_headers
    )
    assert bid_resp.status_code == 200, bid_resp.text
    bid_result = bid_resp.json()
    assert bid_result["status"] == "success"
    assert bid_result["current_bid"] == 7500.0
    reservation_id = UUID(bid_result["reservation_id"])

    # Stock should be decremented from 8.0 to 5.0 due to reservation
    async with AsyncSessionLocal() as session:
        stock_res = await session.execute(
            select(StoreStock).filter(StoreStock.product_id == product_id)
        )
        stock = stock_res.scalars().first()
        assert stock.quantity == 5.0

    # 5. Settle Auction - Settle confirms reservation and generates sales order
    settle_idempotency = f"key-settle-{uuid4()}"
    settle_resp = await client.post(
        f"/api/v1/store/auctions/{auction_id}/settle",
        json={
            "customer_name": "Auction Winner Krishnan",
            "customer_phone": "9876543210",
            "payment_mode": "UPI",
            "idempotency_key": settle_idempotency
        },
        headers=auth_headers
    )
    assert settle_resp.status_code == 200, settle_resp.text
    settled_order = settle_resp.json()
    assert settled_order["total_amount"] == 7500.0

    # Stock remains 5.0 (reservation confirmed, net change is 0 since stock was locked at bid)
    async with AsyncSessionLocal() as session:
        stock_res = await session.execute(
            select(StoreStock).filter(StoreStock.product_id == product_id)
        )
        stock = stock_res.scalars().first()
        assert stock.quantity == 5.0
        
        # Verify reservation status is CONFIRMED
        res_res = await session.execute(
            select(StoreStockReservation).filter(StoreStockReservation.id == reservation_id)
        )
        res = res_res.scalars().first()
        assert res.reservation_status == "CONFIRMED"

    # Replay Settle - should return same order
    settle_replay_resp = await client.post(
        f"/api/v1/store/auctions/{auction_id}/settle",
        json={
            "customer_name": "Auction Winner Krishnan",
            "customer_phone": "9876543210",
            "payment_mode": "UPI",
            "idempotency_key": settle_idempotency
        },
        headers=auth_headers
    )
    assert settle_replay_resp.status_code == 200
    assert settle_replay_resp.json()["id"] == settled_order["id"]

    # 6. Test Expiry & Background Cleanup
    # Create another auction and bid to lock stock
    auc2_data = {
        "product_id": str(product_id),
        "quantity": 2.0,
        "start_price": 6000.0
    }
    auc2_resp = await client.post("/api/v1/store/auctions", json=auc2_data, headers=auth_headers)
    assert auc2_resp.status_code == 200
    auc2_id = UUID(auc2_resp.json()["id"])

    bid2_resp = await client.post(
        f"/api/v1/store/auctions/{auc2_id}/bid",
        json={"bid_amount": 7000.0},
        headers=auth_headers
    )
    assert bid2_resp.status_code == 200
    reservation2_id = UUID(bid2_resp.json()["reservation_id"])

    # Stock is now 3.0
    async with AsyncSessionLocal() as session:
        stock_res = await session.execute(
            select(StoreStock).filter(StoreStock.product_id == product_id)
        )
        stock = stock_res.scalars().first()
        assert stock.quantity == 3.0

    # Manually backdate the expires_at of reservation2 to the past
    async with AsyncSessionLocal() as session:
        res2_res = await session.execute(
            select(StoreStockReservation).filter(StoreStockReservation.id == reservation2_id)
        )
        res2 = res2_res.scalars().first()
        res2.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        await session.commit()

    # Trigger background cleanup job manually
    await cleanup_expired_reservations()

    # Stock should be restored to 5.0 and reservation2 should be RELEASED
    async with AsyncSessionLocal() as session:
        stock_res = await session.execute(
            select(StoreStock).filter(StoreStock.product_id == product_id)
        )
        stock = stock_res.scalars().first()
        assert stock.quantity == 5.0

        res2_res = await session.execute(
            select(StoreStockReservation).filter(StoreStockReservation.id == reservation2_id)
        )
        res2 = res2_res.scalars().first()
        assert res2.reservation_status == "RELEASED"

    # 7. Check Observability Dashboard
    health_resp = await client.get("/api/v1/store/health-dashboard", headers=auth_headers)
    assert health_resp.status_code == 200
    metrics = health_resp.json()["metrics"]
    assert metrics["stale_reservations_released"] >= 1
    assert "kalavara_low_stock_count" in metrics
    assert "store_low_stock_count" in metrics

    # 8. Test Product Media and Edit endpoint
    prod_with_media = {
        "name": "Deity Saree",
        "category": "Offerings",
        "unit": "piece",
        "unit_price": 300.0,
        "sku": "SR-DEITY-01",
        "media": ["/static/uploads/img1.png", "/static/uploads/img2.png"]
    }
    create_resp = await client.post("/api/v1/store/products", json=prod_with_media, headers=auth_headers)
    assert create_resp.status_code == 200
    created_prod = create_resp.json()
    assert created_prod["media"] == ["/static/uploads/img1.png", "/static/uploads/img2.png"]
    
    update_data = {
        "unit_price": 350.0,
        "media": ["/static/uploads/img1.png", "/static/uploads/img2.png", "/static/uploads/img3.png"]
    }
    update_resp = await client.put(f"/api/v1/store/products/{created_prod['id']}", json=update_data, headers=auth_headers)
    assert update_resp.status_code == 200
    updated_prod = update_resp.json()
    assert updated_prod["unit_price"] == 350.0
    assert updated_prod["media"] == ["/static/uploads/img1.png", "/static/uploads/img2.png", "/static/uploads/img3.png"]

