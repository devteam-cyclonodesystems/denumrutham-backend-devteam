import asyncio
from sqlalchemy import text
from app.core.database import engine

async def update_schema():
    async with engine.begin() as conn:
        print("Adding columns to audit_logs...")
        # Ignore errors if columns already exist
        try:
            await conn.execute(text("ALTER TABLE audit_logs ADD COLUMN role VARCHAR;"))
        except Exception as e: print(e)
        try:
            await conn.execute(text("ALTER TABLE audit_logs ADD COLUMN module_name VARCHAR;"))
        except Exception as e: print(e)
        try:
            await conn.execute(text("ALTER TABLE audit_logs ADD COLUMN action_type VARCHAR;"))
        except Exception as e: print(e)
        try:
            await conn.execute(text("ALTER TABLE audit_logs ADD COLUMN entity_id VARCHAR;"))
        except Exception as e: print(e)
        try:
            await conn.execute(text("ALTER TABLE audit_logs ADD COLUMN old_value JSON;"))
        except Exception as e: print(e)
        try:
            await conn.execute(text("ALTER TABLE audit_logs ADD COLUMN new_value JSON;"))
        except Exception as e: print(e)
        try:
            await conn.execute(text("ALTER TABLE audit_logs ADD COLUMN ip_address VARCHAR;"))
        except Exception as e: print(e)

        print("Creating approval_requests table...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS approval_requests (
                id UUID PRIMARY KEY,
                temple_id UUID NOT NULL,
                module VARCHAR NOT NULL,
                entity_id VARCHAR,
                requested_by UUID NOT NULL,
                request_payload JSON NOT NULL,
                status VARCHAR DEFAULT 'pending',
                reviewed_by UUID,
                reviewed_at TIMESTAMP WITH TIME ZONE,
                remarks TEXT,
                created_at TIMESTAMP WITH TIME ZONE
            );
        """))
        print("Schema updated successfully!")

if __name__ == "__main__":
    asyncio.run(update_schema())
