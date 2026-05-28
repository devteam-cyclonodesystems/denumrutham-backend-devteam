import asyncio
from sqlalchemy import text
from app.core.database import engine

async def migrate_columns():
    tables = [
        "users", "devotees", "poojas", "pooja_slots", "bookings",
        "donations", "inventory_items", "inventory_movements",
        "events", "tickets", "payments", "audit_logs",
        "roles", "permissions"
    ]

    async with engine.begin() as conn:
        for table in tables:
            try:
                # Check if column exists
                result = await conn.execute(text(f"""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='{table}' and column_name='tenant_id';
                """))
                if result.scalar():
                    print(f"Migrating {table}...")
                    
                    # Instead of RENAME COLUMN which can be tricky with indexes and foreign keys,
                    # PostgreSQL supports RENAME COLUMN safely propagating to indexes and foreign keys.
                    await conn.execute(text(f"ALTER TABLE {table} RENAME COLUMN tenant_id TO temple_id;"))
                    
                    # Backfill NULLs to a safe temple_id if necessary, assuming no NULLs exist since nullable=False
                    # except users which is nullable=True.
                    print(f"Successfully migrated {table}.")
                else:
                    print(f"Table {table} already updated or no tenant_id found.")
            except Exception as e:
                print(f"Error migrating {table}: {e}")

if __name__ == "__main__":
    asyncio.run(migrate_columns())
