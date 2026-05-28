import asyncio
from app.core.database import engine
from app.models.accounting import Base

async def create_schema():
    print("Creating Enterprise Accounting schema...")
    async with engine.begin() as conn:
        # Import other models to ensure FKs work if needed
        import app.models.domain
        import app.models.archana
        await conn.run_sync(Base.metadata.create_all)
    print("Accounting schema created successfully.")

if __name__ == "__main__":
    asyncio.run(create_schema())
