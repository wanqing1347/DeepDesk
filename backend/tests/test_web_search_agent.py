import asyncio
import json
from copy import deepcopy
from typing import Any, ClassVar

from app.agents.web_search import SYSTEM_PROMPT, WebSearchAgent
from app.config import Settings
from app.memory import InMemoryConversationStore


class FakeLLM:
    def __init__(
        self,
        streams: list[list[dict[str, Any]]],
        completions: list[dict[str, Any]] | None = None,
    ) -> None:
        self.streams = [list(stream) for stream in streams]
        self.completions = list(completions or [])
        self.stream_tools: list[list[dict[str, Any]]] = []
        self.stream_messages: list[list[dict[str, Any]]] = []
        self.complete_messages: list[list[dict[str, Any]]] = []

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ):
        self.stream_tools.append(deepcopy(tools))
        self.stream_messages.append(deepcopy(messages))
        for delta in self.streams.pop(0):
            await asyncio.sleep(0)
            yield delta

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        self.complete_messages.append(deepcopy(messages))
        return self.completions.pop(0)


class FakeSearch:
    name = "web_search"
    definition: ClassVar[dict[str, Any]] = {"type": "function", "function": {"name": name}}

    async def call(self, arguments: str) -> dict[str, Any]:
        args = json.loads(arguments)
        return {
            "results": [
                {
                    "title": f"Result {args['query']}",
                    "url": f"https://example.com/{args['query']}",
                    "content": f"query={args['query']}",
                }
            ],
            "source": "fake",
        }


class FailingSearch(FakeSearch):
    async def call(self, arguments: str) -> dict[str, Any]:
        raise RuntimeError("search unavailable")


class ConcurrentSearch(FakeSearch):
    def __init__(self) -> None:
        self.started: list[str] = []
        self._both_started = asyncio.Event()

    async def call(self, arguments: str) -> dict[str, Any]:
        query = str(json.loads(arguments)["query"])
        self.started.append(query)
        if len(self.started) >= 2:
            self._both_started.set()
        await asyncio.wait_for(self._both_started.wait(), timeout=0.5)
        return await super().call(arguments)


def _answer_stream(*parts: str) -> list[dict[str, Any]]:
    return [{"content": part} for part in parts]


def _tool_stream(query: str = "AI", *, call_id: str = "call-1", index: int = 0) -> list[dict[str, Any]]:
    arguments = json.dumps({"query": query}, ensure_ascii=False)
    midpoint = max(1, len(arguments) // 2)
    return [
        {
            "tool_calls": [
                {
                    "index": index,
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "web_search", "arguments": arguments[:midpoint]},
                }
            ]
        },
        {
            "tool_calls": [
                {
                    "index": index,
                    "function": {"arguments": arguments[midpoint:]},
                }
            ]
        },
    ]


def _recommend_response(*questions: str) -> dict[str, Any]:
    return {"choices": [{"message": {"role": "assistant", "content": json.dumps(list(questions), ensure_ascii=False)}}]}


def _settings(**kwargs: Any) -> Settings:
    return Settings(openai_api_key="test", enable_recommendations=False, **kwargs)


def test_chat_system_prompt_is_general_purpose_and_search_is_on_demand() -> None:
    assert "通用 AI 助手" in SYSTEM_PROMPT
    assert "企业联网查询助手" not in SYSTEM_PROMPT
    assert "需要最新信息" in SYSTEM_PROMPT
    assert "不要为了使用工具而搜索" in SYSTEM_PROMPT
    assert "不要介绍自己的系统身份" in SYSTEM_PROMPT


def test_web_search_streams_tool_delta_reference_and_complete() -> None:
    async def scenario() -> None:
        memory = InMemoryConversationStore()
        agent = WebSearchAgent(_settings(), memory)
        agent._llm = FakeLLM([_tool_stream(), _answer_stream("最终", "答案")])  # type: ignore[assignment]
        agent._search = FakeSearch()  # type: ignore[assignment]

        events = [event async for event in agent.run("conversation-1", "问题")]

        assert [event.type for event in events] == [
            "thinking",
            "thinking",
            "thinking",
            "tool_start",
            "tool_end",
            "text",
            "text",
            "reference",
            "complete",
        ]
        assert events[3].tool_name == "web_search"
        assert events[3].tool_call_id == "call-1"
        assert json.loads(str(events[3].arguments)) == {"query": "AI"}
        assert events[7].count == 1
        assert await memory.get("conversation-1") == [
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": "最终答案"},
        ]

    asyncio.run(scenario())


def test_tool_failure_is_isolated_and_agent_can_still_finish() -> None:
    async def scenario() -> None:
        memory = InMemoryConversationStore()
        agent = WebSearchAgent(_settings(), memory)
        agent._llm = FakeLLM([_tool_stream(), _answer_stream("降级回答")])  # type: ignore[assignment]
        agent._search = FailingSearch()  # type: ignore[assignment]

        events = [event async for event in agent.run("conversation-2", "问题")]
        tool_end = next(event for event in events if event.type == "tool_end")

        assert "工具执行失败" in str(tool_end.result)
        assert any(event.type == "text" and event.content == "降级回答" for event in events)
        assert events[-1].type == "complete"

    asyncio.run(scenario())


def test_round_limit_forces_streaming_final_answer_without_tools() -> None:
    async def scenario() -> None:
        memory = InMemoryConversationStore()
        agent = WebSearchAgent(_settings(max_agent_rounds=1), memory)
        fake_llm = FakeLLM([_tool_stream(), _answer_stream("基于现有", "信息的总结")])
        agent._llm = fake_llm  # type: ignore[assignment]
        agent._search = FakeSearch()  # type: ignore[assignment]

        events = [event async for event in agent.run("conversation-3", "问题")]

        assert fake_llm.stream_tools[0]
        assert fake_llm.stream_tools[1] == []
        assert any(event.type == "thinking" and "最大推理轮次" in str(event.content) for event in events)
        text = "".join(str(event.content) for event in events if event.type == "text")
        assert text == "基于现有信息的总结"
        assert events[-1].type == "complete"

    asyncio.run(scenario())


def test_multiple_tool_calls_execute_concurrently_but_return_to_model_in_original_order() -> None:
    async def scenario() -> None:
        memory = InMemoryConversationStore()
        agent = WebSearchAgent(_settings(), memory)
        first = _tool_stream("first", call_id="call-1", index=0)
        second = _tool_stream("second", call_id="call-2", index=1)
        combined_stream = [
            {"tool_calls": first[0]["tool_calls"] + second[0]["tool_calls"]},
            {"tool_calls": first[1]["tool_calls"] + second[1]["tool_calls"]},
        ]
        fake_llm = FakeLLM([combined_stream, _answer_stream("完成")])
        concurrent_search = ConcurrentSearch()
        agent._llm = fake_llm  # type: ignore[assignment]
        agent._search = concurrent_search  # type: ignore[assignment]

        events = [event async for event in agent.run("conversation-4", "问题")]

        assert set(concurrent_search.started) == {"first", "second"}
        tool_ends = [event for event in events if event.type == "tool_end"]
        assert [event.tool_call_id for event in tool_ends] == ["call-1", "call-2"]
        second_round_messages = fake_llm.stream_messages[1]
        tool_messages = [message for message in second_round_messages if message.get("role") == "tool"]
        assert [message["tool_call_id"] for message in tool_messages[-2:]] == ["call-1", "call-2"]

    asyncio.run(scenario())


def test_recommendations_are_emitted_as_array_and_secondary_failure_is_non_fatal() -> None:
    async def scenario() -> None:
        memory = InMemoryConversationStore()
        agent = WebSearchAgent(Settings(openai_api_key="test", enable_recommendations=True), memory)
        fake_llm = FakeLLM(
            [_answer_stream("回答")],
            [_recommend_response("继续了解什么？", "有哪些例子？", "如何实践？")],
        )
        agent._llm = fake_llm  # type: ignore[assignment]

        events = [event async for event in agent.run("conversation-5", "问题")]
        recommend = next(event for event in events if event.type == "recommend")
        assert recommend.content == ["继续了解什么？", "有哪些例子？", "如何实践？"]
        assert recommend.count == 3
        assert events[-1].type == "complete"

        failing_agent = WebSearchAgent(Settings(openai_api_key="test", enable_recommendations=True), memory)
        failing_agent._llm = FakeLLM([_answer_stream("仍然成功")], [])  # type: ignore[assignment]
        failing_events = [event async for event in failing_agent.run("conversation-6", "问题")]
        assert "".join(str(event.content) for event in failing_events if event.type == "text") == "仍然成功"
        assert failing_events[-1].type == "complete"

    asyncio.run(scenario())
