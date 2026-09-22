"""Phase 9: unit tests for the Redis-backed rate limiters (Phase 8), against
the live Redis instance (docker-compose), same pattern as test_retrieval.py
uses the live Postgres instance.
"""

import uuid

import pytest

from voicedesk_voice import quota, rate_limit


@pytest.fixture(autouse=True)
def _fresh_redis_client_per_test():
    # pytest-asyncio's default "function" loop scope gives each test its own
    # event loop; a Redis client created in one test can't be reused in the
    # next, since its transport is bound to the loop that created it.
    quota._redis = None
    rate_limit._redis = None


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


async def test_quota_not_exceeded_under_limit():
    provider = _unique("provider")
    for _ in range(3):
        await quota.record_request(provider)
    assert await quota.requests_this_minute(provider) == 3
    assert await quota.is_quota_exceeded(provider, limit=5) is False


async def test_quota_exceeded_over_limit():
    provider = _unique("provider")
    for _ in range(4):
        await quota.record_request(provider)
    assert await quota.is_quota_exceeded(provider, limit=3) is True


async def test_call_start_rate_limit_allows_under_budget(monkeypatch):
    monkeypatch.setattr(rate_limit, "CALL_START_RATE_LIMIT", 3)
    ip = _unique("ip")
    for _ in range(3):
        await rate_limit.check_and_record_call_start(ip)


async def test_call_start_rate_limit_blocks_over_budget(monkeypatch):
    monkeypatch.setattr(rate_limit, "CALL_START_RATE_LIMIT", 2)
    ip = _unique("ip")
    await rate_limit.check_and_record_call_start(ip)
    await rate_limit.check_and_record_call_start(ip)
    with pytest.raises(rate_limit.RateLimitExceeded):
        await rate_limit.check_and_record_call_start(ip)


async def test_call_start_rate_limit_tracks_ips_independently(monkeypatch):
    monkeypatch.setattr(rate_limit, "CALL_START_RATE_LIMIT", 1)
    ip_a, ip_b = _unique("ip"), _unique("ip")
    await rate_limit.check_and_record_call_start(ip_a)
    await rate_limit.check_and_record_call_start(ip_b)  # different IP, own budget
    with pytest.raises(rate_limit.RateLimitExceeded):
        await rate_limit.check_and_record_call_start(ip_a)
