import asyncio
import traceback
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from uuid import UUID

async def run():
    db_url = "postgresql+asyncpg://neondb_owner:npg_R3hWbAYn0tuI@ep-proud-shadow-aom9gssv-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb"
    engine = create_async_engine(db_url, connect_args={"ssl": True})
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    temple_id = "b400aa3d-ecd3-4ed9-b6f6-2572bc59d069" # Demo Temple ID
    
    async with AsyncSessionLocal() as db:
        print("=== RUNNING DashboardService.get_summary ===")
        try:
            # Import service
            from app.services.dashboard_service import DashboardService
            
            # Run get_summary
            res = await DashboardService.get_summary(db, temple_id)
            print("DashboardService.get_summary: SUCCESS!")
            print("Response keys:", list(res.keys()))
            print("Response:", res)
        except Exception as e:
            print("DashboardService.get_summary: FAILED!")
            traceback.print_exc()

    await engine.dispose()

if __name__ == "__main__":
    import sys
    # Add app to python path
    import os
    sys.path.append(os.path.abspath('.'))
    asyncio.run(run())
