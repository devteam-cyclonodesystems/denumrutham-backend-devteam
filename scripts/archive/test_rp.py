import asyncio
import uuid
from app.core.database import AsyncSessionLocal as SessionLocal
from sqlalchemy import text

async def main():
    async with SessionLocal() as db:
        res = await db.execute(text('SELECT * FROM role_permissions;'))
        rows = res.fetchall()
        print("TOTAL RP ROWS:", len(rows))
        for r in rows:
            print(r)

if __name__ == "__main__":
    asyncio.run(main())
