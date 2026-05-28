import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def run():
    engine = create_async_engine('postgresql+asyncpg://postgres:postgres@localhost:5433/tms_postgres')
    async with engine.connect() as conn:
        try:
            await conn.execute(text("INSERT INTO temples (id, name, domain, status, version) VALUES (gen_random_uuid(), 'Test Temple', 'test-temple', 'active', 1);"))
            await conn.commit()
            print("SUCCESS: Inserted invalid status (THIS SHOULD NOT HAPPEN)")
        except Exception as e:
            print("FAILED to insert invalid status (THIS IS EXPECTED AND GOOD)")
            print(str(e))
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(run())
