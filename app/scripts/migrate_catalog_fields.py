"""Add malayalam_name and remarks columns to archana_catalog table."""
import asyncio
from sqlalchemy import text
from app.core.database import engine

async def migrate():
    async with engine.begin() as conn:
        # Add malayalam_name column if not exists
        await conn.execute(text("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                    WHERE table_name='archana_catalog' AND column_name='malayalam_name') THEN
                    ALTER TABLE archana_catalog ADD COLUMN malayalam_name VARCHAR;
                END IF;
            END $$;
        """))
        # Add remarks column if not exists  
        await conn.execute(text("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                    WHERE table_name='archana_catalog' AND column_name='remarks') THEN
                    ALTER TABLE archana_catalog ADD COLUMN remarks TEXT;
                END IF;
            END $$;
        """))
        print("Migration complete: malayalam_name and remarks columns added")

if __name__ == "__main__":
    asyncio.run(migrate())
