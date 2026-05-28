"""
add_temple_columns.py — Migration to add 'status' and 'location' columns to the 'temples' table.
Run this once before using the new SuperAdmin CRUD endpoints.

Usage:
    python add_temple_columns.py
"""
import asyncio
from sqlalchemy import text
from app.core.database import engine


async def main():
    print("=" * 50)
    print("  Adding 'status' and 'location' columns to temples table")
    print("=" * 50)

    async with engine.begin() as conn:
        # Check if columns already exist
        result = await conn.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'temples' AND column_name IN ('status', 'location')
        """))
        existing = [row[0] for row in result.fetchall()]

        if 'status' not in existing:
            await conn.execute(text(
                "ALTER TABLE temples ADD COLUMN status VARCHAR DEFAULT 'active'"
            ))
            print("  ✅ Added 'status' column")
        else:
            print("  ⏭️  'status' column already exists")

        if 'location' not in existing:
            await conn.execute(text(
                "ALTER TABLE temples ADD COLUMN location VARCHAR DEFAULT ''"
            ))
            print("  ✅ Added 'location' column")
        else:
            print("  ⏭️  'location' column already exists")

        # Backfill: set status='active' for any rows with NULL status
        await conn.execute(text(
            "UPDATE temples SET status = 'active' WHERE status IS NULL"
        ))

        # Backfill: copy location from temple_profiles if available
        await conn.execute(text("""
            UPDATE temples t
            SET location = tp.location
            FROM temple_profiles tp
            WHERE tp.temple_id = t.id
              AND (t.location IS NULL OR t.location = '')
              AND tp.location IS NOT NULL
              AND tp.location != ''
        """))

    print("  ✅ Migration complete!")


if __name__ == "__main__":
    asyncio.run(main())
