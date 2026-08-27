import json
from collections.abc import AsyncIterator

from .metrics import record_agent_error
from .schemas import AgentEvent


def event_json(event: AgentEvent) -> str:
    return json.dumps(event.model_dump(exclude_none=True, by_alias=True), ensure_ascii=False)


async def as_sse(events: AsyncIterator[AgentEvent]) -> AsyncIterator[str]:
    try:
        async for event in events:
            if event.type == "error":
                record_agent_error(str(event.code or "UNKNOWN"))
            yield f"data: {event_json(event)}\n\n"
    except Exception as exc:
        error = AgentEvent.error("流式响应异常", code="SSE_STREAM_ERROR", detail=str(exc))
        record_agent_error("SSE_STREAM_ERROR")
        yield f"data: {event_json(error)}\n\n"
        yield f"data: {event_json(AgentEvent.complete())}\n\n"

