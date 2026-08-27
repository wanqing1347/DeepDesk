import asyncio
import json

from app.schemas import AgentEvent
from app.sse import as_sse, event_json


def _payload(sse_chunk: str) -> dict[str, object]:
    assert sse_chunk.startswith("data: ")
    return json.loads(sse_chunk.removeprefix("data: ").strip())


def test_event_json_preserves_reference_contract() -> None:
    payload = json.loads(event_json(AgentEvent(type="reference", content=[{"url": "https://example.com"}], count=1)))
    assert payload == {"type": "reference", "content": [{"url": "https://example.com"}], "count": 1}


def test_event_json_uses_frontend_tool_field_names() -> None:
    payload = json.loads(event_json(AgentEvent.tool_start("web_search", "call-1", '{"query":"AI"}')))
    assert payload == {
        "type": "tool_start",
        "toolName": "web_search",
        "toolCallId": "call-1",
        "arguments": '{"query":"AI"}',
    }


def test_error_event_supports_current_and_legacy_frontends() -> None:
    payload = json.loads(event_json(AgentEvent.error("调用失败", code="TEST_ERROR", detail="boom")))
    assert payload == {
        "type": "error",
        "content": "调用失败",
        "code": "TEST_ERROR",
        "message": "调用失败",
        "detail": "boom",
    }


def test_as_sse_turns_unexpected_error_into_terminal_events() -> None:
    async def failing_events():
        yield AgentEvent(type="thinking", content="start")
        raise RuntimeError("boom")

    async def collect() -> list[dict[str, object]]:
        return [_payload(chunk) async for chunk in as_sse(failing_events())]

    payloads = asyncio.run(collect())
    assert [payload["type"] for payload in payloads] == ["thinking", "error", "complete"]
    assert payloads[1]["code"] == "SSE_STREAM_ERROR"
    assert payloads[1]["message"] == "流式响应异常"
    assert payloads[1]["detail"] == "boom"
