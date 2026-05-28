import asyncio
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import AsyncSessionLocal
from app.models.domain import User, UserStatus
from app.services.audit_service import AuditService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("cleanup_pending_accounts")

async def cleanup_pending_accounts():
    """
    Identifies staff accounts in PENDING_APPROVAL state for more than 14 days
    and transitions them to DISABLED state to prevent onboarding bloat.
    """
    expiration_threshold = datetime.now(timezone.utc) - timedelta(days=14)
    
    async with AsyncSessionLocal() as db:
        async with db.begin():
            # Find expired pending accounts
            stmt = select(User).filter(
                User.status == "PENDING_APPROVAL",
                User.created_at < expiration_threshold,
                User.is_active == True
            )
            result = await db.execute(stmt)
            expired_users = result.scalars().all()
            
            if not expired_users:
                logger.info("No expired pending accounts found.")
                return

            for user in expired_users:
                logger.info(f"Expiring account: {user.user_id} (Created: {user.created_at})")
                
                # Transition state
                user.status = "DISABLED"
                user.is_active = False # Effectively deactivate
                
                # Audit log
                await AuditService.log_event(
                    db=db,
                    temple_id=user.temple_id,
                    user_id=None, # System action
                    action="STAFF_EXPIRED",
                    resource="USER",
                    resource_id=user.id,
                    details={
                        "reason": "Pending approval threshold (14 days) exceeded",
                        "created_at": user.created_at.isoformat()
                    }
                )
            
            await db.commit()
            logger.info(f"Successfully expired {len(expired_users)} pending accounts.")

if __name__ == "__main__":
    asyncio.run(cleanup_pending_accounts())
