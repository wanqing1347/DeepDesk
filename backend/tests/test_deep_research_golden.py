"""Stable Deep Research event-contract regression tests."""

from app.schemas import AgentEvent


def test_deep_research_public_timeline_keeps_nested_tools_internal() -> None:
    events = [
        AgentEvent(type="thinking", content="正在执行研究任务"),
        AgentEvent(type="text", content="研究报告"),
        AgentEvent(type="reference", content=[{"title": "source", "url": "https://example.com"}], count=1),
        AgentEvent.complete(),
    ]

    assert [event.type for event in events] == ["thinking", "text", "reference", "complete"]
    assert not any(event.type in {"tool_start", "tool_end"} for event in events)
    assert events[-1].model_dump(exclude_none=True, by_alias=True) == {"type": "complete"}
