"""
Create a SuperAdmin user for the Denumrutham Temple Management System.

Usage:
    cd backend
    python create_superadmin.py

This script:
 - Prompts for a username (user_id) and password
 - Creates a new User with role = SUPERADMIN and no temple_id
 - Uses the same DB URL from the .env file / environment
"""

import os
import sys
import getpass
import asyncio

# Safety Guard: Ensure script runs inside Docker
if not os.getenv("TMS_CONTAINER"):
    print("\n[!] ERROR: This script must be run inside the Docker container.")
    print("[!] Use: ./manage.ps1 create_superadmin.py (Windows)")
    print("[!] Or : ./manage.sh create_superadmin.py (Linux/macOS)\n")
    sys.exit(1)

# Allow running from the backend directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.database import AsyncSessionLocal
from app.core.security import get_password_hash
from app.models.domain import User
from sqlalchemy.future import select


async def main():
    print("=" * 50)
    print("  Denumrutham — Create SuperAdmin User")
    print("=" * 50)

    user_id = input("Enter SuperAdmin username (user_id): ").strip()
    if not user_id:
        print("[ERROR] Username cannot be empty.")
        return

    password = getpass.getpass("Enter password: ")
    if len(password) < 6:
        print("[ERROR] Password must be at least 6 characters.")
        return

    async with AsyncSessionLocal() as db:
        # Check if user_id already exists
        result = await db.execute(select(User).filter(User.user_id == user_id))
        existing = result.scalars().first()

        if existing:
            # Update existing user to SUPERADMIN
            existing.role = "SUPERADMIN"
            existing.password_hash = get_password_hash(password)
            existing.temple_id = None  # SuperAdmin has no fixed tenant
            await db.commit()
            print(f"\n[OK] Updated existing user '{user_id}' → role=SUPERADMIN, temple_id cleared.")
        else:
            # Create new SUPERADMIN user
            new_user = User(
                user_id=user_id,
                password_hash=get_password_hash(password),
                role="SUPERADMIN",
                temple_id=None,
            )
            db.add(new_user)
            await db.commit()
            print(f"\n[OK] Created SuperAdmin user: '{user_id}'")

    print("\nYou can now log in at the frontend with these credentials.")
    print("After login you will be directed to the Temple Selector page.")


if __name__ == "__main__":
    asyncio.run(main())


from passlib.context import CryptContext

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
print(pwd.hash("superadmin123"))