import asyncio
from sqlalchemy import select, create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

async def check_tms_db():
    url = "postgresql+asyncpg://postgres:postgres@localhost:5433/tms"
    print(f"Checking {url}...")
    try:
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(bind=engine, class_=AsyncSession)
        async with session_factory() as db:
            result = await db.execute(text("SELECT user_id FROM users"))
            rows = result.fetchall()
            print(f"Users in 'tms' DB: {[r[0] for r in rows]}")
    except Exception as e:
        print(f"Error checking 'tms' DB: {e}")

if __name__ == "__main__":
    asyncio.run(check_tms_db())
