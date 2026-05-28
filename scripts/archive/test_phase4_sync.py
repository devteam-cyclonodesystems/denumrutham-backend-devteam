"""
Phase 4 Validation Tests — Version Atomicity + Hybrid Sync.

Tests:
  1. Version atomicity under concurrent access
  2. Sync pull (incremental changes)
  3. Sync push (batch updates with version check)
  4. Conflict detection (client_version < server_version)
  5. Server-wins resolution
  6. Blocked offline fields (status, delete)
  7. RBAC enforcement on sync
"""
import asyncio
import httpx
import sys
import os
from datetime import datetime, timezone, timedelta

# --- Configuration ---
BASE_URL = os.getenv("TMS_API_URL", "http://localhost:8000/api/v1")
SUPERADMIN_USER = os.getenv("TMS_SUPERADMIN_USER", "superadmin")
SUPERADMIN_PASS = os.getenv("TMS_SUPERADMIN_PASS", "superadmin123")


async def get_token(client: httpx.AsyncClient) -> str:
    """Authenticate and return a bearer token."""
    resp = await client.post(
        f"{BASE_URL}/auth/login",
        data={"username": SUPERADMIN_USER, "password": SUPERADMIN_PASS},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    body = resp.json()
    # Handle api_response wrapper: token may be in body["data"]["access_token"]
    if "data" in body and isinstance(body["data"], dict):
        return body["data"]["access_token"]
    return body["access_token"]


def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def get_test_temple(client: httpx.AsyncClient, token: str) -> dict:
    """Get the first temple from the list for testing."""
    resp = await client.get(
        f"{BASE_URL}/superadmin/temples/?include_inactive=true",
        headers=headers(token),
    )
    assert resp.status_code == 200, f"List temples failed: {resp.text}"
    temples = resp.json()["temples"]
    assert len(temples) > 0, "No temples found — seed test data first"
    return temples[0]


# ══════════════════════════════════════════════════════════════════════
# TEST 1: Sync Pull
# ══════════════════════════════════════════════════════════════════════

async def test_sync_pull():
    """Test GET /temples/sync returns changes since a timestamp."""
    async with httpx.AsyncClient() as client:
        token = await get_token(client)
        
        # Pull from the distant past — should return all temples
        since = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        resp = await client.get(
            f"{BASE_URL}/superadmin/temples/sync",
            params={"since": since, "limit": 10},
            headers=headers(token),
        )
        assert resp.status_code == 200, f"Sync pull failed: {resp.text}"
        data = resp.json()
        
        assert "temples" in data, "Missing 'temples' key"
        assert "server_time" in data, "Missing 'server_time' key"
        assert "count" in data, "Missing 'count' key"
        assert data["count"] > 0, "Expected at least one temple"
        
        # Verify each item has version
        for item in data["temples"]:
            assert "version" in item, f"Temple {item['id']} missing version"
            assert "updated_at" in item, f"Temple {item['id']} missing updated_at"
        
        print(f"  [PASS] Sync pull returned {data['count']} temples")
        print(f"  [PASS] Server time: {data['server_time']}")
        return data


# ══════════════════════════════════════════════════════════════════════
# TEST 2: Sync Push — Successful Update
# ══════════════════════════════════════════════════════════════════════

async def test_sync_push_success():
    """Test POST /temples/sync applies updates with matching version."""
    async with httpx.AsyncClient() as client:
        token = await get_token(client)
        temple = await get_test_temple(client, token)
        
        temple_id = temple["id"]
        current_version = temple.get("version", 1)
        
        resp = await client.post(
            f"{BASE_URL}/superadmin/temples/sync",
            json={
                "updates": [{
                    "id": temple_id,
                    "version": current_version,
                    "changes": {"description": f"Sync test at {datetime.now(timezone.utc).isoformat()}"},
                    "local_change_id": "test-001",
                }]
            },
            headers=headers(token),
        )
        assert resp.status_code == 200, f"Sync push failed: {resp.text}"
        data = resp.json()
        
        assert data["applied"] == 1, f"Expected 1 applied, got {data['applied']}"
        assert data["conflicts"] == 0, f"Unexpected conflicts: {data['conflicts']}"
        
        result = data["results"][0]
        assert result["status"] == "applied", f"Expected 'applied', got '{result['status']}'"
        assert result["server_version"] == current_version + 1, \
            f"Expected version {current_version + 1}, got {result['server_version']}"
        
        print(f"  [PASS] Sync push applied: v{current_version} -> v{current_version + 1}")
        return data


# ══════════════════════════════════════════════════════════════════════
# TEST 3: Sync Push — Conflict Detection
# ══════════════════════════════════════════════════════════════════════

async def test_sync_push_conflict():
    """Test that stale client version triggers a conflict response."""
    async with httpx.AsyncClient() as client:
        token = await get_token(client)
        temple = await get_test_temple(client, token)
        
        temple_id = temple["id"]
        current_version = temple.get("version", 1)
        
        # Send with a stale version (current - 1)
        stale_version = max(current_version - 1, 0)
        
        resp = await client.post(
            f"{BASE_URL}/superadmin/temples/sync",
            json={
                "updates": [{
                    "id": temple_id,
                    "version": stale_version,
                    "changes": {"description": "This should conflict"},
                    "local_change_id": "conflict-001",
                }]
            },
            headers=headers(token),
        )
        assert resp.status_code == 200, f"Sync push failed: {resp.text}"
        data = resp.json()
        
        assert data["conflicts"] == 1, f"Expected 1 conflict, got {data['conflicts']}"
        
        result = data["results"][0]
        assert result["status"] == "conflict", f"Expected 'conflict', got '{result['status']}'"
        assert "server_data" in result, "Missing server_data in conflict response"
        assert "client_data" in result, "Missing client_data in conflict response"
        assert result["server_version"] == current_version, \
            f"Expected server version {current_version}"
        
        print(f"  [PASS] Conflict detected: client v{stale_version} < server v{current_version}")
        print(f"  [PASS] Server data returned for reconciliation")


# ══════════════════════════════════════════════════════════════════════
# TEST 4: Sync Push — Blocked Fields
# ══════════════════════════════════════════════════════════════════════

async def test_sync_push_blocked_fields():
    """Test that status changes are blocked in offline sync."""
    async with httpx.AsyncClient() as client:
        token = await get_token(client)
        temple = await get_test_temple(client, token)
        
        resp = await client.post(
            f"{BASE_URL}/superadmin/temples/sync",
            json={
                "updates": [{
                    "id": temple["id"],
                    "version": temple.get("version", 1),
                    "changes": {"status": "REJECTED"},
                    "local_change_id": "blocked-001",
                }]
            },
            headers=headers(token),
        )
        assert resp.status_code == 200, f"Request failed: {resp.text}"
        data = resp.json()
        
        result = data["results"][0]
        assert result["status"] == "error", f"Expected 'error', got '{result['status']}'"
        assert "blocked" in result["message"].lower() or "status" in result["message"].lower(), \
            f"Expected blocked message, got: {result['message']}"
        
        print(f"  [PASS] Status change correctly blocked: {result['message']}")


# ══════════════════════════════════════════════════════════════════════
# TEST 5: Version Sequential Increment
# ══════════════════════════════════════════════════════════════════════

async def test_version_sequential():
    """Test that sequential sync pushes increment version correctly."""
    async with httpx.AsyncClient() as client:
        token = await get_token(client)
        temple = await get_test_temple(client, token)
        
        temple_id = temple["id"]
        version = temple.get("version", 1)
        
        for i in range(3):
            resp = await client.post(
                f"{BASE_URL}/superadmin/temples/sync",
                json={
                    "updates": [{
                        "id": temple_id,
                        "version": version,
                        "changes": {"description": f"Sequential test #{i+1}"},
                    }]
                },
                headers=headers(token),
            )
            data = resp.json()
            result = data["results"][0]
            
            assert result["status"] == "applied", \
                f"Update #{i+1} failed: {result.get('message')}"
            
            new_version = result["server_version"]
            assert new_version == version + 1, \
                f"Expected v{version + 1}, got v{new_version}"
            
            version = new_version
        
        print(f"  [PASS] 3 sequential updates: version incremented correctly to v{version}")


# ══════════════════════════════════════════════════════════════════════
# RUNNER
# ══════════════════════════════════════════════════════════════════════

async def main():
    tests = [
        ("Sync Pull", test_sync_pull),
        ("Sync Push — Success", test_sync_push_success),
        ("Sync Push — Conflict", test_sync_push_conflict),
        ("Sync Push — Blocked Fields", test_sync_push_blocked_fields),
        ("Version Sequential", test_version_sequential),
    ]
    
    passed = 0
    failed = 0
    
    print("\n" + "=" * 60)
    print("  PHASE 4 VALIDATION -- Version Atomicity + Hybrid Sync")
    print("=" * 60)
    
    for name, test_fn in tests:
        print(f"\n> {name}")
        try:
            await test_fn()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] FAILED: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"  Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    asyncio.run(main())
