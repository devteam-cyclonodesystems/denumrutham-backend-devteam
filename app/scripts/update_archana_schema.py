import asyncio
from app.core.database import engine
from app.models.archana import Base

async def update_archana_schema():
    print("Updating Archana & Ritual Governance schema...")
    async with engine.begin() as conn:
        # Import models to ensure all are registered
        import app.models.domain
        import app.models.accounting
        await conn.run_sync(Base.metadata.create_all)
    print("Archana schema updated successfully.")

if __name__ == "__main__":
    asyncio.run(update_archana_schema())
