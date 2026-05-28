import asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

async def check_consolidated_db():
    url = "postgresql+asyncpg://postgres:postgres@localhost:5433/tms_postgres"
    print(f"--- Checking consolidated tms_postgres ---")
    try:
        engine = create_async_engine(url)
        session_factory = async_sessionmaker(bind=engine, class_=AsyncSession)
        async with session_factory() as db:
            result = await db.execute(text("SELECT user_id FROM users"))
            rows = result.fetchall()
            print(f"Users found ({len(rows)}): {[r[0] for r in rows]}")
    except Exception as e:
        print(f"Error checking tms_postgres: {e}")

if __name__ == "__main__":
    asyncio.run(check_consolidated_db())
