import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

async def run():
    url = "postgresql+asyncpg://neondb_owner:npg_R3hWbAYn0tuI@ep-proud-shadow-aom9gssv-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb"
    engine = create_async_engine(url, connect_args={"ssl": True})
    async with engine.connect() as conn:
        try:
            print("=== PRODUCTION ARCHANA EXECUTIONS ===")
            query = """
            SELECT id, status, priest_id, started_by_user_id, completed_by_user_id, start_time, completed_at
            FROM archana_executions 
            ORDER BY updated_at DESC 
            LIMIT 20;
            """
            res = await conn.execute(text(query))
            rows = res.fetchall()
            if not rows:
                print("No executions found in production database.")
            for row in rows:
                print(f"ID: {row[0]}")
                print(f"  Status: {row[1]}")
                print(f"  Priest ID (Legacy): {row[2]} (Expected: None/NULL)")
                print(f"  Started By User ID: {row[3]}")
                print(f"  Completed By User ID: {row[4]}")
                print(f"  Start Time: {row[5]}")
                print(f"  Completed At: {row[6]}")
                print("-" * 40)
                
            print("\n=== PRODUCTION RITUAL QUEUE ===")
            query_q = """
            SELECT id, token_number, status, priest_id, actual_start_time, completed_at
            FROM ritual_queue
            ORDER BY id DESC
            LIMIT 10;
            """
            res_q = await conn.execute(text(query_q))
            rows_q = res_q.fetchall()
            if not rows_q:
                print("No queue entries found.")
            for q in rows_q:
                print(f"Queue ID: {q[0]}")
                print(f"  Token: {q[1]}")
                print(f"  Status: {q[2]}")
                print(f"  Priest ID: {q[3]} (Expected: None/NULL)")
                print(f"  Actual Start Time: {q[4]}")
                print(f"  Completed At: {q[5]}")
                print("-" * 40)
                
        except Exception as e:
            print("Error connecting/querying production DB:")
            print(str(e))
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(run())
