import pytest


@pytest.mark.asyncio
async def test_create_devotee(client, auth_headers):
    """Create a devotee via POST."""
    resp = await client.post(
        "/api/v1/devotees",
        json={
            "first_name": "Ravi",
            "last_name": "Kumar",
            "phone": "9876543210",
            "email": "ravi@example.com",
            "star_sign_nakshatram": "Ashwini",
            "gotram": "Bharadwaja",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["first_name"] == "Ravi"
    assert "id" in body
    assert "temple_id" in body
    assert "created_at" in body


@pytest.mark.asyncio
async def test_list_devotees(client, auth_headers):
    """List devotees returns an array (may include the one we just created)."""
    resp = await client.get("/api/v1/devotees", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_create_devotee_minimal(client, auth_headers):
    """Create a devotee with only required fields."""
    resp = await client.post(
        "/api/v1/devotees",
        json={"first_name": "Sita"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["first_name"] == "Sita"
