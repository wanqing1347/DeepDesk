import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from app.config import Settings
from app.main import create_app
from app.tasks import RedisTaskManager, TaskManager, TaskManagerUnavailableError, build_task_manager


class _FakeRedisBackend:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiry: dict[str, int] = {}
        self.subscribers: dict[str, set[_FakePubSub]] = {}
        self.refreshes: list[str] = []
        self.fail_eval = False

    def client(self) -> "_FakeRedisClient":
        return _FakeRedisClient(self)


class _FakeRedisClient:
    def __init__(self, backend: _FakeRedisBackend) -> None:
        self.backend = backend

    async def ping(self) -> bool:
        return True

    async def set(self, key: str, value: str, *, nx: bool, ex: int) -> bool | None:
        if nx and key in self.backend.values:
            return None
        self.backend.values[key] = value
        self.backend.expiry[key] = ex
        return True

    async def get(self, key: str) -> str | None:
        return self.backend.values.get(key)

    async def eval(self, script: str, _num_keys: int, key: str, owner: str, *args: Any) -> int:
        if self.backend.fail_eval:
            raise RedisError("simulated redis outage")
        if self.backend.values.get(key) != owner:
            return 0
        if "redis.call('del'" in script:
            self.backend.values.pop(key, None)
            self.backend.expiry.pop(key, None)
            return 1
        if "redis.call('expire'" in script:
            ttl = int(args[0])
            self.backend.expiry[key] = ttl
            self.backend.refreshes.append(key)
            return 1
        raise AssertionError("unknown Lua script")

    def pubsub(self, *, ignore_subscribe_messages: bool) -> "_FakePubSub":
        assert ignore_subscribe_messages is True
        return _FakePubSub(self.backend)

    async def publish(self, topic: str, data: str) -> int:
        subscribers = list(self.backend.subscribers.get(topic, set()))
        for subscriber in subscribers:
            await subscriber.queue.put({"type": "message", "data": data})
        return len(subscribers)


class _FakePubSub:
    def __init__(self, backend: _FakeRedisBackend) -> None:
        self.backend = backend
        self.queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        self.topics: set[str] = set()
        self.closed = False

    async def subscribe(self, topic: str) -> None:
        self.topics.add(topic)
        self.backend.subscribers.setdefault(topic, set()).add(self)

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        while not self.closed:
            message = await self.queue.get()
            if message is None:
                return
            yield message

    async def get_message(self, *, timeout: float) -> dict[str, Any] | None:
        try:
            message = await asyncio.wait_for(self.queue.get(), timeout=timeout)
        except TimeoutError:
            return None
        return message

    async def aclose(self) -> None:
        if self.closed:
            return
        self.closed = True
        for topic in self.topics:
            subscribers = self.backend.subscribers.get(topic)
            if subscribers is not None:
                subscribers.discard(self)
        await self.queue.put(None)


async def _hold_task(manager: TaskManager, conversation_id: str, ready: asyncio.Event) -> None:
    acquired = await manager.register_current(conversation_id)
    if not acquired:
        raise AssertionError("holder failed to acquire task lease")
    ready.set()
    try:
        await asyncio.Future()
    finally:
        await manager.remove(conversation_id)


def _redis_settings() -> Settings:
    return Settings(
        task_manager_mode="redis",
        task_ttl_seconds=1800,
        task_ttl_refresh_seconds=300,
    )


def test_build_task_manager_defaults_to_local_and_supports_redis() -> None:
    assert isinstance(build_task_manager(Settings()), TaskManager)
    assert not isinstance(build_task_manager(Settings()), RedisTaskManager)
    assert isinstance(build_task_manager(_redis_settings()), RedisTaskManager)


def test_redis_refresh_interval_must_be_shorter_than_lease_ttl() -> None:
    with pytest.raises(ValueError, match="TASK_TTL_REFRESH_SECONDS"):
        Settings(
            task_manager_mode="redis",
            task_ttl_seconds=30,
            task_ttl_refresh_seconds=30,
        )


def test_redis_task_manager_rejects_same_conversation_on_second_instance() -> None:
    asyncio.run(_rejects_same_conversation_on_second_instance())


async def _rejects_same_conversation_on_second_instance() -> None:
    backend = _FakeRedisBackend()
    first = RedisTaskManager(_redis_settings(), redis_client=backend.client(), instance_id="first")
    second = RedisTaskManager(_redis_settings(), redis_client=backend.client(), instance_id="second")
    ready = asyncio.Event()
    holder = asyncio.create_task(_hold_task(first, "conv-lock", ready))
    await ready.wait()
    try:
        assert await second.register_current("conv-lock") is False
        assert backend.values["agent:task:conv-lock"] == "first"
    finally:
        holder.cancel()
        await asyncio.gather(holder, return_exceptions=True)


def test_remote_stop_broadcast_cancels_holder_and_releases_redis_key() -> None:
    asyncio.run(_remote_stop_broadcast_cancels_holder_and_releases_redis_key())


async def _remote_stop_broadcast_cancels_holder_and_releases_redis_key() -> None:
    backend = _FakeRedisBackend()
    first = RedisTaskManager(_redis_settings(), redis_client=backend.client(), instance_id="first")
    second = RedisTaskManager(_redis_settings(), redis_client=backend.client(), instance_id="second")
    await first.start()
    await second.start()
    await asyncio.sleep(0)

    ready = asyncio.Event()
    holder = asyncio.create_task(_hold_task(first, "conv-stop", ready))
    await ready.wait()
    try:
        assert await second.stop("conv-stop") is True
        with pytest.raises(asyncio.CancelledError):
            await holder
        for _ in range(10):
            if "agent:task:conv-stop" not in backend.values:
                break
            await asyncio.sleep(0)
        assert "agent:task:conv-stop" not in backend.values
    finally:
        await first.close()
        await second.close()


def test_remove_never_deletes_a_lock_now_owned_by_another_instance() -> None:
    asyncio.run(_remove_never_deletes_a_lock_now_owned_by_another_instance())


async def _remove_never_deletes_a_lock_now_owned_by_another_instance() -> None:
    backend = _FakeRedisBackend()
    manager = RedisTaskManager(_redis_settings(), redis_client=backend.client(), instance_id="first")
    ready = asyncio.Event()
    holder = asyncio.create_task(_hold_task(manager, "conv-owner", ready))
    await ready.wait()
    backend.values["agent:task:conv-owner"] = "other"

    await manager.remove("conv-owner")

    assert backend.values["agent:task:conv-owner"] == "other"
    holder.cancel()
    await asyncio.gather(holder, return_exceptions=True)


def test_refresh_extends_owned_lease() -> None:
    asyncio.run(_refresh_extends_owned_lease())


async def _refresh_extends_owned_lease() -> None:
    backend = _FakeRedisBackend()
    settings = _redis_settings()
    manager = RedisTaskManager(settings, redis_client=backend.client(), instance_id="first")
    ready = asyncio.Event()
    holder = asyncio.create_task(_hold_task(manager, "conv-refresh", ready))
    await ready.wait()
    try:
        backend.expiry["agent:task:conv-refresh"] = 1
        await manager._refresh_once()
        assert backend.expiry["agent:task:conv-refresh"] == settings.task_ttl_seconds
        assert backend.refreshes == ["agent:task:conv-refresh"]
    finally:
        holder.cancel()
        await asyncio.gather(holder, return_exceptions=True)


def test_refresh_cancels_local_task_when_lease_ownership_is_lost() -> None:
    asyncio.run(_refresh_cancels_local_task_when_lease_ownership_is_lost())


async def _refresh_cancels_local_task_when_lease_ownership_is_lost() -> None:
    backend = _FakeRedisBackend()
    manager = RedisTaskManager(_redis_settings(), redis_client=backend.client(), instance_id="first")
    ready = asyncio.Event()
    holder = asyncio.create_task(_hold_task(manager, "conv-lost", ready))
    await ready.wait()
    backend.values["agent:task:conv-lost"] = "second"

    await manager._refresh_once()

    with pytest.raises(asyncio.CancelledError):
        await holder
    assert backend.values["agent:task:conv-lost"] == "second"
    assert await manager.has_running("conv-lost") is True


def test_close_cancels_local_tasks_and_releases_owned_leases() -> None:
    asyncio.run(_close_cancels_local_tasks_and_releases_owned_leases())


async def _close_cancels_local_tasks_and_releases_owned_leases() -> None:
    backend = _FakeRedisBackend()
    manager = RedisTaskManager(_redis_settings(), redis_client=backend.client(), instance_id="first")
    ready = asyncio.Event()
    holder = asyncio.create_task(_hold_task(manager, "conv-close", ready))
    await ready.wait()

    await manager.close()

    assert holder.cancelled()
    assert "agent:task:conv-close" not in backend.values


def test_transient_redis_refresh_failure_keeps_owned_task_running() -> None:
    asyncio.run(_transient_redis_refresh_failure_keeps_owned_task_running())


async def _transient_redis_refresh_failure_keeps_owned_task_running() -> None:
    backend = _FakeRedisBackend()
    manager = RedisTaskManager(_redis_settings(), redis_client=backend.client(), instance_id="first")
    ready = asyncio.Event()
    holder = asyncio.create_task(_hold_task(manager, "conv-outage", ready))
    await ready.wait()
    backend.fail_eval = True
    try:
        await manager._refresh_once()
        assert not holder.done()
        assert backend.values["agent:task:conv-outage"] == "first"
    finally:
        backend.fail_eval = False
        holder.cancel()
        await asyncio.gather(holder, return_exceptions=True)


def test_main_stream_reports_task_manager_unavailable() -> None:
    app = create_app(Settings())

    async def fail_registration(_conversation_id: str) -> bool:
        raise TaskManagerUnavailableError("redis unavailable")

    app.state.tasks.register_current = fail_registration
    with TestClient(app) as client:
        response = client.get(
            "/agent/chat/stream",
            params={"query": "hello", "conversationId": "task-backend-down"},
        )
        payloads = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]

    assert response.status_code == 200
    assert payloads[0]["type"] == "error"
    assert payloads[0]["code"] == "TASK_MANAGER_UNAVAILABLE"
    assert payloads[-1] == {"type": "complete"}


def test_stop_returns_503_when_distributed_task_backend_is_unavailable() -> None:
    app = create_app(Settings())

    async def fail_stop(_conversation_id: str) -> bool:
        raise TaskManagerUnavailableError("redis unavailable")

    app.state.tasks.stop = fail_stop
    with TestClient(app) as client:
        response = client.get("/agent/stop", params={"conversationId": "task-backend-down"})

    assert response.status_code == 503
    assert response.json()["detail"] == "任务协调服务不可用，请稍后重试"
