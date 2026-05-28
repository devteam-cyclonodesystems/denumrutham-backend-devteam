import pytest


@pytest.mark.asyncio
async def test_create_donation(client, auth_headers):
    """Create a donation."""
    resp = await client.post(
        "/api/v1/donations",
        json={"amount": 1000.0, "notes": "Annual festival donation"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["amount"] == 1000.0
    assert "id" in body
    assert "created_at" in body


@pytest.mark.asyncio
async def test_list_donations(client, auth_headers):
    """GET /donations returns an array."""
    resp = await client.get("/api/v1/donations", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1  # at least the one we just created


@pytest.mark.asyncio
async def test_list_donations_unauthenticated(client):
    """GET /donations without auth is rejected."""
    resp = await client.get("/api/v1/donations")
    assert resp.status_code == 401
