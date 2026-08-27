import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from ..config import Settings
from ..tracing import inject_trace_headers, trace_provider_call
from .retry import is_retryable_http_error, sleep_before_retry


class OpenAICompatibleClient:
    """Small provider-neutral client for OpenAI-compatible chat APIs."""

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
    ) -> None:
        if transport is not None and client is not None:
            raise ValueError("transport and client cannot both be provided")
        self._settings = settings
        self._transport = transport
        self._client = client
        self._api_key = settings.openai_api_key if api_key is None else api_key
        self._base_url = settings.openai_base_url if base_url is None else base_url
        self._model = settings.openai_model if model is None else model
        self._temperature = settings.openai_temperature if temperature is None else temperature

    @asynccontextmanager
    async def _client_scope(self):
        if self._client is not None:
            yield self._client
            return
        async with httpx.AsyncClient(
            timeout=self._settings.request_timeout_seconds,
            transport=self._transport,
        ) as client:
            yield client

    def _url(self) -> str:
        return self._base_url.rstrip("/") + "/chat/completions"

    def _headers(self) -> dict[str, str]:
        return inject_trace_headers(
            {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            }
        )

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        enable_thinking: bool | None = None,
    ) -> dict[str, Any]:
        if not self._api_key:
            raise RuntimeError("模型 API Key 未配置，无法调用模型")
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
        }
        if enable_thinking is not None:
            payload["enable_thinking"] = enable_thinking
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        with trace_provider_call("llm", "complete"):
            async with self._client_scope() as client:
                for attempt in range(self._settings.provider_max_retries + 1):
                    try:
                        response = await client.post(self._url(), headers=self._headers(), json=payload)
                        response.raise_for_status()
                        return response.json()
                    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                        if attempt >= self._settings.provider_max_retries or not is_retryable_http_error(exc):
                            raise
                        await sleep_before_retry(
                            retry_number=attempt + 1,
                            base_seconds=self._settings.provider_retry_base_seconds,
                            max_seconds=self._settings.provider_retry_max_seconds,
                            provider="llm",
                            operation="complete",
                        )
        raise RuntimeError("LLM request retry loop exited unexpectedly")

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        enable_thinking: bool | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield OpenAI-compatible assistant deltas, including tool-call deltas."""
        if not self._api_key:
            raise RuntimeError("模型 API Key 未配置，无法调用模型")

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "stream": True,
        }
        if enable_thinking is not None:
            payload["enable_thinking"] = enable_thinking
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        with trace_provider_call("llm", "stream_chat"):
            async with self._client_scope() as client:
                for attempt in range(self._settings.provider_max_retries + 1):
                    yielded_delta = False
                    try:
                        async with client.stream(
                            "POST",
                            self._url(),
                            headers=self._headers(),
                            json=payload,
                        ) as response:
                            response.raise_for_status()
                            async for line in response.aiter_lines():
                                if not line.startswith("data:"):
                                    continue
                                data = line[5:].strip()
                                if not data or data == "[DONE]":
                                    if data == "[DONE]":
                                        return
                                    continue
                                chunk = json.loads(data)
                                choices = chunk.get("choices") or []
                                if not choices:
                                    continue
                                delta = choices[0].get("delta") or {}
                                if delta:
                                    yielded_delta = True
                                    yield delta
                        return
                    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                        if (
                            yielded_delta
                            or attempt >= self._settings.provider_max_retries
                            or not is_retryable_http_error(exc)
                        ):
                            raise
                        await sleep_before_retry(
                            retry_number=attempt + 1,
                            base_seconds=self._settings.provider_retry_base_seconds,
                            max_seconds=self._settings.provider_retry_max_seconds,
                            provider="llm",
                            operation="stream_chat",
                        )

    async def stream_text(self, messages: list[dict[str, Any]]) -> AsyncIterator[str]:
        async for delta in self.stream_chat(messages, []):
            content = delta.get("content")
            if content:
                yield str(content)
