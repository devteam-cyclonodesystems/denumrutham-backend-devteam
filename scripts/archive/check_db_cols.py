import asyncio
from sqlalchemy import text
from app.core.database import engine

async def check_cols():
    async with engine.begin() as conn:
        result = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'temples'"
        ))
        rows = result.fetchall()
        print("Columns in 'temples':")
        for row in rows:
            print(f" - {row[0]}")

if __name__ == "__main__":
    asyncio.run(check_cols())
