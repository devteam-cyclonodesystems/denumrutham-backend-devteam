import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def run():
    url = "postgresql+asyncpg://neondb_owner:npg_6Ii0uTBKbaZP@ep-old-queen-aoeyozad-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    engine = create_async_engine(url, connect_args={"ssl": True})
    async with engine.connect() as conn:
        try:
            print("Querying alembic version...")
            res = await conn.execute(text("SELECT version_num FROM alembic_version;"))
            print("Current Alembic Version:", res.scalar())
            
            print("\nQuerying columns of archana_execution_groups:")
            res = await conn.execute(text("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'archana_execution_groups';
            """))
            for row in res.fetchall():
                print(f"Column: {row[0]}, Type: {row[1]}")
                
            print("\nQuerying columns of archana_executions:")
            res = await conn.execute(text("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = 'archana_executions';
            """))
            for row in res.fetchall():
                print(f"Column: {row[0]}, Type: {row[1]}")
                
        except Exception as e:
            print("Error connecting/querying production DB:")
            print(str(e))
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(run())
