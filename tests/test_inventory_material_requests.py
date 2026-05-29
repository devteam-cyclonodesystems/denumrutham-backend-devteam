import pytest
from httpx import AsyncClient
from uuid import UUID

@pytest.mark.asyncio
async def test_material_request_workflow(client: AsyncClient, auth_headers):
    # 1. Create an inventory item first to request
    item_resp = await client.post(
        "/api/v1/inventory/items",
        json={
            "name": "Coconut",
            "category": "Ritual Supplies",
            "unit": "piece",
            "qty": 50,
            "min_stock": 5,
            "unit_price": 15.0,
            "remarks": "For test request"
        },
        headers=auth_headers,
    )
    assert item_resp.status_code == 200
    item_id = item_resp.json()["id"]

    # 2. Create a Material Request
    req_resp = await client.post(
        "/api/v1/inventory/item-requests",
        json={
            "date": "2026-05-29",
            "requester": "Head Priest",
            "role": "Priest",
            "department": "Pooja Department",
            "items_summary": "1 item requested",
            "items_data": [{"itemId": item_id, "qty": 10}],
            "remarks": "Need coconuts for Ganesha Pooja",
            "priority": "High",
            "purpose": "Daily Puja"
        },
        headers=auth_headers,
    )
    assert req_resp.status_code == 200
    req_data = req_resp.json()
    assert req_data["status"] == "PENDING"
    assert req_data["priority"] == "High"
    assert req_data["purpose"] == "Daily Puja"
    req_id = req_data["id"]

    # 3. Approve the Material Request
    approve_resp = await client.post(
        f"/api/v1/inventory/item-requests/{req_id}/approve",
        json=[{"itemId": item_id, "approvedQty": 8.0}],
        headers=auth_headers,
    )
    assert approve_resp.status_code == 200
    req_data = approve_resp.json()
    assert req_data["status"] == "APPROVED"
    assert req_data["items_data"][0]["approvedQty"] == 8.0

    # 4. Issue Stock for the request
    issue_resp = await client.post(
        f"/api/v1/inventory/item-requests/{req_id}/issue",
        json={
            "issued_items": [{"itemId": item_id, "qty": 8.0}],
            "location_id": None
        },
        headers=auth_headers,
    )
    assert issue_resp.status_code == 200
    req_data = issue_resp.json()
    assert req_data["status"] == "ISSUED"
    assert req_data["items_data"][0]["issuedQty"] == 8.0

    # 5. Check that item stock is decremented
    # Originally we added 50. Issued 8. Remaining should be 42.
    items_resp = await client.get("/api/v1/inventory/items", headers=auth_headers)
    assert items_resp.status_code == 200
    items = items_resp.json()
    test_item = next(itm for itm in items if itm["id"] == item_id)
    assert test_item["stock"] == 42
