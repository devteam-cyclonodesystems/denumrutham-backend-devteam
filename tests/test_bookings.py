import pytest


@pytest.mark.asyncio
async def test_list_bookings(client, auth_headers):
    """GET /bookings returns an array."""
    resp = await client.get("/api/v1/bookings", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_list_bookings_unauthenticated(client):
    """GET /bookings without auth is rejected."""
    resp = await client.get("/api/v1/bookings")
    assert resp.status_code == 401
