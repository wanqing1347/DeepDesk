import asyncio
import hashlib
import math
import time
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings
from .metrics import current_metrics_context
from .tracing import record_trace_event


class RateLimiterUnavailableError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int


class RateLimiter:
    enabled = False

    async def start(self) -> None:
        return None

    async def check(self, key: str) -> RateLimitDecision:
        return RateLimitDecision(allowed=True, remaining=0, retry_after_seconds=0)

    async def check_ready(self) -> None:
        return None

    async def close(self) -> None:
        return None


class LocalRateLimiter(RateLimiter):
    enabled = True

    def __init__(self, *, requests: int, window_seconds: int) -> None:
        self._requests = requests
        self._window_seconds = window_seconds
        self._entries: dict[str, tuple[int, float]] = {}
        self._lock = asyncio.Lock()

    async def check(self, key: str) -> RateLimitDecision:
        now = time.monotonic()
        async with self._lock:
            count, expires_at = self._entries.get(key, (0, now + self._window_seconds))
            if now >= expires_at:
                count = 0
                expires_at = now + self._window_seconds
            count += 1
            self._entries[key] = (count, expires_at)
            if len(self._entries) > 10_000:
                self._entries = {
                    entry_key: entry
                    for entry_key, entry in self._entries.items()
                    if entry[1] > now
                }
        retry_after = max(1, math.ceil(expires_at - now))
        return RateLimitDecision(
            allowed=count <= self._requests,
            remaining=max(0, self._requests - count),
            retry_after_seconds=retry_after,
        )


_REDIS_RATE_LIMIT_SCRIPT = """
local count = redis.call('incr', KEYS[1])
if count == 1 then
  redis.call('expire', KEYS[1], ARGV[1])
end
local ttl = redis.call('ttl', KEYS[1])
return {count, ttl}
"""


class RedisRateLimiter(RateLimiter):
    enabled = True

    def __init__(self, settings: Settings, *, redis_client: Any | None = None) -> None:
        self._requests = settings.rate_limit_requests
        self._window_seconds = settings.rate_limit_window_seconds
        self._key_prefix = settings.rate_limit_key_prefix
        self._redis: Any = redis_client or Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=settings.redis_socket_connect_timeout_seconds,
            socket_timeout=settings.redis_socket_timeout_seconds,
        )
        self._owns_redis = redis_client is None

    async def start(self) -> None:
        await self.check_ready()

    async def check(self, key: str) -> RateLimitDecision:
        redis_key = f"{self._key_prefix}{_hash_key(key)}"
        try:
            result = await self._redis.eval(
                _REDIS_RATE_LIMIT_SCRIPT,
                1,
                redis_key,
                self._window_seconds,
            )
        except RedisError as exc:
            raise RateLimiterUnavailableError(f"Redis rate limit backend unavailable: {exc}") from exc
        count = int(result[0])
        ttl = max(1, int(result[1]))
        return RateLimitDecision(
            allowed=count <= self._requests,
            remaining=max(0, self._requests - count),
            retry_after_seconds=ttl,
        )

    async def check_ready(self) -> None:
        try:
            await self._redis.ping()
        except RedisError as exc:
            raise RateLimiterUnavailableError(f"Redis rate limit backend unavailable: {exc}") from exc

    async def close(self) -> None:
        if self._owns_redis:
            await self._redis.aclose()


class RateLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        limiter: RateLimiter,
        path_prefixes: tuple[str, ...],
        limit: int,
    ) -> None:
        self.app = app
        self._limiter = limiter
        self._path_prefixes = path_prefixes
        self._limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._limiter.enabled:
            await self.app(scope, receive, send)
            return
        path = str(scope.get("path") or "")
        matched_prefix = next((prefix for prefix in self._path_prefixes if path.startswith(prefix)), None)
        if matched_prefix is None:
            await self.app(scope, receive, send)
            return

        rate_scope = matched_prefix.strip("/").replace("/", "_") or "root"
        identity = _request_identity(scope)
        try:
            decision = await self._limiter.check(f"{rate_scope}:{identity}")
        except RateLimiterUnavailableError:
            response = JSONResponse(
                status_code=503,
                content={
                    "code": 503,
                    "message": "请求限流服务不可用，请稍后重试",
                    "data": None,
                },
            )
            await response(scope, receive, send)
            return

        if not decision.allowed:
            _record_rejection(rate_scope)
            record_trace_event("rate_limit.rejected", {"deepdesk.rate_limit.scope": rate_scope})
            response = JSONResponse(
                status_code=429,
                content={
                    "code": 429,
                    "message": "请求过于频繁，请稍后重试",
                    "data": None,
                },
                headers={
                    "Retry-After": str(decision.retry_after_seconds),
                    "X-RateLimit-Limit": str(self._limit),
                    "X-RateLimit-Remaining": "0",
                },
            )
            await response(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(
                    [
                        (b"x-ratelimit-limit", str(self._limit).encode("ascii")),
                        (b"x-ratelimit-remaining", str(decision.remaining).encode("ascii")),
                    ]
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


def build_rate_limiter(settings: Settings) -> RateLimiter:
    if settings.rate_limit_mode == "local":
        return LocalRateLimiter(
            requests=settings.rate_limit_requests,
            window_seconds=settings.rate_limit_window_seconds,
        )
    if settings.rate_limit_mode == "redis":
        return RedisRateLimiter(settings)
    return RateLimiter()


def _request_identity(scope: Scope) -> str:
    state = scope.get("state")
    if isinstance(state, dict):
        principal = str(state.get("auth_principal") or "").strip()
        if principal:
            return f"principal:{principal}"
    client = scope.get("client")
    if isinstance(client, tuple) and client:
        return f"ip:{client[0]}"
    return "ip:unknown"


def _hash_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _record_rejection(rate_scope: str) -> None:
    context = current_metrics_context()
    if context is None:
        return
    context.registry.increment(
        "deepdesk_rate_limit_rejections_total",
        labels={"scope": rate_scope},
    )
