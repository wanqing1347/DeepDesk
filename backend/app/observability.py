import json
import logging
import time
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .metrics import MetricsRegistry, bind_metrics_context, reset_metrics_context
from .tracing import (
    TracingManager,
    bind_tracing_manager,
    current_trace_id,
    reset_tracing_manager,
    start_span,
)

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
conversation_id_var: ContextVar[str] = ContextVar("conversation_id", default="")
agent_type_var: ContextVar[str] = ContextVar("agent_type", default="")

access_logger = logging.getLogger("deepdesk.access")

_AGENT_TYPES = {
    "/agent/chat/stream": "websearch",
    "/agent/file/stream": "file",
    "/agent/skills/stream": "skills",
    "/agent/deep/stream": "plan-execute",
    "/agent/pptx/stream": "pptx",
}


@dataclass(slots=True)
class RequestContextTokens:
    request_id: Token[str]
    conversation_id: Token[str]
    agent_type: Token[str]


def bind_request_context(request: Request) -> tuple[RequestContextTokens, str, str, str]:
    request_id = request.headers.get("X-Request-ID", "").strip() or uuid.uuid4().hex
    conversation_id = request.query_params.get("conversationId", "").strip()
    agent_type = _AGENT_TYPES.get(request.url.path, "")
    tokens = RequestContextTokens(
        request_id=request_id_var.set(request_id),
        conversation_id=conversation_id_var.set(conversation_id),
        agent_type=agent_type_var.set(agent_type),
    )
    return tokens, request_id, conversation_id, agent_type


def reset_request_context(tokens: RequestContextTokens) -> None:
    request_id_var.reset(tokens.request_id)
    conversation_id_var.reset(tokens.conversation_id)
    agent_type_var.reset(tokens.agent_type)


def log_http_request(
    *,
    request: Request,
    status_code: int,
    request_id: str,
    conversation_id: str,
    agent_type: str,
    started_at: float,
    error: BaseException | None = None,
) -> None:
    payload: dict[str, Any] = {
        "event": "http_request",
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status_code": status_code,
        "duration_ms": round((time.perf_counter() - started_at) * 1000, 3),
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    if agent_type:
        payload["agent_type"] = agent_type
    trace_id = current_trace_id()
    if trace_id:
        payload["trace_id"] = trace_id
    if error is not None:
        payload["error_type"] = type(error).__name__
    access_logger.info(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))


class RequestContextMiddleware:
    """Attach request ids and emit one structured log when the full HTTP body finishes."""

    def __init__(self, app: ASGIApp, metrics: MetricsRegistry, tracing: TracingManager) -> None:
        self.app = app
        self._metrics = metrics
        self._tracing = tracing

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        tokens, request_id, conversation_id, agent_type = bind_request_context(request)
        metrics_token = bind_metrics_context(self._metrics, agent_type)
        tracing_token = bind_tracing_manager(self._tracing)
        parent_context = self._tracing.extract(request.headers)
        span_attributes: dict[str, Any] = {
            "http.request.method": request.method,
            "url.path": request.url.path,
            "deepdesk.request.id": request_id,
        }
        if conversation_id:
            span_attributes["deepdesk.conversation.id"] = conversation_id
        if agent_type:
            span_attributes["deepdesk.agent.type"] = agent_type

        try:
            with start_span(
                f"HTTP {request.method} {request.url.path}",
                kind="server",
                attributes=span_attributes,
                parent_context=parent_context,
            ) as request_span:
                started_at = time.perf_counter()
                status_code = 500
                logged = False
                first_response_recorded = False

                async def send_wrapper(message: Message) -> None:
                    nonlocal status_code, logged, first_response_recorded
                    if message["type"] == "http.response.start":
                        status_code = int(message["status"])
                        if request_span is not None:
                            request_span.set_attribute("http.response.status_code", status_code)
                        headers = list(message.get("headers", []))
                        if not any(name.lower() == b"x-request-id" for name, _ in headers):
                            headers.append((b"x-request-id", request_id.encode("latin-1", errors="replace")))
                        trace_id = current_trace_id()
                        if trace_id and not any(name.lower() == b"x-trace-id" for name, _ in headers):
                            headers.append((b"x-trace-id", trace_id.encode("ascii")))
                        message["headers"] = headers
                    elif message["type"] == "http.response.body":
                        body = message.get("body", b"")
                        if agent_type and body and not first_response_recorded:
                            first_response_recorded = True
                            self._metrics.observe(
                                "deepdesk_agent_first_response_seconds",
                                max(0.0, time.perf_counter() - started_at),
                                labels={"agent_type": agent_type},
                            )
                        if not message.get("more_body", False) and not logged:
                            logged = True
                            duration_seconds = max(0.0, time.perf_counter() - started_at)
                            if agent_type:
                                request_labels = {"agent_type": agent_type, "status_code": str(status_code)}
                                self._metrics.increment("deepdesk_agent_requests_total", labels=request_labels)
                                self._metrics.observe(
                                    "deepdesk_agent_request_duration_seconds",
                                    duration_seconds,
                                    labels=request_labels,
                                )
                            log_http_request(
                                request=request,
                                status_code=status_code,
                                request_id=request_id,
                                conversation_id=conversation_id,
                                agent_type=agent_type,
                                started_at=started_at,
                            )
                    await send(message)

                try:
                    await self.app(scope, receive, send_wrapper)
                except BaseException as exc:
                    if not logged:
                        duration_seconds = max(0.0, time.perf_counter() - started_at)
                        if agent_type:
                            request_labels = {"agent_type": agent_type, "status_code": str(status_code)}
                            self._metrics.increment("deepdesk_agent_requests_total", labels=request_labels)
                            self._metrics.observe(
                                "deepdesk_agent_request_duration_seconds",
                                duration_seconds,
                                labels=request_labels,
                            )
                        log_http_request(
                            request=request,
                            status_code=status_code,
                            request_id=request_id,
                            conversation_id=conversation_id,
                            agent_type=agent_type,
                            started_at=started_at,
                            error=exc,
                        )
                    raise
        finally:
            reset_tracing_manager(tracing_token)
            reset_metrics_context(metrics_token)
            reset_request_context(tokens)
