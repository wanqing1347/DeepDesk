import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from app.rate_limit import LocalRateLimiter, RedisRateLimiter
from app.schemas import AgentEvent


def test_local_rate_limiter_enforces_fixed_window() -> None:
    limiter = LocalRateLimiter(requests=2, window_seconds=60)

    async def run_case():
        first = await limiter.check("client")
        second = await limiter.check("client")
        third = await limiter.check("client")
        other = await limiter.check("other")
        return first, second, third, other

    first, second, third, other = asyncio.run(run_case())
    assert first.allowed is True and first.remaining == 1
    assert second.allowed is True and second.remaining == 0
    assert third.allowed is False and third.retry_after_seconds >= 1
    assert other.allowed is True


def test_agent_rate_limit_returns_429_with_cors_headers_and_metrics() -> None:
    app = create_app(
        Settings(
            rate_limit_mode="local",
            rate_limit_requests=2,
            rate_limit_window_seconds=60,
        )
    )

    async def fake_run(_conversation_id: str, _query: str):
        yield AgentEvent(type="text", content="ok")
        yield AgentEvent.complete()

    app.state.web_search_agent.run = fake_run
    with TestClient(app) as client:
        responses = [
            client.get(
                "/agent/chat/stream",
                params={"query": "hello", "conversationId": f"rate-{index}"},
                headers={"Origin": "http://localhost:8080"},
            )
            for index in range(3)
        ]
        metrics = client.get("/metrics").text
        stop = client.get("/agent/stop", params={"conversationId": "rate-0"})

    assert [response.status_code for response in responses] == [200, 200, 429]
    assert responses[0].headers["x-ratelimit-limit"] == "2"
    assert responses[1].headers["x-ratelimit-remaining"] == "0"
    rejected = responses[2]
    assert rejected.headers["retry-after"]
    assert rejected.headers["access-control-allow-origin"] == "http://localhost:8080"
    assert rejected.json()["code"] == 429
    assert 'deepdesk_rate_limit_rejections_total{scope="agent_chat_stream"} 1' in metrics
    assert stop.status_code == 200


def test_rate_limit_is_disabled_by_default() -> None:
    app = create_app(Settings())

    async def fake_run(_conversation_id: str, _query: str):
        yield AgentEvent(type="text", content="ok")
        yield AgentEvent.complete()

    app.state.web_search_agent.run = fake_run
    with TestClient(app) as client:
        responses = [
            client.get(
                "/agent/chat/stream",
                params={"query": "hello", "conversationId": f"off-{index}"},
            )
            for index in range(3)
        ]

    assert all(response.status_code == 200 for response in responses)
    assert all("x-ratelimit-limit" not in response.headers for response in responses)


def test_redis_rate_limiter_hashes_identity_and_uses_shared_counter() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.count = 0
            self.keys: list[str] = []

        async def eval(self, _script, _num_keys, key, _window):
            self.keys.append(key)
            self.count += 1
            return [self.count, 30]

        async def ping(self):
            return True

    redis = FakeRedis()
    limiter = RedisRateLimiter(
        Settings(rate_limit_requests=1, rate_limit_window_seconds=60),
        redis_client=redis,
    )

    async def run_case():
        await limiter.start()
        first = await limiter.check("agent_chat_stream:ip:203.0.113.10")
        second = await limiter.check("agent_chat_stream:ip:203.0.113.10")
        return first, second

    first, second = asyncio.run(run_case())
    assert first.allowed is True
    assert second.allowed is False
    assert redis.keys[0].startswith("rate_limit:")
    assert "203.0.113.10" not in redis.keys[0]
    assert redis.keys[0] == redis.keys[1]


def test_rate_limit_configuration_validation() -> None:
    with pytest.raises(ValidationError):
        Settings(rate_limit_mode="invalid")
    with pytest.raises(ValidationError):
        Settings(rate_limit_requests=0)
    with pytest.raises(ValidationError):
        Settings(rate_limit_window_seconds=0)
    with pytest.raises(ValidationError):
        Settings(rate_limit_path_prefixes="agent")
    with pytest.raises(ValidationError):
        Settings(rate_limit_key_prefix="   ")
