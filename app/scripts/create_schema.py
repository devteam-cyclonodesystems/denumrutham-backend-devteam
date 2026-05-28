import asyncio
from app.core.database import engine, Base
# Import all models to ensure they are registered with Base.metadata
from app.models import *

async def main():
    print("Updating schema...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("Schema update complete.")

if __name__ == "__main__":
    asyncio.run(main())
