from typing import Any

from app.config import settings
from app.logging import logger

try:
    import redis.asyncio as aioredis

    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False


class RedisManager:
    """Manages Redis connection with graceful fallback for standalone mode."""

    def __init__(self) -> None:
        self._client: Any | None = None

    async def get_client(self):
        """Get or initialize async redis connection."""
        if not _REDIS_AVAILABLE:
            logger.warning("Redis library not available or running in standalone mode.")
            return None
        if self._client is None and settings.redis_url:
            try:
                self._client = aioredis.from_url(
                    settings.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                )
            except Exception as exc:
                logger.warning(f"Could not connect to Redis: {exc}")
                return None
        return self._client


redis_manager = RedisManager()


async def get_redis_client():
    return await redis_manager.get_client()
