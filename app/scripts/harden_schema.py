import asyncio
from sqlalchemy import text
from app.core.database import engine

async def update_schema():
    async with engine.begin() as conn:
        print("Modifying schema for hardening...")

        # 1. Add fields to audit_logs
        try:
            await conn.execute(text("ALTER TABLE audit_logs ADD COLUMN approval_id UUID;"))
        except Exception as e: print(e)
        try:
            await conn.execute(text("ALTER TABLE audit_logs ADD COLUMN content_hash VARCHAR;"))
        except Exception as e: print(e)

        # 2. Add notifications table
        print("Creating notifications table...")
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS notifications (
                id UUID PRIMARY KEY,
                temple_id UUID NOT NULL,
                user_id UUID,
                role VARCHAR,
                title VARCHAR NOT NULL,
                message TEXT NOT NULL,
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now())
            );
        """))

        # 3. Create Audit Log Immutability Triggers
        print("Creating audit log immutability triggers...")
        await conn.execute(text("""
            CREATE OR REPLACE FUNCTION prevent_audit_modification()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Audit logs are strictly immutable. Updates and deletions are forbidden.';
            END;
            $$ LANGUAGE plpgsql;
        """))

        await conn.execute(text("DROP TRIGGER IF EXISTS no_update_delete_audit ON audit_logs;"))
        await conn.execute(text("""
            CREATE TRIGGER no_update_delete_audit
            BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW EXECUTE FUNCTION prevent_audit_modification();
        """))

        print("Hardening schema updated successfully!")

if __name__ == "__main__":
    asyncio.run(update_schema())
