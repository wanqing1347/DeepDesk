import asyncio
import json
from copy import deepcopy
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

from app.agents.deep_research import (
    DeepResearchAgent,
    DeepResearchState,
    PlanTask,
    TaskResult,
    _TaskExecution,
)
from app.config import Settings
from app.memory import InMemoryConversationStore
from app.persistence import AiSession, Base, Database
from app.persistence.conversation_store import SqlConversationStore


class FakeLLM:
    def __init__(
        self,
        streams: list[list[dict[str, Any]]] | None = None,
        completions: list[dict[str, Any] | Exception] | None = None,
    ) -> None:
        self.streams = [list(stream) for stream in streams or []]
        self.completions = list(completions or [])
        self.stream_messages: list[list[dict[str, Any]]] = []
        self.complete_messages: list[list[dict[str, Any]]] = []
        self.complete_tools: list[list[dict[str, Any]]] = []
        self.complete_options: list[dict[str, Any]] = []

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        **_options: Any,
    ):
        self.stream_messages.append(deepcopy(messages))
        for delta in self.streams.pop(0):
            await asyncio.sleep(0)
            yield delta

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        **options: Any,
    ) -> dict[str, Any]:
        self.complete_messages.append(deepcopy(messages))
        self.complete_tools.append(deepcopy(tools))
        self.complete_options.append(deepcopy(options))
        result = self.completions.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeSearch:
    name = "web_search"
    definition: ClassVar[dict[str, Any]] = {
        "type": "function",
        "function": {"name": "web_search", "description": "search"},
    }

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def call(self, arguments: str) -> dict[str, Any]:
        payload = json.loads(arguments)
        self.calls.append(payload)
        return {
            "results": [
                {
                    "title": f"Result for {payload['query']}",
                    "url": "https://example.com/source",
                    "content": "fact",
                }
            ],
            "source": "fake",
        }


def _completion(content: str, *, tool_calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"content": content}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


def _stream(*parts: str) -> list[dict[str, Any]]:
    return [{"content": part} for part in parts]


def _settings(**kwargs: Any) -> Settings:
    return Settings(
        openai_api_key="test",
        search_mode="demo",
        enable_recommendations=False,
        **kwargs,
    )


def test_deep_state_keeps_only_latest_critique_and_extracts_task_results() -> None:
    state = DeepResearchState("conv", "question")
    state.add("user", "question")
    state.add("assistant", "【Critique Feedback】\nold")
    state.add("assistant", "【Completed Task Result】\ntaskId: one")
    state.add("assistant", "【Critique Feedback】\nlatest")
    state.add("assistant", "【Completed Task Result】\ntaskId: two")

    rendered = state.render_full_context()
    assert "old" not in rendered
    assert "latest" in rendered
    assert "taskId: one" in rendered
    assert state.extract_tool_results().count("【Completed Task Result】") == 2


def test_deep_requirement_clarification_can_pause_and_persist_answer() -> None:
    async def scenario() -> None:
        memory = InMemoryConversationStore()
        agent = DeepResearchAgent(_settings(), memory)
        agent._llm = FakeLLM(streams=[_stream("【需要补充信息】请说明研究对象。")])  # type: ignore[assignment]

        events = [event async for event in agent.run("deep-pause", "帮我研究一下")]

        assert [event.type for event in events] == ["thinking", "thinking", "thinking", "text", "complete"]
        assert events[3].content == "⏸【暂停深入研究】请说明研究对象。"
        assert await memory.get("deep-pause") == [
            {"role": "user", "content": "帮我研究一下"},
            {"role": "assistant", "content": "⏸【暂停深入研究】请说明研究对象。"},
        ]

    asyncio.run(scenario())


def test_deep_task_executor_uses_search_and_collects_references() -> None:
    async def scenario() -> None:
        agent = DeepResearchAgent(_settings(), InMemoryConversationStore())
        search = FakeSearch()
        agent._search = search  # type: ignore[assignment]
        agent._llm = FakeLLM(  # type: ignore[assignment]
            completions=[
                _completion(
                    "",
                    tool_calls=[
                        {
                            "id": "search-1",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": json.dumps({"query": "latest topic"}),
                            },
                        }
                    ],
                ),
                _completion("忠实整理后的事实"),
            ]
        )

        execution = await agent._execute_task_once(PlanTask("task-1", "检索最新资料", 1), "无\n")

        assert execution.result == TaskResult("task-1", True, output="忠实整理后的事实")
        assert execution.used_tools == {"web_search"}
        assert execution.references[0]["url"] == "https://example.com/source"
        assert search.calls == [{"query": "latest topic"}]

    asyncio.run(scenario())


def test_deep_settings_reject_non_positive_concurrency_and_negative_retries() -> None:
    with pytest.raises(ValueError, match="Deep Research 正整数配置"):
        _settings(deep_tool_concurrency=0)
    with pytest.raises(ValueError, match="DEEP_TOOL_RETRIES"):
        _settings(deep_tool_retries=-1)


def test_deep_tool_retry_configuration_retries_twice_after_initial_failure() -> None:
    class RetryAgent(DeepResearchAgent):
        def __init__(self) -> None:
            super().__init__(_settings(deep_tool_retries=2), InMemoryConversationStore())
            self.calls = 0

        async def _execute_task_once(self, task: PlanTask, dependency_context: str) -> _TaskExecution:
            self.calls += 1
            if self.calls < 3:
                raise RuntimeError(f"failure-{self.calls}")
            return _TaskExecution(TaskResult(task.id or "", True, output="ok"))

    async def scenario() -> None:
        agent = RetryAgent()
        execution = await agent._execute_task_with_retry(PlanTask("retry", "run", 1), "无\n")
        assert agent.calls == 3
        assert execution.attempts == 3
        assert execution.result.success is True

    asyncio.run(scenario())


def test_deep_plan_runs_same_order_concurrently_and_only_passes_previous_order_results() -> None:
    class ControlledAgent(DeepResearchAgent):
        def __init__(self) -> None:
            super().__init__(_settings(deep_tool_concurrency=3, deep_tool_retries=0), InMemoryConversationStore())
            self.active = 0
            self.max_active = 0
            self.contexts: dict[str, str] = {}

        async def _execute_task_once(self, task: PlanTask, dependency_context: str) -> _TaskExecution:
            self.contexts[task.id or ""] = dependency_context
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            try:
                await asyncio.sleep(0.03)
                return _TaskExecution(TaskResult(task.id or "", True, output=f"output-{task.id}"))
            finally:
                self.active -= 1

    async def scenario() -> None:
        agent = ControlledAgent()
        plan = [
            PlanTask("one", "first", 1),
            PlanTask("two", "second", 1),
            PlanTask("three", "third", 2),
        ]
        state = DeepResearchState("conv", "question")
        results: dict[str, TaskResult] = {}
        references: list[dict[str, Any]] = []
        used_tools: set[str] = set()

        events = [event async for event in agent._execute_plan(plan, state, results, references, used_tools)]

        assert agent.max_active >= 2
        assert agent.contexts["one"] == "无\n"
        assert agent.contexts["two"] == "无\n"
        assert "one: output-one" in agent.contexts["three"]
        assert "two: output-two" in agent.contexts["three"]
        assert set(results) == {"one", "two", "three"}
        assert sum(event.type == "thinking" and "正在执行任务" in str(event.content) for event in events) == 3

    asyncio.run(scenario())


def test_deep_plan_cancellation_propagates_to_running_task() -> None:
    class CancellableAgent(DeepResearchAgent):
        def __init__(self) -> None:
            super().__init__(_settings(deep_tool_concurrency=1), InMemoryConversationStore())
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def _execute_task_once(self, task: PlanTask, dependency_context: str) -> _TaskExecution:
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

    async def scenario() -> None:
        agent = CancellableAgent()
        state = DeepResearchState("conv", "question")
        plan = [PlanTask("cancel-me", "wait forever", 1)]
        results: dict[str, TaskResult] = {}
        references: list[dict[str, Any]] = []
        used_tools: set[str] = set()

        async def consume() -> None:
            async for _ in agent._execute_plan(plan, state, results, references, used_tools):
                pass

        task = asyncio.create_task(consume())
        await agent.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(agent.cancelled.wait(), timeout=1)

    asyncio.run(scenario())


def test_deep_context_compression_replaces_state_when_limit_is_exceeded() -> None:
    async def scenario() -> None:
        agent = DeepResearchAgent(_settings(deep_context_char_limit=20), InMemoryConversationStore())
        agent._llm = FakeLLM(completions=[_completion("compressed snapshot")])  # type: ignore[assignment]
        state = DeepResearchState("conv", "question")
        state.add("assistant", "x" * 30)

        events = [event async for event in agent._compress_if_needed(state)]

        assert [event.type for event in events] == ["thinking", "thinking"]
        assert len(state.messages) == 1
        assert state.messages[0]["role"] == "system"
        assert "compressed snapshot" in state.messages[0]["content"]

    asyncio.run(scenario())


def test_deep_full_flow_respects_max_rounds_and_streams_final_report() -> None:
    async def scenario() -> None:
        memory = InMemoryConversationStore()
        agent = DeepResearchAgent(_settings(deep_max_rounds=2), memory)
        agent._llm = FakeLLM(  # type: ignore[assignment]
            streams=[
                _stream("【开始研究】研究该主题。"),
                _stream("1. 维度A\n2. 维度B"),
                _stream("# 最终", "报告"),
            ],
            completions=[
                _completion('[{"id":null,"instruction":"无需调用任何工具","order":0}]'),
            ],
        )

        events = [event async for event in agent.run("deep-full", "研究主题")]

        assert "".join(str(event.content) for event in events if event.type == "text") == "# 最终报告"
        assert sum(event.type == "thinking" and "第 1 轮研究开始" in str(event.content) for event in events) == 1
        assert not any(event.type == "thinking" and "第 2 轮研究开始" in str(event.content) for event in events)
        assert events[-1].type == "complete"
        assert await memory.get("deep-full") == [
            {"role": "user", "content": "研究主题"},
            {"role": "assistant", "content": "# 最终报告"},
        ]

    asyncio.run(scenario())


def test_deep_max_rounds_stops_after_configured_round_count() -> None:
    class NoToolAgent(DeepResearchAgent):
        async def _execute_plan(
            self,
            plan: list[PlanTask],
            state: DeepResearchState,
            results: dict[str, TaskResult],
            references: list[dict[str, Any]],
            used_tools: set[str],
        ):
            for task in plan:
                if task.id:
                    result = TaskResult(task.id, True, output=f"result-{task.id}")
                    results[task.id] = result
                    state.add("assistant", f"【Completed Task Result】\ntaskId: {task.id}\nresult: result-{task.id}")
            if False:
                yield None

    async def scenario() -> None:
        agent = NoToolAgent(_settings(deep_max_rounds=2), InMemoryConversationStore())
        agent._llm = FakeLLM(  # type: ignore[assignment]
            streams=[_stream("【开始研究】继续。"), _stream("1. 维度"), _stream("报告")],
            completions=[
                _completion('[{"id":"r1","instruction":"search one","order":1}]'),
                _completion('{"passed":false,"feedback":"补充更多"}'),
                _completion('[{"id":"r2","instruction":"search two","order":1}]'),
                _completion('{"passed":false,"feedback":"仍不足"}'),
            ],
        )

        events = [event async for event in agent.run("deep-rounds", "研究")]

        assert sum("轮研究开始" in str(event.content) for event in events if event.type == "thinking") == 2
        assert any(event.type == "text" and event.content == "报告" for event in events)
        assert events[-1].type == "complete"

    asyncio.run(scenario())


def test_deep_full_flow_search_emits_reference_after_report() -> None:
    async def scenario() -> None:
        agent = DeepResearchAgent(_settings(deep_max_rounds=1), InMemoryConversationStore())
        search = FakeSearch()
        agent._search = search  # type: ignore[assignment]
        agent._llm = FakeLLM(  # type: ignore[assignment]
            streams=[_stream("【开始研究】继续。"), _stream("1. 最新事实"), _stream("有来源的报告")],
            completions=[
                _completion('[{"id":"search-task","instruction":"搜索最新事实","order":1}]'),
                _completion(
                    "",
                    tool_calls=[
                        {
                            "id": "search-call",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": json.dumps({"query": "latest fact"}),
                            },
                        }
                    ],
                ),
                _completion("事实整理"),
                _completion('{"passed":true,"feedback":""}'),
            ],
        )

        events = [event async for event in agent.run("deep-reference", "研究最新事实")]
        text_index = max(index for index, event in enumerate(events) if event.type == "text")
        reference_index = next(index for index, event in enumerate(events) if event.type == "reference")
        assert reference_index > text_index
        reference = events[reference_index]
        assert reference.count == 1
        assert reference.content[0]["url"] == "https://example.com/source"
        # Nested task-agent web-search calls stay internal and are not exposed
        # on the outer SSE stream.
        assert not any(event.type in {"tool_start", "tool_end"} for event in events)
        assert events[-1].type == "complete"

    asyncio.run(scenario())


def test_deep_sql_persistence_uses_plan_execute_agent_type_and_references() -> None:
    async def scenario() -> None:
        database = Database("sqlite:///:memory:")
        Base.metadata.create_all(database.engine)
        memory = SqlConversationStore(database.session_factory)
        agent = DeepResearchAgent(_settings(), memory)
        agent._llm = FakeLLM(  # type: ignore[assignment]
            streams=[_stream("【开始研究】继续。"), _stream("1. 维度"), _stream("数据库报告")],
            completions=[_completion('[{"id":null,"instruction":"无需工具","order":0}]')],
        )

        events = [event async for event in agent.run("deep-db", "数据库研究")]
        assert events[-1].type == "complete"

        with database.session_factory() as session:
            record = session.query(AiSession).filter_by(session_id="deep-db").one()
            assert record.agent_type == "plan-execute"
            assert record.answer == "数据库报告"
            assert record.thinking is not None
            assert record.first_response_time is not None
            assert record.total_response_time is not None

        database.dispose()

    asyncio.run(scenario())


def test_main_deep_stream_uses_canonical_sse() -> None:
    from app.main import create_app

    settings = _settings(persistence_mode="memory")
    app = create_app(settings)
    agent = app.state.deep_research_agent
    agent._llm = FakeLLM(  # type: ignore[assignment]
        streams=[_stream("【开始研究】继续。"), _stream("1. 维度"), _stream("SSE报告")],
        completions=[_completion('[{"id":null,"instruction":"无需工具","order":0}]')],
    )

    with TestClient(app) as client:
        response = client.get(
            "/agent/deep/stream",
            params={"query": "研究", "conversationId": "deep-sse"},
        )
        payloads = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]

    assert response.status_code == 200
    assert payloads[0]["type"] == "thinking"
    assert any(payload["type"] == "text" and payload["content"] == "SSE报告" for payload in payloads)
    assert payloads[-1] == {"type": "complete"}
