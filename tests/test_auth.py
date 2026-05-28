import pytest


@pytest.mark.asyncio
async def test_login_success(client):
    """Valid credentials return a JWT token."""
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "superadmin@temple", "password": "admin@123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body["data"]
    assert body["data"]["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    """Wrong password returns 400."""
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "superadmin@temple", "password": "wrongpassword"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_login_unknown_user(client):
    """Non-existent user returns 400."""
    resp = await client.post(
        "/api/v1/auth/login",
        data={"username": "nobody@temple.com", "password": "whatever"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_protected_endpoint_without_token(client):
    """Accessing a protected route with no token returns 401."""
    resp = await client.get("/api/v1/devotees")
    assert resp.status_code == 401
