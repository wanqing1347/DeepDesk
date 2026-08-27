import asyncio
import json
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.config import Settings
from app.files.rag import DashScopeEmbeddingClient, OpenAIQueryRewriter
from app.ppt.providers import QwenPptImageGenerator, materialize_ppt_images
from app.providers.llm import OpenAICompatibleClient
from app.providers.multimodal import OpenAICompatibleImageDescriber
from app.providers.retry import is_retryable_http_error, retry_delay_seconds
from app.tools.web_search import WebSearchTool


def retry_settings(**overrides) -> Settings:
    defaults = {
        "openai_api_key": "test-key",
        "search_mode": "tavily",
        "tavily_api_key": "tavily-key",
        "provider_max_retries": 2,
        "provider_retry_base_seconds": 0,
        "provider_retry_max_seconds": 0,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_retry_delay_is_exponential_and_capped() -> None:
    assert retry_delay_seconds(retry_number=1, base_seconds=0.5, max_seconds=3) == 0.5
    assert retry_delay_seconds(retry_number=2, base_seconds=0.5, max_seconds=3) == 1.0
    assert retry_delay_seconds(retry_number=4, base_seconds=0.5, max_seconds=3) == 3


def test_retry_policy_distinguishes_transient_and_permanent_http_errors() -> None:
    request = httpx.Request("POST", "https://example.test")
    transient_response = httpx.Response(503, request=request)
    permanent_response = httpx.Response(400, request=request)

    with pytest.raises(httpx.HTTPStatusError) as transient_info:
        transient_response.raise_for_status()
    with pytest.raises(httpx.HTTPStatusError) as permanent_info:
        permanent_response.raise_for_status()

    assert is_retryable_http_error(transient_info.value) is True
    assert is_retryable_http_error(permanent_info.value) is False
    assert is_retryable_http_error(httpx.ConnectError("offline", request=request)) is True


def test_provider_retry_configuration_rejects_invalid_values() -> None:
    with pytest.raises(ValidationError):
        Settings(provider_max_retries=-1)
    with pytest.raises(ValidationError):
        Settings(provider_retry_base_seconds=2, provider_retry_max_seconds=1)
    with pytest.raises(ValidationError):
        Settings(request_timeout_seconds=0)


def test_llm_complete_retries_transient_status_then_succeeds() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    client = OpenAICompatibleClient(retry_settings(), transport=httpx.MockTransport(handler))
    result = asyncio.run(client.complete([{"role": "user", "content": "hello"}], []))

    assert attempts == 2
    assert result["choices"][0]["message"]["content"] == "ok"


def test_llm_complete_can_disable_provider_thinking() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    client = OpenAICompatibleClient(retry_settings(), transport=httpx.MockTransport(handler))
    result = asyncio.run(
        client.complete(
            [{"role": "user", "content": "hello"}],
            [],
            enable_thinking=False,
        )
    )

    assert result["choices"][0]["message"]["content"] == "ok"
    assert captured["enable_thinking"] is False


def test_llm_can_use_provider_overrides_independent_from_main_chat() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization", "")
        captured["model"] = str(json.loads(request.content)["model"])
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": "rewritten"}}]},
        )

    client = OpenAICompatibleClient(
        retry_settings(
            openai_api_key="main-key",
            openai_base_url="https://main.example.test/v1",
            openai_model="main-model",
        ),
        transport=httpx.MockTransport(handler),
        api_key="rewrite-key",
        base_url="https://rewrite.example.test/v1",
        model="rewrite-model",
    )
    result = asyncio.run(client.complete([{"role": "user", "content": "hello"}], []))

    assert result["choices"][0]["message"]["content"] == "rewritten"
    assert captured == {
        "url": "https://rewrite.example.test/v1/chat/completions",
        "authorization": "Bearer rewrite-key",
        "model": "rewrite-model",
    }


def test_query_rewriter_uses_dedicated_provider_settings_with_fallbacks() -> None:
    dedicated = retry_settings(
        query_rewrite_api_key="rewrite-key",
        query_rewrite_base_url="https://rewrite.example.test/v1",
        query_rewrite_model="rewrite-model",
    )
    rewriter = OpenAIQueryRewriter(dedicated)

    assert rewriter._llm._api_key == "rewrite-key"
    assert rewriter._llm._base_url == "https://rewrite.example.test/v1"
    assert rewriter._llm._model == "rewrite-model"

    fallback = retry_settings(
        openai_api_key="main-key",
        openai_model="main-model",
        query_rewrite_api_key="",
        query_rewrite_base_url="",
        query_rewrite_model="",
    )
    fallback_rewriter = OpenAIQueryRewriter(fallback)
    assert fallback_rewriter._llm._api_key == "main-key"
    assert fallback_rewriter._llm._model == "main-model"


def test_llm_complete_does_not_retry_permanent_400() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, request=request)

    client = OpenAICompatibleClient(retry_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.complete([{"role": "user", "content": "hello"}], []))

    assert attempts == 1


def test_llm_stream_retries_before_first_delta() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, request=request)
        body = 'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
        return httpx.Response(200, request=request, text=body)

    client = OpenAICompatibleClient(retry_settings(), transport=httpx.MockTransport(handler))

    async def collect() -> list[dict[str, str]]:
        return [delta async for delta in client.stream_chat([{"role": "user", "content": "hello"}], [])]

    deltas = asyncio.run(collect())

    assert attempts == 2
    assert deltas == [{"content": "ok"}]


class _FailAfterFirstDelta(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
        raise httpx.ReadError("stream dropped")



def test_llm_stream_does_not_retry_after_user_visible_delta() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(200, request=request, stream=_FailAfterFirstDelta())

    client = OpenAICompatibleClient(retry_settings(), transport=httpx.MockTransport(handler))

    async def collect() -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        with pytest.raises(httpx.ReadError):
            async for delta in client.stream_chat([{"role": "user", "content": "hello"}], []):
                items.append(delta)
        return items

    deltas = asyncio.run(collect())

    assert attempts == 1
    assert deltas == [{"content": "partial"}]


def test_tavily_retries_connect_error_then_succeeds() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("temporary offline", request=request)
        return httpx.Response(
            200,
            request=request,
            json={"results": [{"title": "result", "url": "https://example.test"}]},
        )

    tool = WebSearchTool(retry_settings(), transport=httpx.MockTransport(handler))
    result = asyncio.run(tool.call('{"query":"retry test"}'))

    assert attempts == 2
    assert result["source"] == "tavily"
    assert result["results"][0]["title"] == "result"


def test_embedding_can_use_provider_credentials_independent_from_chat_provider() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(
            200,
            request=request,
            json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]},
        )

    provider = DashScopeEmbeddingClient(
        retry_settings(
            openai_api_key="chat-key",
            openai_base_url="https://chat.example.test/v1",
            embedding_api_key="embedding-key",
            embedding_base_url="https://embedding.example.test/v1",
            embedding_dimension=3,
        ),
        transport=httpx.MockTransport(handler),
    )

    result = provider.embed(["hello"])

    assert result == [[0.1, 0.2, 0.3]]
    assert captured == {
        "url": "https://embedding.example.test/v1/embeddings",
        "authorization": "Bearer embedding-key",
    }


def test_embedding_retries_transient_status_then_succeeds() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(
            200,
            request=request,
            json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]},
        )

    provider = DashScopeEmbeddingClient(
        retry_settings(embedding_dimension=3),
        transport=httpx.MockTransport(handler),
    )
    result = provider.embed(["hello"])

    assert attempts == 2
    assert result == [[0.1, 0.2, 0.3]]


def test_image_describer_can_use_dedicated_vision_provider() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization", "")
        captured["model"] = str(json.loads(request.content)["model"])
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": "vision ok"}}]},
        )

    describer = OpenAICompatibleImageDescriber(
        retry_settings(
            openai_api_key="main-key",
            openai_base_url="https://main.example.test/v1",
            image_model="main-image-model",
            vision_api_key="vision-key",
            vision_base_url="https://vision.example.test/v1",
            vision_model="auto/best-vision",
        ),
        transport=httpx.MockTransport(handler),
    )
    result = describer.describe(content=b"image", content_type="image/png")

    assert result == "vision ok"
    assert captured == {
        "url": "https://vision.example.test/v1/chat/completions",
        "authorization": "Bearer vision-key",
        "model": "auto/best-vision",
    }


def test_image_describer_retries_transient_status_then_succeeds() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, request=request)
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": "a diagram"}}]},
        )

    describer = OpenAICompatibleImageDescriber(
        retry_settings(),
        transport=httpx.MockTransport(handler),
    )
    result = describer.describe(content=b"image", content_type="image/png")

    assert attempts == 2
    assert result == "a diagram"


def test_ppt_image_generator_retries_transient_status_then_succeeds() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(
            200,
            request=request,
            json={
                "output": {
                    "choices": [
                        {"message": {"content": [{"image": "https://images.test/generated.png"}]}}
                    ]
                }
            },
        )

    generator = QwenPptImageGenerator(
        retry_settings(ppt_image_endpoint="https://images.test/generate"),
        transport=httpx.MockTransport(handler),
    )
    result = asyncio.run(generator.generate("diagram"))

    assert attempts == 2
    assert result == "https://images.test/generated.png"


def test_ppt_image_download_reuses_client_and_retries() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(200, request=request, content=b"png-bytes")

    class FakeGenerator:
        async def generate(self, prompt: str) -> str | None:
            assert prompt == "diagram"
            return "https://images.test/generated.png"

    class FakeObjectStore:
        def __init__(self) -> None:
            self.uploaded: bytes | None = None

        def upload(self, *, object_name: str, content: bytes, content_type: str) -> str:
            assert object_name.startswith("ppt/conversation/images/")
            assert content_type == "image/png"
            self.uploaded = content
            return "http://minio.test/generated.png"

        def delete(self, object_name: str) -> None:
            raise AssertionError(f"unexpected delete: {object_name}")

    async def run_case() -> tuple[list[tuple[str, bool]], FakeObjectStore]:
        store = FakeObjectStore()
        schema: dict[str, object] = {
            "slides": [
                {
                    "data": {
                        "hero": {
                            "type": "image",
                            "content": "diagram",
                            "url": "",
                        }
                    }
                }
            ]
        }
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            outcomes = await materialize_ppt_images(
                schema,
                conversation_id="conversation",
                generator=FakeGenerator(),
                object_store=store,
                download_timeout_seconds=5,
                http_client=client,
                max_retries=2,
                retry_base_seconds=0,
                retry_max_seconds=0,
            )
        assert schema["slides"][0]["data"]["hero"]["url"] == "http://minio.test/generated.png"
        return outcomes, store

    outcomes, store = asyncio.run(run_case())

    assert attempts == 2
    assert outcomes == [("hero", True)]
    assert store.uploaded == b"png-bytes"
