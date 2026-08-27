"""Stable WebSearch event-contract regression tests."""

from app.schemas import AgentEvent


def test_websearch_tool_events_keep_call_identity() -> None:
    start = AgentEvent.tool_start("web_search", "call-1", {"query": "agent frameworks"})
    end = AgentEvent.tool_end("web_search", "call-1", {"results": []})

    assert start.tool_name == end.tool_name == "web_search"
    assert start.tool_call_id == end.tool_call_id == "call-1"
    assert start.model_dump(exclude_none=True, by_alias=True)["toolName"] == "web_search"
    assert end.model_dump(exclude_none=True, by_alias=True)["toolCallId"] == "call-1"
