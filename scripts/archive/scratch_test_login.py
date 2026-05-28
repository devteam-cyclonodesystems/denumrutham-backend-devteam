import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))

import app.models
from app.core.database import AsyncSessionLocal
from app.services.registration_service import RegistrationService

async def test_login():
    async with AsyncSessionLocal() as db:
        username = "admin"
        password = "AdminPassword123!"
        try:
            res = await RegistrationService.login_with_redirect(db, username, password)
            print("Login SUCCESS")
            print(f"Token: {res['access_token'][:20]}...")
            print(f"Redirect: {res['redirect_url']}")
        except Exception as e:
            print(f"Login FAILED: {e}")

if __name__ == "__main__":
    asyncio.run(test_login())
