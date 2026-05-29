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


@pytest.mark.asyncio
async def test_role_cloning(client, auth_headers):
    """Cloning a role copies the permission mapping to the new role."""
    # 1. Create a base role
    create_role_resp = await client.post(
        "/api/v1/rbac/roles",
        json={"name": "PriestBase", "description": "Original priest role"},
        headers=auth_headers,
    )
    assert create_role_resp.status_code == 201
    source_role_id = create_role_resp.json()["id"]

    # 2. Add a permission mapping to it (we first fetch available permissions to link)
    perms_resp = await client.get("/api/v1/rbac/permissions", headers=auth_headers)
    assert perms_resp.status_code == 200
    perms = perms_resp.json()
    assert len(perms) > 0
    target_perm_id = perms[0]["id"]

    assign_resp = await client.post(
        f"/api/v1/rbac/roles/{source_role_id}/permissions",
        json=[{"permission_id": target_perm_id, "access_level": "full"}],
        headers=auth_headers,
    )
    assert assign_resp.status_code == 201

    # 3. Clone the role
    clone_resp = await client.post(
        f"/api/v1/rbac/roles/{source_role_id}/clone",
        json={"name": "SeniorPriestCloned", "description": "Cloned Priest Role"},
        headers=auth_headers,
    )
    assert clone_resp.status_code == 201
    cloned_role_data = clone_resp.json()
    assert cloned_role_data["name"] == "SeniorPriestCloned"
    cloned_role_id = cloned_role_data["id"]

    # 4. Check permissions of cloned role to verify they match
    cloned_perms_resp = await client.get(
        f"/api/v1/rbac/roles/{cloned_role_id}/permissions",
        headers=auth_headers,
    )
    assert cloned_perms_resp.status_code == 200
    cloned_perms = cloned_perms_resp.json()["permissions"]
    assert len(cloned_perms) == 1
    assert cloned_perms[0]["resource_key"] == perms[0]["resource_key"]
