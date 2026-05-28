import asyncio
import asyncpg

async def create_new_db():
    # Connect to the default 'postgres' database
    conn = await asyncpg.connect(user='postgres', password='postgres', host='localhost', database='postgres')
    new_db = "tms_postgres"
    print(f"Checking if database {new_db} exists...")
    
    try:
        # Check if it exists
        exists = await conn.fetchval(f"SELECT 1 FROM pg_database WHERE datname = '{new_db}'")
        if not exists:
            # CREATE DATABASE cannot run in a transaction block
            await conn.execute(f"CREATE DATABASE {new_db}")
            print(f"Successfully created {new_db}")
        else:
            print(f"Database {new_db} already exists.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(create_new_db())
