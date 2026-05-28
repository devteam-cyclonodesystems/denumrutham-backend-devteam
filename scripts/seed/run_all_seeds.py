import asyncio
import logging
from app.core.database import AsyncSessionLocal
from app.scripts.seed_system_rbac import seed_system_rbac
from scripts.seed.seed_admin import seed_admin
from scripts.seed.seed_temples import seed_temples
from scripts.seed.seed_demo_data import seed_demo_data

# Set up logging format to match user's custom formatting requirement: [Seed] [Module] [Status]
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("Seed.Wrapper")

async def run_all():
    logger.info("=" * 60)
    logger.info("[Seed] [Wrapper] [STARTING] - Beginning SaaS database seeding...")
    logger.info("=" * 60)
    
    async with AsyncSessionLocal() as db:
        try:
            # 1. System RBAC seeding
            logger.info("[Seed] [RBAC] [RUNNING]")
            await seed_system_rbac(db)
            logger.info("[Seed] [RBAC] [COMPLETED]")
            
            # 2. Super Admin seeding
            logger.info("[Seed] [Admin] [RUNNING]")
            admin = await seed_admin(db)
            logger.info("[Seed] [Admin] [COMPLETED]")
            
            # 3. Temple seeding
            logger.info("[Seed] [Temple] [RUNNING]")
            temple = await seed_temples(db, admin)
            logger.info("[Seed] [Temple] [COMPLETED]")
            
            # 4. Demo Data seeding
            logger.info("[Seed] [DemoData] [RUNNING]")
            await seed_demo_data(db, temple)
            logger.info("[Seed] [DemoData] [COMPLETED]")
            
            # Commit transaction
            await db.commit()
            logger.info("=" * 60)
            logger.info("[Seed] [Wrapper] [SUCCESS] - Database seeding successfully completed.")
            logger.info("=" * 60)
            
            # Print output credentials
            print("\n" + "=" * 50)
            print("=== SEED SYSTEM RUN SUCCESSFUL ===")
            print("=" * 50)
            print("Admin Credentials:")
            print("  Username/ID: admin")
            print("  Email:       admin@denumrutham.com")
            print("  Password:    DenumruthamAdmin@2026")
            print("\nTemple Manager Credentials:")
            print("  Username/ID: manager")
            print("  Email:       manager@demotemple.org")
            print("  Password:    ManagerPass@2026")
            print("\nDevotee Credentials:")
            print("  Username/ID: devotee")
            print("  Email:       devotee@example.com")
            print("  Password:    DevoteePass@2026")
            print("=" * 50 + "\n")
            
        except Exception as e:
            logger.error(f"[Seed] [Wrapper] [FAILED] - Seeding encountered an error: {e}")
            await db.rollback()
            raise

if __name__ == "__main__":
    asyncio.run(run_all())
