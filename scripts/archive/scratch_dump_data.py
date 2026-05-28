import asyncio
import sys
import os
from sqlalchemy import text

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), 'backend')))

from app.core.database import engine

async def dump_data():
    async with engine.connect() as conn:
        print("--- TEMPLE REQUESTS ---")
        res = await conn.execute(text("SELECT * FROM temple_requests"))
        rows = res.all()
        print(f"Total: {len(rows)}")
        for row in rows:
            print(row)
            
        print("\n--- USERS ---")
        res = await conn.execute(text("SELECT user_id, email, role, status FROM users"))
        rows = res.all()
        print(f"Total: {len(rows)}")
        for row in rows:
            print(row)

if __name__ == "__main__":
    asyncio.run(dump_data())
