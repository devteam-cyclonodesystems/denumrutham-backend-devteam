import asyncio
import logging
from app.core.database import engine, Base
from app.core.config import settings
from alembic.config import Config
from alembic import command

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tms.prod_init")

async def main():
    logger.info(f"Initializing database using URL: {settings.DATABASE_URL}")
    
    # 1. Create all tables defined in models via SQLAlchemy
    logger.info("Creating all tables via Base.metadata.create_all...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("All tables created successfully.")
    
    # 2. Stamp Alembic migration to 'head'
    logger.info("Stamping Alembic migration to 'head'...")
    alembic_cfg = Config("alembic.ini")
    db_url = str(settings.DATABASE_URL).replace("+asyncpg", "")
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)
    
    # Run the stamp command synchronously
    command.stamp(alembic_cfg, "head")
    logger.info("Alembic stamped to head successfully.")

if __name__ == "__main__":
    asyncio.run(main())
