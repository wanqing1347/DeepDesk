import base64
from contextlib import contextmanager
from typing import Protocol

import httpx

from ..config import Settings
from ..tracing import inject_trace_headers, trace_provider_call
from .retry import is_retryable_http_error, sleep_before_retry_sync


class ImageDescriber(Protocol):
    def describe(self, *, content: bytes, content_type: str) -> str: ...


class OpenAICompatibleImageDescriber:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        if transport is not None and client is not None:
            raise ValueError("transport and client cannot both be provided")
        self._settings = settings
        self._transport = transport
        self._client = client

    @contextmanager
    def _client_scope(self):
        if self._client is not None:
            yield self._client
            return
        with httpx.Client(
            timeout=self._settings.request_timeout_seconds,
            transport=self._transport,
        ) as client:
            yield client

    def describe(self, *, content: bytes, content_type: str) -> str:
        api_key = self._settings.vision_provider_api_key
        if not api_key:
            raise RuntimeError("VISION_API_KEY/OPENAI_API_KEY 未配置，无法进行图片识别")
        encoded = base64.b64encode(content).decode("ascii")
        payload = {
            "model": self._settings.vision_provider_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "请描述这张图片的内容，包括场景、对象、布局、颜色、文字信息，"
                                "直接输出纯文本描述，不要多余说明。"
                            ),
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{content_type};base64,{encoded}"},
                        },
                    ],
                }
            ],
            "temperature": 0.2,
        }
        url = self._settings.vision_provider_base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        with trace_provider_call("multimodal", "describe_image"):
            traced_headers = inject_trace_headers(headers)
            with self._client_scope() as client:
                for attempt in range(self._settings.provider_max_retries + 1):
                    try:
                        response = client.post(url, headers=traced_headers, json=payload)
                        response.raise_for_status()
                        data = response.json()
                        break
                    except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                        if attempt >= self._settings.provider_max_retries or not is_retryable_http_error(exc):
                            raise
                        sleep_before_retry_sync(
                            retry_number=attempt + 1,
                            base_seconds=self._settings.provider_retry_base_seconds,
                            max_seconds=self._settings.provider_retry_max_seconds,
                            provider="multimodal",
                            operation="describe_image",
                        )
                else:
                    raise RuntimeError("image describe request retry loop exited unexpectedly")
        description = str(data.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
        return description or "[无法识别图片内容]"
