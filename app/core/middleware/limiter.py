from slowapi import Limiter
from slowapi.util import get_remote_address
from app.core.config import settings

# Global limiter instance
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.REDIS_URL,
    default_limits=["200/minute"],
    in_memory_fallback_enabled=True
)
