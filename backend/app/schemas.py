from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AgentEventType = Literal[
    "text",
    "thinking",
    "tool_start",
    "tool_end",
    "reference",
    "recommend",
    "error",
    "complete",
]


class AgentEvent(BaseModel):
    """Canonical SSE payload consumed by agent clients."""

    model_config = ConfigDict(populate_by_name=True)

    type: AgentEventType
    content: Any | None = None
    count: int | None = None
    tool_name: str | None = Field(default=None, alias="toolName")
    tool_call_id: str | None = Field(default=None, alias="toolCallId")
    arguments: Any | None = None
    result: Any | None = None
    code: str | None = None
    message: str | None = None
    detail: str | None = None

    @classmethod
    def tool_start(cls, tool_name: str, tool_call_id: str, arguments: Any) -> "AgentEvent":
        return cls(type="tool_start", tool_name=tool_name, tool_call_id=tool_call_id, arguments=arguments)

    @classmethod
    def tool_end(cls, tool_name: str, tool_call_id: str, result: Any) -> "AgentEvent":
        return cls(type="tool_end", tool_name=tool_name, tool_call_id=tool_call_id, result=result)

    @classmethod
    def error(cls, message: str, *, code: str = "AGENT_ERROR", detail: str | None = None) -> "AgentEvent":
        # Keep content for older consumers while also populating message for the
        # current frontend's error timeline.
        return cls(type="error", content=message, code=code, message=message, detail=detail)

    @classmethod
    def complete(cls) -> "AgentEvent":
        return cls(type="complete")


class ChatRequest(BaseModel):
    query: str = Field(min_length=1)
    conversation_id: str = Field(alias="conversationId", min_length=1)


class StopResponse(BaseModel):
    success: bool
    message: str

