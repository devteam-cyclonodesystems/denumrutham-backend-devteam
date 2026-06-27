"""
Query startup verification reports from the database.
"""
import asyncio
from sqlalchemy import text

async def main():
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("""
            SELECT id, status, details, verified_at 
            FROM audit_integrity_verification_reports 
            ORDER BY verified_at DESC 
            LIMIT 10
        """))
        rows = res.fetchall()
        print(f"Found {len(rows)} startup reports:")
        for r in rows:
            print("-" * 50)
            print(f"ID: {r[0]} | Status: {r[1]} | Verified At: {r[3]}")
            print(f"Details:\n{r[2]}")
        print("-" * 50)

if __name__ == "__main__":
    asyncio.run(main())
