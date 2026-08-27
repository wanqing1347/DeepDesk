import json
from contextlib import asynccontextmanager
from typing import Any, ClassVar

import httpx

from ..config import Settings
from ..providers.retry import is_retryable_http_error, sleep_before_retry
from ..tracing import inject_trace_headers, trace_provider_call


class WebSearchTool:
    name = "web_search"

    definition: ClassVar[dict[str, Any]] = {
        "type": "function",
        "function": {
            "name": name,
            "description": "Search the web for current information. Use concise queries.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
                },
                "required": ["query"],
            },
        },
    }

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if transport is not None and client is not None:
            raise ValueError("transport and client cannot both be provided")
        self._settings = settings
        self._transport = transport
        self._client = client

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

    async def call(self, arguments: str) -> dict[str, Any]:
        args = json.loads(arguments or "{}")
        query = str(args.get("query", "")).strip()
        max_results = max(1, min(int(args.get("max_results", 3)), 5))
        if not query:
            return {"error": "query 不能为空"}

        if self._settings.search_mode.lower() == "demo":
            return {
                "results": [
                    {
                        "title": "Demo search result",
                        "url": "https://example.com/demo-search",
                        "content": f"这是本地 demo 搜索结果，查询词为：{query}",
                    }
                ][:max_results],
                "source": "demo",
            }

        if not self._settings.tavily_api_key:
            return {"error": "TAVILY_API_KEY 未配置，无法进行真实联网搜索"}

        payload = {
            "api_key": self._settings.tavily_api_key,
            "query": query,
            "max_results": max_results,
            "include_answer": False,
        }
        with trace_provider_call("tavily", "search"):
            async with self._client_scope() as client:
                for attempt in range(self._settings.provider_max_retries + 1):
                    try:
                        response = await client.post(
                            self._settings.tavily_endpoint,
                            headers=inject_trace_headers(),
                            json=payload,
                        )
                        response.raise_for_status()
                        data = response.json()
                        return {"results": data.get("results", []), "source": "tavily"}
                    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                        if attempt >= self._settings.provider_max_retries or not is_retryable_http_error(exc):
                            raise
                        await sleep_before_retry(
                            retry_number=attempt + 1,
                            base_seconds=self._settings.provider_retry_base_seconds,
                            max_seconds=self._settings.provider_retry_max_seconds,
                            provider="tavily",
                            operation="search",
                        )
        raise RuntimeError("Tavily request retry loop exited unexpectedly")

