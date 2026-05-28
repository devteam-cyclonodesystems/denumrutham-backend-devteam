import asyncio
from sqlalchemy import text
from app.core.database import engine, Base

async def migrate_columns():
    print("=" * 50)
    print("  Applying Temple CRUD Schema Enhancements")
    print("=" * 50)

    # 1. Create any missing tables (like user_temples)
    print("Ensuring tables like user_temples exist...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2. Add new columns to `temples` table if they don't exist
    new_columns = {
        "location": "VARCHAR DEFAULT ''",
        "status": "VARCHAR DEFAULT 'active'",
        "state": "VARCHAR",
        "address_line_1": "VARCHAR",
        "address_line_2": "VARCHAR",
        "district": "VARCHAR",
        "pincode": "VARCHAR",
        "contact_number": "VARCHAR",
        "alternate_contact": "VARCHAR",
        "email": "VARCHAR",
        "description": "TEXT",
        "updated_at": "TIMESTAMP WITH TIME ZONE",
        "created_by": "UUID"
    }

    async with engine.begin() as conn:
        result = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'temples'"
        ))
        existing_cols = [row[0] for row in result.fetchall()]

        for col, col_type in new_columns.items():
            if col not in existing_cols:
                await conn.execute(text(f"ALTER TABLE temples ADD COLUMN {col} {col_type}"))
                print(f"  ✅ Added column: {col}")
            else:
                print(f"  ⏭️  Column already exists: {col}")

    print("  ✅ Schema migration complete!")

if __name__ == "__main__":
    asyncio.run(migrate_columns())
