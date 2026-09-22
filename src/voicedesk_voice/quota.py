"""Phase 4: Redis-backed request-quota tracking for the LLM provider layer.

Tracks a rolling requests-per-minute count per provider. A provider over its
budget is treated the same as one returning a real rate-limit error: the
ServiceSwitcher fails over to the next provider in the list.
"""

import time

import redis.asyncio as redis

from voicedesk_voice.config import REDIS_URL

_redis: redis.Redis | None = None


def _client() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


async def record_request(provider: str) -> None:
    """Record one request against the provider's current one-minute bucket."""
    bucket = int(time.time() // 60)
    key = f"voicedesk:llm_quota:{provider}:{bucket}"
    client = _client()
    async with client.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, 120)
        await pipe.execute()


async def requests_this_minute(provider: str) -> int:
    bucket = int(time.time() // 60)
    key = f"voicedesk:llm_quota:{provider}:{bucket}"
    value = await _client().get(key)
    return int(value) if value else 0


async def is_quota_exceeded(provider: str, limit: int) -> bool:
    return await requests_this_minute(provider) >= limit
