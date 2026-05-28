import asyncio
from app.core.database import engine
from sqlalchemy import text

async def test():
    try:
        async with engine.connect() as conn:
            await conn.execute(text('SELECT 1'))
            print('DB CONNECTED ✅')
    except Exception as e:
        print(f'DB CONNECTION FAILED ❌: {e}')
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(test())
