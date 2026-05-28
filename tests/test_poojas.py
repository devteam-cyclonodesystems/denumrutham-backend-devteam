import pytest


@pytest.mark.asyncio
async def test_create_pooja(client, auth_headers):
    """Admin can create a pooja."""
    resp = await client.post(
        "/api/v1/poojas",
        json={"name": "Ganapathi Homam", "base_price": 500.0, "is_active": True},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Ganapathi Homam"
    assert body["base_price"] == 500.0


@pytest.mark.asyncio
async def test_list_poojas(client, auth_headers):
    """List poojas returns an array."""
    resp = await client.get("/api/v1/poojas", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_create_pooja_unauthenticated(client):
    """Creating a pooja without auth is rejected."""
    resp = await client.post(
        "/api/v1/poojas",
        json={"name": "Test", "base_price": 100.0},
    )
    assert resp.status_code == 401
