import asyncio
import time

import httpx

from ..metrics import record_provider_retry
from ..tracing import record_trace_event

RETRYABLE_HTTP_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


def _record_retry(provider: str | None, operation: str | None, retry_number: int) -> None:
    if not provider or not operation:
        return
    record_provider_retry(provider, operation)
    record_trace_event(
        "provider.retry",
        {
            "deepdesk.provider.name": provider,
            "deepdesk.provider.operation": operation,
            "deepdesk.retry.number": retry_number,
        },
    )


def is_retryable_http_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.RequestError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_HTTP_STATUS_CODES
    return False


def retry_delay_seconds(*, retry_number: int, base_seconds: float, max_seconds: float) -> float:
    if retry_number < 1:
        raise ValueError("retry_number must be >= 1")
    if base_seconds <= 0 or max_seconds <= 0:
        return 0.0
    return min(max_seconds, base_seconds * (2 ** (retry_number - 1)))


async def sleep_before_retry(
    *,
    retry_number: int,
    base_seconds: float,
    max_seconds: float,
    provider: str | None = None,
    operation: str | None = None,
) -> None:
    _record_retry(provider, operation, retry_number)
    delay = retry_delay_seconds(
        retry_number=retry_number,
        base_seconds=base_seconds,
        max_seconds=max_seconds,
    )
    if delay > 0:
        await asyncio.sleep(delay)


def sleep_before_retry_sync(
    *,
    retry_number: int,
    base_seconds: float,
    max_seconds: float,
    provider: str | None = None,
    operation: str | None = None,
) -> None:
    _record_retry(provider, operation, retry_number)
    delay = retry_delay_seconds(
        retry_number=retry_number,
        base_seconds=base_seconds,
        max_seconds=max_seconds,
    )
    if delay > 0:
        time.sleep(delay)
