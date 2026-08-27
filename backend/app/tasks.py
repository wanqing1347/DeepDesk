import asyncio
import logging
import uuid
from contextlib import suppress
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError

from .config import Settings

logger = logging.getLogger(__name__)


class TaskManagerUnavailableError(RuntimeError):
    pass


_RELEASE_IF_OWNER = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""

_REFRESH_IF_OWNER = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""


class TaskManager:
    """Single-process task manager used by default for development and tests."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[object]] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        return None

    async def register_current(self, conversation_id: str) -> bool:
        async with self._lock:
            task = asyncio.current_task()
            if task is None or conversation_id in self._tasks:
                return False
            self._tasks[conversation_id] = task
            return True

    async def remove(self, conversation_id: str) -> None:
        async with self._lock:
            self._tasks.pop(conversation_id, None)

    async def stop(self, conversation_id: str) -> bool:
        async with self._lock:
            task = self._tasks.get(conversation_id)
            if task is None or task.done():
                self._tasks.pop(conversation_id, None)
                return False
            self._tasks.pop(conversation_id, None)
        task.cancel()
        return True

    async def has_running(self, conversation_id: str) -> bool:
        async with self._lock:
            task = self._tasks.get(conversation_id)
            return bool(task is not None and not task.done())

    async def check_ready(self) -> None:
        return None

    async def close(self) -> None:
        async with self._lock:
            tasks = list(self._tasks.values())
            self._tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


class RedisTaskManager(TaskManager):
    """Redis-backed distributed task lease + cross-instance stop propagation."""

    def __init__(
        self,
        settings: Settings,
        *,
        redis_client: Any | None = None,
        instance_id: str | None = None,
    ) -> None:
        super().__init__()
        self._settings = settings
        self.instance_id = instance_id or uuid.uuid4().hex[:8]
        self._redis: Any = redis_client or Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=settings.redis_socket_connect_timeout_seconds,
            socket_timeout=settings.redis_socket_timeout_seconds,
        )
        self._owns_redis = redis_client is None
        self._listener_task: asyncio.Task[object] | None = None
        self._refresh_task: asyncio.Task[object] | None = None
        self._pubsub: Any | None = None
        self._subscriber_ready = asyncio.Event()
        self._closing = False

    async def start(self) -> None:
        if self._listener_task is not None:
            return
        try:
            await self._redis.ping()
        except RedisError as exc:
            raise TaskManagerUnavailableError(f"Redis task backend unavailable: {exc}") from exc
        self._closing = False
        self._listener_task = asyncio.create_task(
            self._subscriber_loop(),
            name=f"agent-stop-listener-{self.instance_id}",
        )
        self._refresh_task = asyncio.create_task(
            self._ttl_refresh_loop(),
            name=f"agent-ttl-refresh-{self.instance_id}",
        )
        try:
            await asyncio.wait_for(
                self._subscriber_ready.wait(),
                timeout=self._settings.redis_socket_connect_timeout_seconds,
            )
        except TimeoutError as exc:
            await self.close()
            raise TaskManagerUnavailableError("Redis stop subscriber did not become ready") from exc

    async def register_current(self, conversation_id: str) -> bool:
        task = asyncio.current_task()
        if task is None:
            return False
        key = self._task_key(conversation_id)
        async with self._lock:
            existing = self._tasks.get(conversation_id)
            if existing is not None and not existing.done():
                return False
            try:
                acquired = await self._redis.set(
                    key,
                    self.instance_id,
                    nx=True,
                    ex=self._settings.task_ttl_seconds,
                )
            except RedisError as exc:
                raise TaskManagerUnavailableError(f"Redis task registration failed: {exc}") from exc
            if not acquired:
                return False
            self._tasks[conversation_id] = task
        return True

    async def remove(self, conversation_id: str) -> None:
        async with self._lock:
            self._tasks.pop(conversation_id, None)
        try:
            await self._release_if_owner(conversation_id)
        except RedisError as exc:
            logger.warning("Redis task lease cleanup failed conversation_id=%s: %s", conversation_id, exc)

    async def stop(self, conversation_id: str) -> bool:
        task: asyncio.Task[object] | None
        async with self._lock:
            task = self._tasks.pop(conversation_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await self._release_if_owner(conversation_id)
            except RedisError as exc:
                logger.warning(
                    "Redis task lease cleanup after stop failed conversation_id=%s: %s",
                    conversation_id,
                    exc,
                )
            return True

        try:
            holder = self._decode(await self._redis.get(self._task_key(conversation_id)))
        except RedisError as exc:
            raise TaskManagerUnavailableError(f"Redis task lookup failed: {exc}") from exc
        if not holder:
            return False
        if holder == self.instance_id:
            # Redis still points to us but no active local task exists. Match the
            # Fast path: do not broadcast a stop to every instance.
            return False
        try:
            await self._redis.publish(self._settings.task_stop_topic, conversation_id)
        except RedisError as exc:
            raise TaskManagerUnavailableError(f"Redis stop broadcast failed: {exc}") from exc
        return True

    async def has_running(self, conversation_id: str) -> bool:
        if await super().has_running(conversation_id):
            return True
        try:
            holder = self._decode(await self._redis.get(self._task_key(conversation_id)))
        except RedisError as exc:
            raise TaskManagerUnavailableError(f"Redis task lookup failed: {exc}") from exc
        return bool(holder)

    async def check_ready(self) -> None:
        try:
            await self._redis.ping()
        except RedisError as exc:
            raise TaskManagerUnavailableError(f"Redis task backend unavailable: {exc}") from exc
        if self._listener_task is None or self._listener_task.done() or not self._subscriber_ready.is_set():
            raise TaskManagerUnavailableError("Redis stop subscriber is not ready")

    async def _handle_remote_stop(self, conversation_id: str) -> None:
        async with self._lock:
            task = self._tasks.pop(conversation_id, None)
        if task is None or task.done():
            return
        task.cancel()
        await self._release_if_owner(conversation_id)

    async def _refresh_once(self) -> None:
        async with self._lock:
            snapshot = list(self._tasks.items())
        for conversation_id, task in snapshot:
            if task.done():
                async with self._lock:
                    self._tasks.pop(conversation_id, None)
                await self._release_if_owner(conversation_id)
                continue
            try:
                refreshed = await self._redis.eval(
                    _REFRESH_IF_OWNER,
                    1,
                    self._task_key(conversation_id),
                    self.instance_id,
                    self._settings.task_ttl_seconds,
                )
            except RedisError as exc:
                logger.warning("Redis task TTL refresh failed conversation_id=%s: %s", conversation_id, exc)
                continue
            if int(refreshed or 0) == 1:
                continue

            # Removing only the local entry can leave an
            # old request running after lock ownership changes. Cancel it instead
            # so a lost lease cannot produce split-brain execution.
            async with self._lock:
                current = self._tasks.get(conversation_id)
                if current is task:
                    self._tasks.pop(conversation_id, None)
            if not task.done():
                task.cancel()
            logger.warning(
                "Redis task lease ownership lost; cancelled local task conversation_id=%s instance_id=%s",
                conversation_id,
                self.instance_id,
            )

    async def _release_if_owner(self, conversation_id: str) -> bool:
        released = await self._redis.eval(
            _RELEASE_IF_OWNER,
            1,
            self._task_key(conversation_id),
            self.instance_id,
        )
        return bool(int(released or 0))

    async def _subscriber_loop(self) -> None:
        while not self._closing:
            pubsub: Any | None = None
            self._subscriber_ready.clear()
            try:
                pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
                self._pubsub = pubsub
                await pubsub.subscribe(self._settings.task_stop_topic)
                self._subscriber_ready.set()
                while not self._closing:
                    message = await pubsub.get_message(timeout=1.0)
                    if message is None:
                        continue
                    if not isinstance(message, dict) or message.get("type") != "message":
                        continue
                    conversation_id = self._decode(message.get("data"))
                    if conversation_id:
                        await self._handle_remote_stop(conversation_id)
            except asyncio.CancelledError:
                raise
            except RedisError as exc:
                if not self._closing:
                    logger.warning("Redis stop subscriber interrupted: %s", exc)
                    await asyncio.sleep(1)
            finally:
                self._subscriber_ready.clear()
                if self._pubsub is pubsub:
                    self._pubsub = None
                if pubsub is not None:
                    with suppress(Exception):
                        await pubsub.aclose()

    async def _ttl_refresh_loop(self) -> None:
        try:
            while not self._closing:
                await asyncio.sleep(self._settings.task_ttl_refresh_seconds)
                if not self._closing:
                    await self._refresh_once()
        except asyncio.CancelledError:
            raise

    async def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        background = [task for task in (self._listener_task, self._refresh_task) if task is not None]
        for task in background:
            task.cancel()
        if background:
            await asyncio.gather(*background, return_exceptions=True)
        self._listener_task = None
        self._refresh_task = None
        self._subscriber_ready.clear()

        async with self._lock:
            local_tasks = list(self._tasks.items())
            self._tasks.clear()
        for _, task in local_tasks:
            if not task.done():
                task.cancel()
        if local_tasks:
            await asyncio.gather(*(task for _, task in local_tasks), return_exceptions=True)
        for conversation_id, _ in local_tasks:
            with suppress(RedisError):
                await self._release_if_owner(conversation_id)

        if self._pubsub is not None:
            with suppress(Exception):
                await self._pubsub.aclose()
            self._pubsub = None
        if self._owns_redis:
            with suppress(Exception):
                await self._redis.aclose()

    def _task_key(self, conversation_id: str) -> str:
        return f"{self._settings.task_key_prefix}{conversation_id}"

    @staticmethod
    def _decode(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)


def build_task_manager(settings: Settings) -> TaskManager:
    if settings.task_manager_mode == "redis":
        return RedisTaskManager(settings)
    return TaskManager()
