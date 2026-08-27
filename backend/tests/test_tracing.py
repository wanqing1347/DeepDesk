import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.providers.llm import OpenAICompatibleClient
from app.schemas import AgentEvent
from app.tracing import bind_tracing_manager, reset_tracing_manager, start_span

_TRACE_ID = int("1234567890abcdef1234567890abcdef", 16)


class _FakeSpanContext:
    is_valid = True
    trace_id = _TRACE_ID


@dataclass
class _FakeSpan:
    name: str
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    status: Any = None

    def get_span_context(self) -> _FakeSpanContext:
        return _FakeSpanContext()

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        self.events.append((name, attributes or {}))

    def record_exception(self, _exc: BaseException) -> None:
        return None

    def set_status(self, status: Any) -> None:
        self.status = status


class _InvalidSpan:
    class _Context:
        is_valid = False
        trace_id = 0

    def get_span_context(self) -> _Context:
        return self._Context()


class _FakeTraceModule:
    def __init__(self) -> None:
        self.current: Any = _InvalidSpan()

    def get_current_span(self) -> Any:
        return self.current


class _FakeTracer:
    def __init__(self, trace_module: _FakeTraceModule) -> None:
        self.trace_module = trace_module
        self.spans: list[_FakeSpan] = []

    @contextmanager
    def start_as_current_span(self, name: str, **kwargs):
        span = _FakeSpan(name=name, attributes=dict(kwargs.get("attributes") or {}))
        previous = self.trace_module.current
        self.trace_module.current = span
        self.spans.append(span)
        try:
            yield span
        finally:
            self.trace_module.current = previous


class _FakeSpanKind:
    SERVER = "server"
    CLIENT = "client"
    INTERNAL = "internal"


class _FakeStatusCode:
    ERROR = "error"


class _FakeStatus:
    def __init__(self, code: str, description: str) -> None:
        self.code = code
        self.description = description


class _FakePropagator:
    def __init__(self) -> None:
        self.extracted: dict[str, str] | None = None

    def extract(self, carrier: dict[str, str]) -> dict[str, str]:
        self.extracted = carrier
        return carrier

    def inject(self, carrier: dict[str, str]) -> None:
        carrier["traceparent"] = "00-1234567890abcdef1234567890abcdef-1234567890abcdef-01"


def _enable_fake_tracing(manager) -> _FakeTracer:
    trace_module = _FakeTraceModule()
    tracer = _FakeTracer(trace_module)
    manager.enabled = True
    manager._tracer = tracer
    manager._propagator = _FakePropagator()
    manager._trace_module = trace_module
    manager._span_kind = _FakeSpanKind
    manager._status = _FakeStatus
    manager._status_code = _FakeStatusCode
    return tracer


def test_http_and_agent_spans_share_trace_id_and_response_exposes_it() -> None:
    app = create_app(Settings())
    tracer = _enable_fake_tracing(app.state.tracing)

    async def fake_run(_conversation_id: str, _query: str):
        yield AgentEvent(type="text", content="ok")
        yield AgentEvent.complete()

    app.state.web_search_agent.run = fake_run
    incoming = "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"

    with TestClient(app) as client:
        response = client.get(
            "/agent/chat/stream",
            params={"query": "hello", "conversationId": "trace-conversation"},
            headers={"traceparent": incoming},
        )

    assert response.status_code == 200
    assert response.headers["x-trace-id"] == "1234567890abcdef1234567890abcdef"
    assert [span.name for span in tracer.spans] == [
        "HTTP GET /agent/chat/stream",
        "agent.websearch",
    ]
    request_span = tracer.spans[0]
    assert request_span.attributes["deepdesk.agent.type"] == "websearch"
    assert request_span.attributes["deepdesk.conversation.id"] == "trace-conversation"
    assert app.state.tracing._propagator.extracted["traceparent"] == incoming


def test_provider_span_injects_w3c_traceparent_without_prompt_attributes() -> None:
    app = create_app(Settings())
    tracer = _enable_fake_tracing(app.state.tracing)
    captured_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(request.headers)
        return httpx.Response(
            200,
            request=request,
            json={"choices": [{"message": {"content": "ok"}}]},
        )

    provider = OpenAICompatibleClient(
        Settings(openai_api_key="test-key"),
        transport=httpx.MockTransport(handler),
    )
    token = bind_tracing_manager(app.state.tracing)
    try:
        with start_span("test.root"):
            result = asyncio.run(provider.complete([{"role": "user", "content": "secret prompt"}], []))
    finally:
        reset_tracing_manager(token)

    assert result["choices"][0]["message"]["content"] == "ok"
    assert captured_headers["traceparent"].startswith("00-1234567890abcdef1234567890abcdef-")
    assert [span.name for span in tracer.spans] == ["test.root", "provider.llm.complete"]
    provider_span = tracer.spans[-1]
    assert provider_span.attributes == {
        "deepdesk.provider.name": "llm",
        "deepdesk.provider.operation": "complete",
    }
    assert "secret prompt" not in repr(provider_span.attributes)
