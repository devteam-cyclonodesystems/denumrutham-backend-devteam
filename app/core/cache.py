import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class GlobalConfigurationCache:
    _cache: Dict[str, Any] = {}

    @classmethod
    def get(cls, key: str) -> Optional[Any]:
        val = cls._cache.get(key)
        if val is not None:
            logger.info("[GlobalConfigurationCache] Cache hit for key: %s", key)
        return val

    @classmethod
    def set(cls, key: str, value: Any) -> None:
        logger.info("[GlobalConfigurationCache] Cache set for key: %s", key)
        cls._cache[key] = value

    @classmethod
    def invalidate(cls, key: str) -> None:
        logger.info("[GlobalConfigurationCache] Cache invalidated for key: %s", key)
        if key in cls._cache:
            del cls._cache[key]

    @classmethod
    def invalidate_all(cls) -> None:
        logger.info("[GlobalConfigurationCache] Cache invalidated all keys")
        cls._cache.clear()
