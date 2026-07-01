import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def run():
    url = "postgresql+asyncpg://neondb_owner:npg_6Ii0uTBKbaZP@ep-old-queen-aoeyozad-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    engine = create_async_engine(url, connect_args={"ssl": True})
    async with engine.connect() as conn:
        try:
            print("=== PRODUCTION USERS ===")
            query = "SELECT id, user_id, email, role, status, approval_status, temple_id, name FROM users LIMIT 20;"
            res = await conn.execute(text(query))
            for row in res.fetchall():
                print(f"ID: {row[0]}, Username: {row[1]}, Email: {row[2]}, Role: {row[3]}, Status: {row[4]}, Approval: {row[5]}, Temple: {row[6]}, Name: {row[7]}")
                
            print("\n=== PRODUCTION ROLES ===")
            query_r = "SELECT id, name, temple_id, is_active FROM roles LIMIT 20;"
            res_r = await conn.execute(text(query_r))
            for row in res_r.fetchall():
                print(f"ID: {row[0]}, Name: {row[1]}, Temple: {row[2]}, Active: {row[3]}")
                
            print("\n=== USER ROLES MAPPING ===")
            query_ur = "SELECT user_id, role_id, temple_id FROM user_roles;"
            res_ur = await conn.execute(text(query_ur))
            for row in res_ur.fetchall():
                print(f"User: {row[0]} -> Role: {row[1]} in Temple: {row[2]}")
                
        except Exception as e:
            print("Error connecting/querying production DB:")
            print(str(e))
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(run())
