import asyncio
import httpx
from app.core.security import create_access_token
from app.core.config import settings

async def test_api():
    token = create_access_token(
        subject="a5b90570-45e1-4161-a793-bef1983e456d", 
        role="SUPER_ADMIN",
        username="superadmin"
    )
    
    async with httpx.AsyncClient() as client:
        url = "http://localhost:8000/api/v1/admin/onboarding/temple-requests?status_filter=PENDING"
        headers = {"Authorization": f"Bearer {token}"}
        response = await client.get(url, headers=headers)
        print(f"Status: {response.status_code}")
        print(f"Body: {response.text}")

if __name__ == "__main__":
    asyncio.run(test_api())
