import json
import logging
from redis import asyncio as aioredis
from uuid import UUID
from app.core.config import settings

logger = logging.getLogger(__name__)

class BroadcastService:
    """
    Handles real-time event broadcasting via Redis Pub/Sub.
    Used for cross-instance invalidation (WebSockets, Cache, etc.)
    """
    
    _redis = None

    @classmethod
    async def get_redis(cls):
        if cls._redis is None:
            cls._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return cls._redis

    @classmethod
    async def publish_tenant_event(cls, temple_id: UUID, event_type: str, data: dict = None):
        """
        Publish an event to the tenant-specific channel.
        Channels are formatted as 'tenant:{temple_id}'
        """
        try:
            redis = await cls.get_redis()
            payload = {
                "event": event_type,
                "temple_id": str(temple_id),
                "data": data or {}
            }
            channel = f"tenant:{str(temple_id)}"
            await redis.publish(channel, json.dumps(payload))
            
            # Also publish to a global security channel for cross-tenant monitoring
            if event_type in ["SESSION_INVALIDATION", "SECURITY_RESET", "TENANT_SUSPENDED"]:
                await redis.publish("security_events", json.dumps(payload))
                
            logger.info("Published %s event for tenant %s", event_type, temple_id)
        except Exception as e:
            logger.error("Failed to publish broadcast event: %s", str(e))

    @classmethod
    async def force_logout_tenant(cls, temple_id: UUID, reason: str = "Administrative action"):
        """
        Triggers immediate logout for all users of a specific tenant.
        """
        await cls.publish_tenant_event(temple_id, "SESSION_INVALIDATION", {"reason": reason})
