import asyncio
import json
from copy import deepcopy
from typing import Any, ClassVar

from fastapi.testclient import TestClient

from app.agents.file import FileAgent
from app.config import Settings
from app.memory import InMemoryConversationStore
from app.persistence import AiFileInfo, AiSession, Base, Database
from app.persistence.conversation_store import SqlConversationStore


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
        return self.completions.pop(0)


class FakeFileContentTool:
    name = "loadContent"
    definition: ClassVar[dict[str, Any]] = {"type": "function", "function": {"name": name}}

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def call(self, arguments: str) -> str:
        payload = json.loads(arguments)
        self.calls.append(payload)
        return "=== 文件内容 ===\nretrieved content"


def _answer_stream(*parts: str) -> list[dict[str, Any]]:
    return [{"content": part} for part in parts]


def _tool_stream(*, file_id: str = "file-1", question: str = "问题") -> list[dict[str, Any]]:
    arguments = json.dumps({"fileId": file_id, "question": question}, ensure_ascii=False)
    midpoint = max(1, len(arguments) // 2)
    return [
        {
            "tool_calls": [
                {
                    "index": 0,
                    "id": "call-file-1",
                    "type": "function",
                    "function": {"name": "loadContent", "arguments": arguments[:midpoint]},
                }
            ]
        },
        {
            "tool_calls": [
                {
                    "index": 0,
                    "function": {"arguments": arguments[midpoint:]},
                }
            ]
        },
    ]


def _recommend_response(*questions: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": json.dumps(list(questions), ensure_ascii=False)}}]}


def _settings(**kwargs: Any) -> Settings:
    return Settings(openai_api_key="test", enable_recommendations=False, **kwargs)


def test_file_agent_streams_load_content_timeline_and_final_answer() -> None:
    async def scenario() -> None:
        memory = InMemoryConversationStore()
        tool = FakeFileContentTool()
        agent = FileAgent(_settings(), memory, tool)  # type: ignore[arg-type]
        agent._llm = FakeLLM([_tool_stream(), _answer_stream("文件", "答案")])  # type: ignore[assignment]

        events = [event async for event in agent.run("conversation-file", "问题", "file-1")]

        assert [event.type for event in events] == [
            "thinking",
            "thinking",
            "tool_start",
            "tool_end",
            "text",
            "text",
            "complete",
        ]
        assert events[1].content == "📂 正在检索文件内容，请稍等...\n"
        assert events[2].tool_name == "loadContent"
        assert events[2].tool_call_id == "call-file-1"
        assert tool.calls == [{"fileId": "file-1", "question": "问题"}]
        assert await memory.get("conversation-file") == [
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": "文件答案"},
        ]

        second_round = agent._llm.stream_messages[1]  # type: ignore[attr-defined]
        tool_message = next(message for message in second_round if message.get("role") == "tool")
        assert tool_message["tool_call_id"] == "call-file-1"
        assert "retrieved content" in tool_message["content"]

    asyncio.run(scenario())


def test_file_agent_round_limit_forces_final_without_tools() -> None:
    async def scenario() -> None:
        tool = FakeFileContentTool()
        agent = FileAgent(_settings(max_agent_rounds=1), InMemoryConversationStore(), tool)  # type: ignore[arg-type]
        fake_llm = FakeLLM([_tool_stream(), _answer_stream("强制", "总结")])
        agent._llm = fake_llm  # type: ignore[assignment]

        events = [event async for event in agent.run("conv-limit", "问题", "file-1")]

        assert fake_llm.stream_tools[0]
        assert fake_llm.stream_tools[1] == []
        assert any(event.type == "thinking" and "最大推理轮次" in str(event.content) for event in events)
        assert "".join(str(event.content) for event in events if event.type == "text") == "强制总结"
        assert events[-1].type == "complete"

    asyncio.run(scenario())


def test_file_agent_recommendation_is_best_effort() -> None:
    async def scenario() -> None:
        agent = FileAgent(
            Settings(openai_api_key="test", enable_recommendations=True),
            InMemoryConversationStore(),
            FakeFileContentTool(),  # type: ignore[arg-type]
        )
        agent._llm = FakeLLM(  # type: ignore[assignment]
            [_answer_stream("回答")],
            [_recommend_response("继续问1", "继续问2", "继续问3")],
        )

        events = [event async for event in agent.run("conv-rec", "问题", "file-1")]

        recommend = next(event for event in events if event.type == "recommend")
        assert recommend.content == ["继续问1", "继续问2", "继续问3"]
        assert recommend.count == 3
        assert events[-1].type == "complete"

    asyncio.run(scenario())


def test_file_agent_persists_agent_type_fileid_tools_and_answer() -> None:
    async def scenario() -> None:
        database = Database("sqlite:///:memory:")
        Base.metadata.create_all(database.engine)
        memory = SqlConversationStore(database.session_factory)
        agent = FileAgent(_settings(), memory, FakeFileContentTool())  # type: ignore[arg-type]
        agent._llm = FakeLLM([_tool_stream(file_id="file-db"), _answer_stream("持久化答案")])  # type: ignore[assignment]

        events = [event async for event in agent.run("conv-db", "数据库问题", "file-db")]
        assert events[-1].type == "complete"

        with database.session_factory() as session:
            record = session.query(AiSession).filter_by(session_id="conv-db").one()
            assert record.agent_type == "file"
            assert record.fileid == "file-db"
            assert record.answer == "持久化答案"
            assert record.tools == "loadContent"
            assert record.thinking is not None
            assert record.first_response_time is not None
            assert record.total_response_time is not None

        database.dispose()

    asyncio.run(scenario())


def test_main_file_stream_uses_canonical_sse_and_real_file_content_tool() -> None:
    from app.main import create_app

    settings = Settings(
        persistence_mode="database",
        database_url="sqlite:///:memory:",
        openai_api_key="test",
        enable_recommendations=False,
        vector_database_url="",
        minio_endpoint="",
    )
    app = create_app(settings)
    database = app.state.database
    file_agent = app.state.file_agent
    assert database is not None
    assert file_agent is not None
    Base.metadata.create_all(database.engine)

    with database.session_factory() as session:
        session.add(
            AiFileInfo(
                file_id="file-main",
                file_name="main.txt",
                file_type="txt",
                file_size=16,
                extracted_text="integration text",
                status="SUCCESS",
                embed=0,
            )
        )
        session.commit()

    file_agent._llm = FakeLLM(  # type: ignore[assignment]
        [_tool_stream(file_id="file-main", question="集成问题"), _answer_stream("集成回答")]
    )

    with TestClient(app) as client:
        response = client.get(
            "/agent/file/stream",
            params={"query": "集成问题", "conversationId": "conv-main", "fileId": "file-main"},
        )
        payloads = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]

        assert response.status_code == 200
        assert [payload["type"] for payload in payloads] == [
            "thinking",
            "thinking",
            "tool_start",
            "tool_end",
            "text",
            "complete",
        ]
        assert payloads[2]["toolName"] == "loadContent"
        assert payloads[2]["toolCallId"] == "call-file-1"
        assert "integration text" in payloads[3]["result"]
        assert payloads[-1] == {"type": "complete"}

        with database.session_factory() as session:
            record = session.query(AiSession).filter_by(session_id="conv-main").one()
            assert record.agent_type == "file"
            assert record.fileid == "file-main"
            assert record.answer == "集成回答"
