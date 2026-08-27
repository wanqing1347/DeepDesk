import asyncio
import json
from copy import deepcopy
from typing import Any

from app.context import ContextCompactor, ContextPolicy, estimate_tokens


class FakeCompletionLLM:
    def __init__(self, content: str | None = None, error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.calls: list[list[dict[str, Any]]] = []

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls.append(deepcopy(messages))
        if self.error is not None:
            raise self.error
        return {"choices": [{"message": {"content": self.content or ""}}]}


def test_token_estimator_handles_cjk_ascii_heuristic() -> None:
    messages = [{"role": "user", "content": "中文中文abcd"}]

    # 4 CJK / 1.5 + 4 ASCII / 4 = int(3.66...) = 3
    assert estimate_tokens(messages) == 3


def test_micro_compact_replaces_old_tool_content_and_args_but_protects_read_skill() -> None:
    async def scenario() -> None:
        messages: list[dict[str, Any]] = [{"role": "system", "content": "system"}]
        for index in range(3):
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call-{index}",
                            "type": "function",
                            "function": {"name": "grep", "arguments": json.dumps({"pattern": "x" * 80})},
                        }
                    ],
                }
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": f"call-{index}",
                    "name": "grep",
                    "content": "result-" + "y" * 80,
                }
            )
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "skill-call",
                            "type": "function",
                            "function": {"name": "read_skill", "arguments": "z" * 100},
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "skill-call",
                    "name": "read_skill",
                    "content": "skill-content-" + "s" * 100,
                },
            ]
        )
        compactor = ContextCompactor(
            ContextPolicy(token_threshold=100_000, keep_recent_tools=1, max_tool_length=20),
            FakeCompletionLLM("unused"),
        )

        await compactor.compact(messages, "question")

        first_tool = next(message for message in messages if message.get("tool_call_id") == "call-0")
        assert json.loads(str(first_tool["content"]))["compacted"] is True
        first_assistant = next(
            message
            for message in messages
            if message.get("role") == "assistant"
            and message.get("tool_calls")
            and message["tool_calls"][0]["id"] == "call-0"
        )
        assert json.loads(first_assistant["tool_calls"][0]["function"]["arguments"])["compacted"] is True

        skill_tool = next(message for message in messages if message.get("tool_call_id") == "skill-call")
        assert str(skill_tool["content"]).startswith("skill-content-")
        skill_assistant = next(
            message
            for message in messages
            if message.get("role") == "assistant"
            and message.get("tool_calls")
            and message["tool_calls"][0]["id"] == "skill-call"
        )
        assert skill_assistant["tool_calls"][0]["function"]["arguments"] == "z" * 100

    asyncio.run(scenario())


def test_auto_compact_replaces_old_messages_with_structured_summary() -> None:
    async def scenario() -> None:
        llm = FakeCompletionLLM("### 一、历史对话摘要\nsummary")
        compactor = ContextCompactor(
            ContextPolicy(token_threshold=1, keep_recent_tools=4, max_tool_length=200),
            llm,
        )
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "很长的当前任务"},
            {"role": "assistant", "content": "之前回答"},
        ]

        await compactor.compact(messages, "当前问题")

        assert messages == [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "[对话已压缩] 以下是之前对话的摘要：\n### 一、历史对话摘要\nsummary"},
        ]
        assert llm.calls
        assert "当前问题" in str(llm.calls[0][1]["content"])

    asyncio.run(scenario())


def test_auto_compact_falls_back_to_recent_messages_when_summary_llm_fails() -> None:
    async def scenario() -> None:
        compactor = ContextCompactor(
            ContextPolicy(token_threshold=1),
            FakeCompletionLLM(error=RuntimeError("boom")),
        )
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "fallback question"},
            {"role": "assistant", "content": "fallback answer"},
        ]

        await compactor.compact(messages, "q")

        assert len(messages) == 2
        assert "摘要生成失败" in str(messages[1]["content"])
        assert "fallback question" in str(messages[1]["content"])

    asyncio.run(scenario())
