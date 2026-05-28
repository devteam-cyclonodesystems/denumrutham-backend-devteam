import asyncio
from app.core.database import engine, Base, AsyncSessionLocal
from app.models.domain import User 
from app.models.rbac import Role, UserRole
from app.core.config import settings
import seed_test_data
import create_admin

async def main():
    print(f"DATABASE_URL used: {settings.DATABASE_URL}")
    print("Resetting schema (dropping and recreating)...")
    async with engine.begin() as conn:
        # Import models here to ensure they are registered with Base.metadata
        from app.models import domain, rbac
        
        # Drop all tables first for a clean reset as approved in the plan
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("Schema initialized.")
    
    print("Running seed_test_data.main()...")
    import seed_test_data
    await seed_test_data.main()
    
    print("Running create_admin.create_admin()...")
    import create_admin
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
