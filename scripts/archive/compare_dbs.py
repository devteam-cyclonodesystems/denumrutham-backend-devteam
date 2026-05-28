import asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

async def check_all_dbs():
    dbs = ["postgres", "tms"]
    for db_name in dbs:
        url = f"postgresql+asyncpg://postgres:postgres@localhost:5433/{db_name}"
        print(f"--- Checking {db_name} ---")
        try:
            engine = create_async_engine(url)
            session_factory = async_sessionmaker(bind=engine, class_=AsyncSession)
            async with session_factory() as db:
                result = await db.execute(text("SELECT user_id FROM users"))
                rows = result.fetchall()
                print(f"Users: {[r[0] for r in rows]}")
        except Exception as e:
            print(f"Error checking {db_name}: {e}")

if __name__ == "__main__":
    asyncio.run(check_all_dbs())
