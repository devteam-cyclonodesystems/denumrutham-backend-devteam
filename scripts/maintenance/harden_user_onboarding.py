import asyncio
from sqlalchemy import text
from app.core.database import engine

async def update_schema():
    async with engine.begin() as conn:
        print("Modifying users table for staff onboarding hardening...")

        # Add fields to users table
        columns = [
            ("approval_status", "VARCHAR DEFAULT 'PENDING'"),
            ("approved_by", "UUID"),
            ("approved_at", "TIMESTAMP WITH TIME ZONE"),
            ("rejected_by", "UUID"),
            ("rejected_at", "TIMESTAMP WITH TIME ZONE"),
            ("rejection_reason", "TEXT"),
            ("onboarding_method", "VARCHAR DEFAULT 'INVITE_TOKEN'")
        ]

        for col_name, col_type in columns:
            try:
                await conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type};"))
                print(f"Added column: {col_name}")
            except Exception as e:
                print(f"Column {col_name} might already exist or error: {e}")

        # Add indexes for performance
        try:
            await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_approval_status ON users (approval_status);"))
            await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_users_temple_id_approval ON users (temple_id, approval_status);"))
            print("Added performance indexes.")
        except Exception as e:
            print(f"Error adding indexes: {e}")

        print("User model schema updated successfully!")

if __name__ == "__main__":
    asyncio.run(update_schema())
