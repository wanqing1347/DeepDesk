import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, ClassVar

from fastapi.testclient import TestClient

from app.agents.skills import SkillsAgent
from app.config import Settings
from app.memory import InMemoryConversationStore
from app.persistence import AiSession, Base, Database
from app.persistence.conversation_store import SqlConversationStore


class FakeFileContentTool:
    name = "loadContent"
    definition: ClassVar[dict[str, Any]] = {
        "type": "function",
        "function": {"name": name, "parameters": {"type": "object"}},
    }

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def call(self, arguments: str) -> str:
        payload = json.loads(arguments)
        self.calls.append(payload)
        return "=== 文件内容 ===\nfile tool content"


class FakeLLM:
    def __init__(
        self,
        streams: list[list[dict[str, Any]] | Exception],
        completions: list[dict[str, Any]] | None = None,
    ) -> None:
        self.streams = list(streams)
        self.completions = list(completions or [])
        self.stream_tools: list[list[dict[str, Any]]] = []
        self.stream_messages: list[list[dict[str, Any]]] = []

    async def stream_chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]):
        self.stream_tools.append(deepcopy(tools))
        self.stream_messages.append(deepcopy(messages))
        stream = self.streams.pop(0)
        if isinstance(stream, Exception):
            raise stream
        for delta in stream:
            await asyncio.sleep(0)
            yield delta

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        return self.completions.pop(0)


def _answer_stream(*parts: str) -> list[dict[str, Any]]:
    return [{"content": part} for part in parts]


def _tool_stream(*calls: tuple[str, str, dict[str, Any]]) -> list[dict[str, Any]]:
    tool_calls = []
    for index, (call_id, name, arguments) in enumerate(calls):
        tool_calls.append(
            {
                "index": index,
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)},
            }
        )
    return [{"tool_calls": tool_calls}]


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "openai_api_key": "test",
        "enable_recommendations": False,
        "search_mode": "demo",
        "skills_workspace_root": str(tmp_path / "workspace"),
        "skills_directories": str(tmp_path / "skills"),
        "skills_retry_interval_seconds": 0,
    }
    values.update(overrides)
    return Settings(**values)


def _prepare_skill_and_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "input.txt").write_text("workspace content", encoding="utf-8")
    skill_dir = tmp_path / "skills" / "code-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: code-review\ndescription: Review code safely\n---\n# Review\nFollow review steps.\n",
        encoding="utf-8",
    )


def test_skills_agent_loads_skill_and_reads_workspace_with_ordered_tool_responses(tmp_path: Path) -> None:
    async def scenario() -> None:
        _prepare_skill_and_workspace(tmp_path)
        memory = InMemoryConversationStore()
        agent = SkillsAgent(_settings(tmp_path), memory)
        fake_llm = FakeLLM(
            [
                _tool_stream(
                    ("call-skill", "read_skill", {"skill": "code-review"}),
                    ("call-read", "read_file", {"filePath": "input.txt"}),
                ),
                _answer_stream("任务", "完成"),
            ]
        )
        agent._llm = fake_llm  # type: ignore[assignment]

        events = [event async for event in agent.run("skills-conv", "帮我处理", None)]

        assert [event.type for event in events] == [
            "thinking",
            "thinking",
            "tool_start",
            "tool_start",
            "tool_end",
            "tool_end",
            "text",
            "text",
            "complete",
        ]
        assert events[1].content == "🧩 正在加载技能: code-review\n"
        assert [event.tool_call_id for event in events if event.type == "tool_end"] == ["call-skill", "call-read"]
        assert "Follow review steps" in str(events[4].result)
        assert "workspace content" in str(events[5].result)
        assert await memory.get("skills-conv") == [
            {"role": "user", "content": "帮我处理"},
            {"role": "assistant", "content": "任务完成"},
        ]

        second_round = fake_llm.stream_messages[1]
        tool_messages = [message for message in second_round if message.get("role") == "tool"]
        assert [message["tool_call_id"] for message in tool_messages] == ["call-skill", "call-read"]
        assert "code-review" in str(fake_llm.stream_messages[0][0]["content"])

    asyncio.run(scenario())


def test_skills_agent_retries_llm_stream_failure_without_losing_terminal_state(tmp_path: Path) -> None:
    async def scenario() -> None:
        agent = SkillsAgent(_settings(tmp_path, skills_max_retries=1), InMemoryConversationStore())
        fake_llm = FakeLLM([RuntimeError("boom"), _answer_stream("retry ok")])
        agent._llm = fake_llm  # type: ignore[assignment]

        events = [event async for event in agent.run("retry-conv", "question")]

        assert [event.type for event in events] == ["thinking", "error", "text", "complete"]
        assert events[1].code == "LLM_CALL_FAILED"
        assert "正在重试" in str(events[1].message)
        assert events[-1].type == "complete"
        assert len(fake_llm.stream_tools) == 2

    asyncio.run(scenario())


def test_skills_agent_round_limit_force_final_disables_tools_before_executing_last_calls(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = tmp_path / "workspace"
        root.mkdir()
        (root / "input.txt").write_text("should not be loaded", encoding="utf-8")
        agent = SkillsAgent(_settings(tmp_path, skills_max_agent_rounds=1), InMemoryConversationStore())
        fake_llm = FakeLLM(
            [
                _tool_stream(("call-read", "read_file", {"filePath": "input.txt"})),
                _answer_stream("forced final"),
            ]
        )
        agent._llm = fake_llm  # type: ignore[assignment]

        events = [event async for event in agent.run("limit-conv", "question")]

        assert not any(event.type in {"tool_start", "tool_end"} for event in events)
        assert any(event.type == "thinking" and "最大推理轮次" in str(event.content) for event in events)
        assert fake_llm.stream_tools[0]
        assert fake_llm.stream_tools[1] == []
        assert "".join(str(event.content) for event in events if event.type == "text") == "forced final"
        assert events[-1].type == "complete"

    asyncio.run(scenario())


def test_skills_agent_persists_agent_type_fileid_tools_reference_and_answer(tmp_path: Path) -> None:
    async def scenario() -> None:
        database = Database("sqlite:///:memory:")
        Base.metadata.create_all(database.engine)
        memory = SqlConversationStore(database.session_factory)
        agent = SkillsAgent(_settings(tmp_path), memory)
        agent._llm = FakeLLM(  # type: ignore[assignment]
            [
                _tool_stream(("call-search", "web_search", {"query": "latest topic"})),
                _answer_stream("搜索回答"),
            ]
        )

        events = [event async for event in agent.run("skills-db", "查一下", "file-optional")]
        assert any(event.type == "reference" for event in events)
        assert events[-1].type == "complete"

        with database.session_factory() as session:
            record = session.query(AiSession).filter_by(session_id="skills-db").one()
            assert record.agent_type == "skills"
            assert record.fileid == "file-optional"
            assert record.answer == "搜索回答"
            assert record.tools == "web_search"
            assert record.reference is not None
            assert "example.com/demo-search" in record.reference
            assert record.first_response_time is not None
            assert record.total_response_time is not None
        database.dispose()

    asyncio.run(scenario())


def test_skills_agent_rejects_duplicate_read_skill_in_same_turn(tmp_path: Path) -> None:
    async def scenario() -> None:
        _prepare_skill_and_workspace(tmp_path)
        agent = SkillsAgent(_settings(tmp_path), InMemoryConversationStore())
        agent._llm = FakeLLM(  # type: ignore[assignment]
            [
                _tool_stream(("call-1", "read_skill", {"skill": "code-review"})),
                _tool_stream(("call-2", "read_skill", {"skill": "code-review"})),
                _answer_stream("done"),
            ]
        )

        events = [event async for event in agent.run("dup-skill", "review")]
        ends = [event for event in events if event.type == "tool_end"]
        assert len(ends) == 2
        assert "禁止重复调用" in str(ends[1].result)
        assert events[-1].type == "complete"

    asyncio.run(scenario())


def test_skills_agent_routes_file_content_tool_with_fileid_context(tmp_path: Path) -> None:
    async def scenario() -> None:
        tool = FakeFileContentTool()
        agent = SkillsAgent(_settings(tmp_path), InMemoryConversationStore(), tool)  # type: ignore[arg-type]
        fake_llm = FakeLLM(
            [
                _tool_stream(
                    ("call-file", "loadContent", {"fileId": "file-123", "question": "what is inside"})
                ),
                _answer_stream("file answer"),
            ]
        )
        agent._llm = fake_llm  # type: ignore[assignment]

        events = [event async for event in agent.run("file-skills", "analyze file", "file-123")]

        assert any(event.type == "thinking" and "检索文件内容" in str(event.content) for event in events)
        assert tool.calls == [{"fileId": "file-123", "question": "what is inside"}]
        assert any(
            message.get("role") == "user" and message.get("content") == "<fileid>file-123</fileid>"
            for message in fake_llm.stream_messages[0]
        )
        assert events[-1].type == "complete"

    asyncio.run(scenario())


def test_skills_agent_routes_grep_and_restricted_bash_through_tool_loop(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = tmp_path / "workspace"
        root.mkdir()
        (root / "notes.txt").write_text("alpha\nneedle here\n", encoding="utf-8")
        agent = SkillsAgent(
            _settings(tmp_path, skills_bash_enabled=True, skills_bash_allowed_commands=""),
            InMemoryConversationStore(),
        )
        agent._llm = FakeLLM(  # type: ignore[assignment]
            [
                _tool_stream(
                    ("call-grep", "grep", {"pattern": "needle", "path": "."}),
                    ("call-bash", "bash", {"command": "pwd"}),
                ),
                _answer_stream("tools done"),
            ]
        )

        events = [event async for event in agent.run("local-tools", "inspect")]
        ends = [event for event in events if event.type == "tool_end"]

        assert [event.tool_name for event in ends] == ["grep", "bash"]
        assert "notes.txt:2:needle here" in str(ends[0].result)
        assert str(root.resolve()) in str(ends[1].result)
        assert events[-1].type == "complete"

    asyncio.run(scenario())


def test_skills_agent_recommendation_is_best_effort(tmp_path: Path) -> None:
    async def scenario() -> None:
        agent = SkillsAgent(_settings(tmp_path, enable_recommendations=True), InMemoryConversationStore())
        agent._llm = FakeLLM(  # type: ignore[assignment]
            [_answer_stream("answer")],
            [{"choices": [{"message": {"content": '["q1","q2","q3"]'}}]}],
        )

        events = [event async for event in agent.run("recommend-skills", "question")]

        recommend = next(event for event in events if event.type == "recommend")
        assert recommend.content == ["q1", "q2", "q3"]
        assert events[-1].type == "complete"

    asyncio.run(scenario())


def test_skills_agent_tool_failure_keeps_original_tool_response_order(tmp_path: Path) -> None:
    async def scenario() -> None:
        root = tmp_path / "workspace"
        root.mkdir()
        (root / "notes.txt").write_text("needle", encoding="utf-8")
        agent = SkillsAgent(_settings(tmp_path), InMemoryConversationStore())
        fake_llm = FakeLLM(
            [
                _tool_stream(
                    ("call-missing", "not_a_tool", {}),
                    ("call-grep", "grep", {"pattern": "needle"}),
                ),
                _answer_stream("recovered"),
            ]
        )
        agent._llm = fake_llm  # type: ignore[assignment]

        events = [event async for event in agent.run("tool-failure", "inspect")]

        ends = [event for event in events if event.type == "tool_end"]
        assert [event.tool_call_id for event in ends] == ["call-missing", "call-grep"]
        assert "工具未找到" in str(ends[0].result)
        assert "needle" in str(ends[1].result)
        second_round = fake_llm.stream_messages[1]
        tool_messages = [message for message in second_round if message.get("role") == "tool"]
        assert [message["tool_call_id"] for message in tool_messages] == ["call-missing", "call-grep"]
        assert events[-1].type == "complete"

    asyncio.run(scenario())


def test_skills_agent_retry_exhaustion_emits_error_then_complete(tmp_path: Path) -> None:
    async def scenario() -> None:
        agent = SkillsAgent(_settings(tmp_path, skills_max_retries=1), InMemoryConversationStore())
        agent._llm = FakeLLM([RuntimeError("first"), RuntimeError("second")])  # type: ignore[assignment]

        events = [event async for event in agent.run("retry-exhausted", "question")]

        assert [event.type for event in events] == ["thinking", "error", "error", "complete"]
        assert "正在重试" in str(events[1].message)
        assert "已重试 1 次" in str(events[2].message)
        assert events[2].code == "LLM_CALL_FAILED"

    asyncio.run(scenario())


def test_main_skills_stream_uses_canonical_sse_in_memory_mode(tmp_path: Path) -> None:
    from app.main import create_app

    settings = _settings(tmp_path, persistence_mode="memory")
    app = create_app(settings)
    skills_agent = app.state.skills_agent
    skills_agent._llm = FakeLLM([_answer_stream("SSE", " answer")])  # type: ignore[assignment]

    with TestClient(app) as client:
        response = client.get(
            "/agent/skills/stream",
            params={"query": "hello", "conversationId": "skills-main"},
        )

    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert response.status_code == 200
    assert [payload["type"] for payload in payloads] == ["thinking", "text", "text", "complete"]
    assert payloads[-1] == {"type": "complete"}
