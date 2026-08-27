import asyncio
import os
import uuid

import pytest
from redis.asyncio import Redis

from app.config import Settings
from app.tasks import RedisTaskManager

pytestmark = pytest.mark.integration


def test_real_redis_two_instance_lock_stop_and_ttl() -> None:
    if os.getenv("RUN_REDIS_INTEGRATION", "").strip().lower() not in {"1", "true", "yes"}:
        pytest.skip("set RUN_REDIS_INTEGRATION=1 to run the real Redis task-manager round-trip")
    asyncio.run(_real_redis_two_instance_lock_stop_and_ttl())


async def _real_redis_two_instance_lock_stop_and_ttl() -> None:
    redis_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6380/15")
    settings = Settings(
        task_manager_mode="redis",
        redis_url=redis_url,
        task_ttl_seconds=30,
        task_ttl_refresh_seconds=5,
        redis_socket_connect_timeout_seconds=3,
        redis_socket_timeout_seconds=3,
    )
    first = RedisTaskManager(settings, instance_id="real-one")
    second = RedisTaskManager(settings, instance_id="real-two")
    raw = Redis.from_url(redis_url, decode_responses=True)
    conversation_id = f"redis-integration-{uuid.uuid4().hex}"
    key = f"{settings.task_key_prefix}{conversation_id}"
    ready = asyncio.Event()

    async def holder() -> None:
        assert await first.register_current(conversation_id) is True
        ready.set()
        try:
            await asyncio.Future()
        finally:
            await first.remove(conversation_id)

    task: asyncio.Task[None] | None = None
    try:
        await first.start()
        await second.start()
        task = asyncio.create_task(holder())
        await ready.wait()

        assert await raw.get(key) == first.instance_id
        assert await second.register_current(conversation_id) is False
        ttl_before = await raw.ttl(key)
        assert 0 < ttl_before <= settings.task_ttl_seconds

        await first._refresh_once()
        ttl_after = await raw.ttl(key)
        assert 0 < ttl_after <= settings.task_ttl_seconds

        assert await second.stop(conversation_id) is True
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=3)
        assert await raw.get(key) is None
    finally:
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await first.close()
        await second.close()
        await raw.delete(key)
        await raw.aclose()
