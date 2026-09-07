from redis.asyncio import Redis

from app.core.config import Settings


def build_redis_client(settings: Settings) -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)
