from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

from .config import Settings

_tracing_manager_var: ContextVar[TracingManager | None] = ContextVar("tracing_manager", default=None)


class TracingManager:
    """Application-scoped OpenTelemetry tracing without mutating the process-global provider."""

    def __init__(self, settings: Settings) -> None:
        self.enabled = settings.tracing_enabled
        self._provider: Any | None = None
        self._tracer: Any | None = None
        self._propagator: Any | None = None
        self._trace_module: Any | None = None
        self._span_kind: Any | None = None
        self._status: Any | None = None
        self._status_code: Any | None = None
        if not self.enabled:
            return

        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import SERVICE_NAME, Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor
            from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased
            from opentelemetry.trace import SpanKind, Status, StatusCode
            from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Tracing 已启用，但 OpenTelemetry 依赖未安装；请安装项目依赖后重试"
            ) from exc

        provider = TracerProvider(
            resource=Resource.create({SERVICE_NAME: settings.app_name}),
            sampler=ParentBased(TraceIdRatioBased(settings.tracing_sample_ratio)),
        )
        if settings.tracing_exporter == "otlp":
            exporter = OTLPSpanExporter(endpoint=settings.tracing_otlp_endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        elif settings.tracing_exporter == "console":
            provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))

        self._provider = provider
        self._tracer = provider.get_tracer("deepdesk-backend")
        self._propagator = TraceContextTextMapPropagator()
        self._trace_module = trace
        self._span_kind = SpanKind
        self._status = Status
        self._status_code = StatusCode

    @property
    def tracer(self) -> Any | None:
        return self._tracer

    def extract(self, headers: Mapping[str, str]) -> Any | None:
        if not self.enabled or self._propagator is None:
            return None
        carrier = {key.lower(): value for key, value in headers.items()}
        return self._propagator.extract(carrier)

    def inject(self, headers: dict[str, str]) -> None:
        if not self.enabled or self._propagator is None:
            return
        self._propagator.inject(headers)

    def span_kind(self, kind: str) -> Any:
        if self._span_kind is None:
            return None
        return {
            "server": self._span_kind.SERVER,
            "client": self._span_kind.CLIENT,
            "internal": self._span_kind.INTERNAL,
        }.get(kind, self._span_kind.INTERNAL)

    def current_trace_id(self) -> str:
        if self._trace_module is None:
            return ""
        span_context = self._trace_module.get_current_span().get_span_context()
        if not span_context.is_valid:
            return ""
        return format(span_context.trace_id, "032x")

    def current_span(self) -> Any | None:
        if self._trace_module is None:
            return None
        span = self._trace_module.get_current_span()
        return span if span.get_span_context().is_valid else None

    def mark_error(self, span: Any | None, exc: BaseException | str) -> None:
        if span is None or self._status is None or self._status_code is None:
            return
        if isinstance(exc, BaseException):
            span.record_exception(exc)
            description = type(exc).__name__
        else:
            description = exc
        span.set_status(self._status(self._status_code.ERROR, description))

    def shutdown(self) -> None:
        if self._provider is not None:
            self._provider.shutdown()


def bind_tracing_manager(manager: TracingManager) -> Token[TracingManager | None]:
    return _tracing_manager_var.set(manager)


def reset_tracing_manager(token: Token[TracingManager | None]) -> None:
    _tracing_manager_var.reset(token)


def current_tracing_manager() -> TracingManager | None:
    return _tracing_manager_var.get()


@contextmanager
def start_span(
    name: str,
    *,
    kind: str = "internal",
    attributes: dict[str, Any] | None = None,
    parent_context: Any | None = None,
) -> Iterator[Any | None]:
    manager = current_tracing_manager()
    tracer = manager.tracer if manager is not None else None
    if tracer is None:
        yield None
        return

    with tracer.start_as_current_span(
        name,
        context=parent_context,
        kind=manager.span_kind(kind),
        attributes=attributes,
        record_exception=True,
        set_status_on_exception=True,
    ) as span:
        yield span


def set_span_error(span: Any | None, exc: BaseException | str) -> None:
    manager = current_tracing_manager()
    if manager is not None:
        manager.mark_error(span, exc)


def current_trace_id() -> str:
    manager = current_tracing_manager()
    return manager.current_trace_id() if manager is not None else ""


def inject_trace_headers(headers: Mapping[str, str] | None = None) -> dict[str, str]:
    result = dict(headers or {})
    manager = current_tracing_manager()
    if manager is not None:
        manager.inject(result)
    return result


def record_trace_event(name: str, attributes: dict[str, Any] | None = None) -> None:
    manager = current_tracing_manager()
    span = manager.current_span() if manager is not None else None
    if span is not None:
        span.add_event(name, attributes or {})


async def trace_agent_stream(agent_type: str, events: AsyncIterator[Any]) -> AsyncIterator[Any]:
    with start_span(
        f"agent.{agent_type}",
        attributes={"deepdesk.agent.type": agent_type},
    ) as span:
        try:
            async for event in events:
                event_type = str(getattr(event, "type", ""))
                if span is not None and event_type == "error":
                    code = str(getattr(event, "code", "") or "UNKNOWN")
                    span.set_attribute("deepdesk.agent.error_code", code)
                    set_span_error(span, code)
                yield event
        except BaseException as exc:
            set_span_error(span, exc)
            raise


@contextmanager
def trace_tool_call(tool_name: str) -> Iterator[Any | None]:
    with start_span(
        f"tool.{tool_name}",
        attributes={"deepdesk.tool.name": tool_name},
    ) as span:
        try:
            yield span
        except BaseException as exc:
            set_span_error(span, exc)
            raise


@contextmanager
def trace_provider_call(provider: str, operation: str) -> Iterator[Any | None]:
    with start_span(
        f"provider.{provider}.{operation}",
        kind="client",
        attributes={
            "deepdesk.provider.name": provider,
            "deepdesk.provider.operation": operation,
        },
    ) as span:
        try:
            yield span
        except BaseException as exc:
            set_span_error(span, exc)
            raise
