import asyncio
import logging
from app.core.database import AsyncSessionLocal
from app.services.onboarding_service import OnboardingService
from sqlalchemy.future import select
from app.models.onboarding import TempleRequest, UserRequest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test():
    async with AsyncSessionLocal() as db:
        query = (
            select(TempleRequest, UserRequest)
            .outerjoin(UserRequest, UserRequest.temple_request_id == TempleRequest.id)
            .where(TempleRequest.status == "PENDING")
            .order_by(TempleRequest.created_at.desc())
        )
        result = await db.execute(query)
        rows = result.all()
        logger.info(f"Query Rows: {len(rows)}")
        for r in rows:
            logger.info(f"Row: {r}")

        items = await OnboardingService.list_pending_requests(db)
        logger.info(f"Service returned: {items}")

if __name__ == "__main__":
    asyncio.run(test())
