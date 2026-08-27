"""Stable Skills Agent event-contract regression tests."""

from app.schemas import AgentEvent


def test_skills_tool_timeline_uses_canonical_event_shape() -> None:
    start = AgentEvent.tool_start("read_skill", "skill-1", {"name": "research"})
    end = AgentEvent.tool_end("read_skill", "skill-1", {"content": "skill instructions"})

    assert start.type == "tool_start"
    assert end.type == "tool_end"
    assert start.tool_name == end.tool_name == "read_skill"
    assert start.tool_call_id == end.tool_call_id == "skill-1"
