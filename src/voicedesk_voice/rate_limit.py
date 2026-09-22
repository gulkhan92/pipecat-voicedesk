"""Phase 8: per-IP rate limiting for new call sessions.

Protects the free-tier STT/LLM quotas from being exhausted by a single
source opening many call sessions, independent of the per-provider request
budget in quota.py (which limits API calls once a call is already running).
"""

import time

import redis.asyncio as redis

from voicedesk_voice.config import CALL_START_RATE_LIMIT, CALL_START_RATE_WINDOW_SECS, REDIS_URL

_redis: redis.Redis | None = None


def _client() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


class RateLimitExceeded(Exception):
    """Raised when a client has started too many calls too recently."""


async def check_and_record_call_start(client_ip: str) -> None:
    """Record a call start for ``client_ip`` and raise if over budget.

    Uses a fixed window keyed by the current window start, so the limit
    resets cleanly every CALL_START_RATE_WINDOW_SECS rather than needing a
    sliding-window computation.

    Raises:
        RateLimitExceeded: If this IP has already started
            CALL_START_RATE_LIMIT calls in the current window.
    """
    window = int(time.time() // CALL_START_RATE_WINDOW_SECS)
    key = f"voicedesk:call_start:{client_ip}:{window}"

    client = _client()
    async with client.pipeline(transaction=True) as pipe:
        pipe.incr(key)
        pipe.expire(key, CALL_START_RATE_WINDOW_SECS * 2)
        count, _ = await pipe.execute()

    if count > CALL_START_RATE_LIMIT:
        raise RateLimitExceeded(
            f"{client_ip} started {count} calls in the last "
            f"{CALL_START_RATE_WINDOW_SECS}s (limit {CALL_START_RATE_LIMIT})"
        )
