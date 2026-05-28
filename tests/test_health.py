import pytest


@pytest.mark.asyncio
async def test_health_check(client):
    resp = await client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "alive"
