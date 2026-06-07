import os
import sys
import asyncio

# Set database URL to local SQLite file
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///tms_local_sqlite.db"

# Add current directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core.database import engine, Base
from app.models.domain import Temple
from app.scripts import seed_test_data, create_admin
from app.scripts.validate_slugs import main as run_validation

async def run_setup():
    print("Setting up local SQLite database...")
    async with engine.begin() as conn:
        # Recreate tables
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("Database schema created.")
    
    import subprocess
    print("Stamping database with Alembic migration head...")
    subprocess.run(["python", "-m", "alembic", "stamp", "add_website_publication_snapshots"], check=True)
    print("Alembic stamped.")
    
    print("Seeding test data...")
    await seed_test_data.main()
    await create_admin.create_admin()
    print("Seeding completed.")
    
    # Insert legacy temples to verify slug generator
    print("Inserting legacy temples with missing or conflicting domains...")
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        t1 = Temple(name="Legacy Temple 1", domain="legacy_temple_1")  # Underscores (invalid)
        t2 = Temple(name="Legacy Temple @ Special!", domain="legacy temple special")  # Spaces (invalid)
        session.add_all([t1, t2])
        await session.commit()
    print("Legacy temples inserted.")

async def main():
    await run_setup()
    
    # Run the validation
    await run_validation()

if __name__ == "__main__":
    if sys.platform == "win32":
        try:
            from asyncio import WindowsSelectorEventLoopPolicy
            asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())
        except ImportError:
            pass
    asyncio.run(main())
