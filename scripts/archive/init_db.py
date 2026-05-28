import asyncio
import os
import sys

# Ensure backend directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.database import engine
from app.db.session import Base
from app.models.domain import Temple, User, Devotee, Pooja, Booking  # register all models
from app.models.rbac import Role, Permission, RolePermission, UserRole

async def init_db():
    print("Initializing Database with app.db.session.Base...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Done.")

if __name__ == "__main__":
    asyncio.run(init_db())
