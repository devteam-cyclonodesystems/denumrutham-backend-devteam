import asyncio
import httpx
import os
import time

BASE_URL = os.getenv("TMS_API_URL", "http://localhost:8000/api/v1")

async def test_performance():
    async with httpx.AsyncClient() as client:
        # get token
        resp = await client.post(
            f"{BASE_URL}/auth/login",
            data={"username": "superadmin", "password": "superadmin123"},
        )
        if resp.status_code != 200:
            print(f"Login failed: {resp.text}")
            return
        
        token = resp.json().get("access_token")
        if not token and "data" in resp.json():
            token = resp.json()["data"]["access_token"]
            
        headers = {"Authorization": f"Bearer {token}"}
        
        # fire 50 requests
        print("Firing 50 concurrent requests...")
        start_time = time.time()
        
        async def fetch():
            return await client.get(f"{BASE_URL}/superadmin/temples/", headers=headers)
            
        tasks = [fetch() for _ in range(50)]
        results = await asyncio.gather(*tasks)
        
        end_time = time.time()
        
        successes = sum(1 for r in results if r.status_code == 200)
        print(f"Successes: {successes}/50")
        print(f"Time taken: {end_time - start_time:.2f}s")
        if successes == 50:
            print("[PASS] Performance + Stress Test")
        else:
            print("[FAIL] Performance + Stress Test")

if __name__ == "__main__":
    asyncio.run(test_performance())
