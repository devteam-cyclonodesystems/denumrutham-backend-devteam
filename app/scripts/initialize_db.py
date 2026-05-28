import asyncio
from app.core.database import engine, Base, AsyncSessionLocal
from app.models.domain import User 
from app.models.rbac import Role, UserRole
from app.core.config import settings
import seed_test_data
import create_admin

async def main():
    print(f"DATABASE_URL used: {settings.DATABASE_URL}")
    print("Ensuring schema...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Schema verified.")
    
    print("Running seed_test_data.main()...")
    await seed_test_data.main()
    
    print("Running create_admin.create_admin()...")
    await create_admin.create_admin()
    
    # Final check in this script's session
    async with AsyncSessionLocal() as db:
        from sqlalchemy import text
        res = await db.execute(text("SELECT count(*) FROM users"))
        count = res.scalar()
        print(f"Users count in this session: {count}")
        await db.commit()
    
    print("Consolidation complete.")

if __name__ == "__main__":
    asyncio.run(main())
