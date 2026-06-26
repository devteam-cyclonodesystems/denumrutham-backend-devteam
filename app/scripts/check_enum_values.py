"""
Check current PostgreSQL enum values for queuestatus.
"""
import asyncio
from sqlalchemy import text

async def main():
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        # Check existing enum values
        res = await db.execute(text("""
            SELECT enumlabel 
            FROM pg_enum 
            JOIN pg_type ON pg_enum.enumtypid = pg_type.oid 
            WHERE pg_type.typname = 'queuestatus'
            ORDER BY enumsortorder
        """))
        vals = [r[0] for r in res.fetchall()]
        print(f"Current queuestatus enum values: {vals}")
        
        # Also check arcanastatus
        res2 = await db.execute(text("""
            SELECT enumlabel 
            FROM pg_enum 
            JOIN pg_type ON pg_enum.enumtypid = pg_type.oid 
            WHERE pg_type.typname = 'archanastatus'
            ORDER BY enumsortorder
        """))
        vals2 = [r[0] for r in res2.fetchall()]
        print(f"Current archanastatus enum values: {vals2}")

if __name__ == "__main__":
    asyncio.run(main())
