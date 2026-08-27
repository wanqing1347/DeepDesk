import asyncio
import json
from copy import deepcopy
from typing import Any

from fastapi.testclient import TestClient

from app.agents.ppt import PptBuilderAgent
from app.config import Settings
from app.memory import InMemoryConversationStore
from app.persistence import AiPptInst, AiPptTemplate, AiSession, Base, Database
from app.persistence.ppt_repository import PptRepository
from app.ppt.domain import PptStatus


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

    async def stream_chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]):
        self.stream_messages.append(deepcopy(messages))
        for delta in self.streams.pop(0):
            await asyncio.sleep(0)
            yield delta

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        self.complete_messages.append(deepcopy(messages))
        self.complete_tools.append(deepcopy(tools))
        result = self.completions.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeRenderer:
    def __init__(self, url: str = "https://files.example/generated.pptx", error: Exception | None = None) -> None:
        self.url = url
        self.error = error
        self.calls: list[tuple[int, str, str]] = []

    async def render(self, inst: AiPptInst, template: AiPptTemplate, ppt_schema: str) -> str:
        self.calls.append((inst.id, template.template_code, ppt_schema))
        if self.error is not None:
            raise self.error
        return self.url


class FakeImageGenerator:
    def __init__(self, url: str | None = None) -> None:
        self.url = url
        self.prompts: list[str] = []

    async def generate(self, prompt: str) -> str | None:
        self.prompts.append(prompt)
        return self.url


def _stream(*parts: str) -> list[dict[str, Any]]:
    return [{"content": part} for part in parts]


def _completion(content: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": content}}]}


def _settings(**kwargs: Any) -> Settings:
    return Settings(openai_api_key="test", search_mode="demo", enable_recommendations=False, **kwargs)


def _database() -> Database:
    database = Database("sqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    return database


def _seed_template(database: Database, *, template_code: str = "ai") -> None:
    with database.session_factory() as session:
        session.add(
            AiPptTemplate(
                template_code=template_code,
                template_name="AI template",
                template_desc="tech",
                template_schema=json.dumps(
                    {
                        "slides": [
                            {
                                "pageType": "COVER",
                                "pageDesc": "cover",
                                "templatePageIndex": 1,
                                "data": {"title": {"type": "text", "content": "title", "fontLimit": 10}},
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                file_path="templates/ai.pptx",
                style_tags="AI,tech",
                slide_count=1,
            )
        )
        session.commit()


def _schema(
    *,
    with_image: bool = False,
    image_url: str = "",
    title: str = "最终标题",
    slide_count: int = 1,
) -> str:
    slides: list[dict[str, Any]] = []
    for index in range(slide_count):
        data: dict[str, Any] = {
            "title": {"type": "text", "content": title if index == 0 else f"内容页 {index + 1}", "fontLimit": 10},
        }
        if with_image:
            data["image"] = {"type": "image", "content": "未来城市", "url": image_url}
        slides.append(
            {
                "pageType": "COVER" if index == 0 else "CONTENT",
                "pageDesc": "cover" if index == 0 else "content",
                "templatePageIndex": 1,
                "data": data,
            }
        )
    return json.dumps({"slides": slides}, ensure_ascii=False)


def _build_agent(
    database: Database,
    *,
    memory: InMemoryConversationStore | None = None,
    renderer: FakeRenderer | None = None,
    image_generator: FakeImageGenerator | None = None,
) -> tuple[PptBuilderAgent, PptRepository, FakeRenderer, FakeImageGenerator]:
    repository = PptRepository(database.session_factory)
    actual_renderer = renderer or FakeRenderer()
    actual_generator = image_generator or FakeImageGenerator()
    agent = PptBuilderAgent(
        _settings(),
        memory or InMemoryConversationStore(),
        repository,
        actual_renderer,  # type: ignore[arg-type]
        actual_generator,  # type: ignore[arg-type]
        None,
    )
    return agent, repository, actual_renderer, actual_generator


def test_ppt_create_runs_state_order_to_success_and_persists_memory() -> None:
    async def scenario() -> None:
        database = _database()
        _seed_template(database)
        memory = InMemoryConversationStore()
        agent, repository, renderer, _ = _build_agent(database, memory=memory)
        agent._llm = FakeLLM(  # type: ignore[assignment]
            streams=[
                _stream("【开始生成PPT】主题明确，生成科技风PPT。"),
                _stream("1. 封面\n2. 核心内容"),
                _stream("PPT已生成，共1页。", " 文件可下载。"),
            ],
            completions=[
                _completion("已收集到必要背景资料。"),
                _completion('{"templateCode":"ai","reason":"最匹配"}'),
                _completion(_schema()),
            ],
        )

        events = [event async for event in agent.run("ppt-create", "做一个AI主题PPT")]

        thinking = "".join(str(event.content or "") for event in events if event.type == "thinking")
        assert thinking.index("正在分析您的需求") < thinking.index("正在收集相关信息")
        assert thinking.index("正在收集相关信息") < thinking.index("正在设计模板样式")
        assert thinking.index("正在设计模板样式") < thinking.index("正在生成PPT大纲")
        assert thinking.index("正在生成PPT大纲") < thinking.index("正在设计PPT详细内容")
        assert thinking.index("正在设计PPT详细内容") < thinking.index("正在渲染PPT")
        assert events[-1].type == "complete"
        assert "".join(str(event.content or "") for event in events if event.type == "text") == (
            "PPT已生成，共1页。 文件可下载。"
        )

        latest = repository.get_latest_inst("ppt-create")
        assert latest is not None
        assert latest.status == PptStatus.SUCCESS.value
        assert latest.requirement.startswith("【开始生成PPT】")
        assert latest.search_info == "已收集到必要背景资料。"
        assert latest.template_code == "ai"
        assert latest.outline == "1. 封面\n2. 核心内容"
        assert latest.ppt_schema is not None
        assert latest.file_url == "https://files.example/generated.pptx"
        assert renderer.calls[0][0] == latest.id
        assert await memory.get("ppt-create") == [
            {"role": "user", "content": "做一个AI主题PPT"},
            {"role": "assistant", "content": "PPT已生成，共1页。 文件可下载。"},
        ]
        database.dispose()

    asyncio.run(scenario())


def test_ppt_create_repairs_wrong_slide_count_before_render() -> None:
    async def scenario() -> None:
        database = _database()
        _seed_template(database)
        agent, repository, renderer, _ = _build_agent(database)
        fake_llm = FakeLLM(
            streams=[
                _stream("【开始生成PPT】主题明确，生成5页科技风PPT。"),
                _stream("1. 封面\n2. 原理\n3. 示例\n4. 应用\n5. 总结"),
                _stream("PPT已生成，共5页。"),
            ],
            completions=[
                _completion("已收集到必要背景资料。"),
                _completion('{"templateCode":"ai","reason":"最匹配"}'),
                _completion(_schema(slide_count=2)),
                _completion(_schema(slide_count=5)),
            ],
        )
        agent._llm = fake_llm  # type: ignore[assignment]

        events = [event async for event in agent.run("ppt-five-pages", "请创建一个5页PPT，主题是Transformer注意力机制")]

        latest = repository.get_latest_inst("ppt-five-pages")
        assert latest is not None
        assert latest.status == PptStatus.SUCCESS.value
        assert latest.ppt_schema is not None
        assert len(json.loads(latest.ppt_schema)["slides"]) == 5
        assert len(renderer.calls) == 1
        assert len(json.loads(renderer.calls[0][2])["slides"]) == 5
        assert "slides 数组必须恰好包含 5 页" in fake_llm.complete_messages[2][0]["content"]
        assert "要求 5 页，实际 2 页" in fake_llm.complete_messages[3][0]["content"]
        assert events[-1].type == "complete"
        database.dispose()

    asyncio.run(scenario())


def test_ppt_requirement_pause_keeps_requirement_stage_and_error_for_resume() -> None:
    async def scenario() -> None:
        database = _database()
        memory = InMemoryConversationStore()
        agent, repository, renderer, _ = _build_agent(database, memory=memory)
        agent._llm = FakeLLM(  # type: ignore[assignment]
            streams=[
                _stream("【暂停生成PPT】请提供PPT主题和目标受众。"),
                _stream("还需要补充主题和目标受众后才能继续。"),
            ]
        )

        events = [event async for event in agent.run("ppt-pause", "帮我做个PPT")]

        latest = repository.get_latest_inst("ppt-pause")
        assert latest is not None
        assert latest.status == PptStatus.REQUIREMENT.value
        assert latest.error_msg is not None and latest.error_msg.startswith("需要补充信息")
        assert renderer.calls == []
        assert any(event.type == "text" and "需要补充" in str(event.content) for event in events)
        assert events[-1].type == "complete"
        assert len(await memory.get("ppt-pause")) == 2
        database.dispose()

    asyncio.run(scenario())


def test_ppt_modify_reuses_latest_instance_and_skips_requirement_search_template_outline() -> None:
    async def scenario() -> None:
        database = _database()
        _seed_template(database)
        repository = PptRepository(database.session_factory)
        inst = repository.create_inst("ppt-modify", "original")
        repository.update_requirement(inst.id, "original requirement", PptStatus.SEARCH)
        repository.update_template_code(inst.id, "ai", PptStatus.OUTLINE)
        repository.update_outline(inst.id, "old outline", PptStatus.SCHEMA)
        repository.update_ppt_schema(inst.id, _schema(), PptStatus.RENDER)
        repository.update_file_url(inst.id, "https://files/old.pptx", PptStatus.SUCCESS)

        renderer = FakeRenderer("https://files/new.pptx")
        agent = PptBuilderAgent(
            _settings(),
            InMemoryConversationStore(),
            repository,
            renderer,  # type: ignore[arg-type]
            FakeImageGenerator(),  # type: ignore[arg-type]
            None,
        )
        agent._llm = FakeLLM(  # type: ignore[assignment]
            streams=[_stream("已完成标题修改，新文件可下载。")],
            completions=[
                _completion('{"intent":"MODIFY_PPT","reason":"修改现有PPT"}'),
                _completion(_schema(title="新标题")),
            ],
        )

        events = [event async for event in agent.run("ppt-modify", "把标题改成新标题")]

        instances = repository.list_by_conversation("ppt-modify")
        assert len(instances) == 1
        latest = instances[0]
        assert latest.id == inst.id
        assert latest.status == PptStatus.SUCCESS.value
        assert latest.file_url == "https://files/new.pptx"
        assert renderer.calls == [(inst.id, "ai", latest.ppt_schema)]
        thinking = "".join(str(event.content or "") for event in events if event.type == "thinking")
        assert "正在修改PPT" in thinking
        assert "正在重新生成PPT详细内容" in thinking
        assert "正在分析您的需求" not in thinking
        assert "正在收集相关信息" not in thinking
        assert events[-1].type == "complete"
        database.dispose()

    asyncio.run(scenario())


def test_ppt_modify_repairs_ignored_explicit_cover_title_before_render() -> None:
    async def scenario() -> None:
        database = _database()
        _seed_template(database)
        repository = PptRepository(database.session_factory)
        inst = repository.create_inst("ppt-modify-repair", "original")
        repository.update_template_code(inst.id, "ai", PptStatus.OUTLINE)
        repository.update_ppt_schema(inst.id, _schema(title="旧标题"), PptStatus.RENDER)
        repository.update_file_url(inst.id, "https://files/old.pptx", PptStatus.SUCCESS)

        renderer = FakeRenderer("https://files/repaired.pptx")
        agent = PptBuilderAgent(
            _settings(),
            InMemoryConversationStore(),
            repository,
            renderer,  # type: ignore[arg-type]
            FakeImageGenerator(),  # type: ignore[arg-type]
            None,
        )
        fake_llm = FakeLLM(
            streams=[_stream("修改完成，新文件可下载。")],
            completions=[
                _completion('{"intent":"MODIFY_PPT","reason":"修改现有PPT"}'),
                _completion(_schema(title="旧标题")),
                _completion(_schema(title="Transformer Attention 深度解析")),
            ],
        )
        agent._llm = fake_llm  # type: ignore[assignment]

        events = [
            event
            async for event in agent.run(
                "ppt-modify-repair",
                "把封面标题改成 Transformer Attention 深度解析",
            )
        ]

        latest = repository.get_latest_inst("ppt-modify-repair")
        assert latest is not None
        schema = json.loads(latest.ppt_schema or "{}")
        assert schema["slides"][0]["data"]["title"]["content"] == "Transformer Attention 深度解析"
        assert schema["slides"][0]["data"]["title"]["fontLimit"] == len("Transformer Attention 深度解析")
        assert latest.status == PptStatus.SUCCESS.value
        assert len(renderer.calls) == 1
        assert "封面标题未精确修改为「Transformer Attention 深度解析」" in fake_llm.complete_messages[2][0]["content"]
        assert events[-1].type == "complete"
        database.dispose()

    asyncio.run(scenario())


def test_ppt_modify_does_not_render_when_explicit_text_still_violates_constraint() -> None:
    async def scenario() -> None:
        database = _database()
        _seed_template(database)
        repository = PptRepository(database.session_factory)
        inst = repository.create_inst("ppt-modify-reject", "original")
        repository.update_template_code(inst.id, "ai", PptStatus.OUTLINE)
        repository.update_ppt_schema(inst.id, _schema(title="旧标题"), PptStatus.RENDER)
        repository.update_file_url(inst.id, "https://files/old.pptx", PptStatus.SUCCESS)

        renderer = FakeRenderer("https://files/should-not-exist.pptx")
        agent = PptBuilderAgent(
            _settings(),
            InMemoryConversationStore(),
            repository,
            renderer,  # type: ignore[arg-type]
            FakeImageGenerator(),  # type: ignore[arg-type]
            None,
        )
        agent._llm = FakeLLM(
            streams=[_stream("明确修改没有成功应用，请重试。")],
            completions=[
                _completion('{"intent":"MODIFY_PPT","reason":"修改现有PPT"}'),
                _completion(_schema(title="旧标题")),
                _completion(_schema(title="仍然没改")),
            ],
        )  # type: ignore[assignment]

        events = [
            event
            async for event in agent.run(
                "ppt-modify-reject",
                "把封面标题改成 Transformer Attention 深度解析",
            )
        ]

        latest = repository.get_latest_inst("ppt-modify-reject")
        assert latest is not None
        assert latest.status == PptStatus.SCHEMA.value
        assert latest.error_msg is not None
        assert "PPT Schema未满足硬约束" in latest.error_msg
        assert renderer.calls == []
        assert any(event.type == "text" for event in events)
        assert events[-1].type == "complete"
        database.dispose()

    asyncio.run(scenario())


def test_ppt_resume_from_render_clears_error_and_does_not_repeat_prior_stages() -> None:
    async def scenario() -> None:
        database = _database()
        _seed_template(database)
        repository = PptRepository(database.session_factory)
        inst = repository.create_inst("ppt-resume", "original")
        repository.update_template_code(inst.id, "ai", PptStatus.OUTLINE)
        repository.update_ppt_schema(inst.id, _schema(), PptStatus.RENDER)
        repository.update_error(inst.id, "PPT渲染失败: previous", PptStatus.RENDER)

        renderer = FakeRenderer("https://files/resumed.pptx")
        agent = PptBuilderAgent(
            _settings(),
            InMemoryConversationStore(),
            repository,
            renderer,  # type: ignore[arg-type]
            FakeImageGenerator(),  # type: ignore[arg-type]
            None,
        )
        agent._llm = FakeLLM(streams=[_stream("已从断点恢复并生成。")])  # type: ignore[assignment]

        events = [event async for event in agent.run("ppt-resume", "继续")]

        latest = repository.get_latest_inst("ppt-resume")
        assert latest is not None
        assert latest.id == inst.id
        assert latest.status == PptStatus.SUCCESS.value
        assert latest.error_msg == ""
        assert latest.file_url == "https://files/resumed.pptx"
        assert len(renderer.calls) == 1
        thinking = "".join(str(event.content or "") for event in events if event.type == "thinking")
        assert "正在从状态 RENDER 继续执行" in thinking
        assert "正在渲染PPT" in thinking
        assert "正在设计PPT详细内容" not in thinking
        assert events[-1].type == "complete"
        database.dispose()

    asyncio.run(scenario())


def test_ppt_render_failure_persists_render_stage_and_is_resumable() -> None:
    async def scenario() -> None:
        database = _database()
        _seed_template(database)
        repository = PptRepository(database.session_factory)
        inst = repository.create_inst("ppt-render-fail", "original")
        repository.update_template_code(inst.id, "ai", PptStatus.OUTLINE)
        repository.update_ppt_schema(inst.id, _schema(), PptStatus.RENDER)

        failing = FakeRenderer(error=RuntimeError("renderer down"))
        agent = PptBuilderAgent(
            _settings(),
            InMemoryConversationStore(),
            repository,
            failing,  # type: ignore[arg-type]
            FakeImageGenerator(),  # type: ignore[arg-type]
            None,
        )
        agent._llm = FakeLLM(streams=[_stream("渲染失败，请重试。")])  # type: ignore[assignment]
        first_events = [event async for event in agent.run("ppt-render-fail", "继续")]
        failed = repository.get_latest_inst("ppt-render-fail")
        assert failed is not None
        assert failed.status == PptStatus.RENDER.value
        assert "renderer down" in str(failed.error_msg)
        assert first_events[-1].type == "complete"

        succeeding = FakeRenderer("https://files/retry.pptx")
        resume_agent = PptBuilderAgent(
            _settings(),
            InMemoryConversationStore(),
            repository,
            succeeding,  # type: ignore[arg-type]
            FakeImageGenerator(),  # type: ignore[arg-type]
            None,
        )
        resume_agent._llm = FakeLLM(streams=[_stream("重试成功。")])  # type: ignore[assignment]
        second_events = [event async for event in resume_agent.run("ppt-render-fail", "重试")]
        recovered = repository.get_latest_inst("ppt-render-fail")
        assert recovered is not None
        assert recovered.status == PptStatus.SUCCESS.value
        assert recovered.error_msg == ""
        assert recovered.file_url == "https://files/retry.pptx"
        assert second_events[-1].type == "complete"
        database.dispose()

    asyncio.run(scenario())


def test_main_pptx_stream_uses_canonical_sse_and_persists_pptx_session() -> None:
    from app.main import create_app

    settings = _settings(
        persistence_mode="database",
        database_url="sqlite:///:memory:",
        minio_endpoint="",
        vector_database_url="",
    )
    app = create_app(settings)
    database = app.state.database
    agent = app.state.ppt_agent
    assert database is not None
    assert agent is not None
    Base.metadata.create_all(database.engine)
    _seed_template(database)

    renderer = FakeRenderer("https://files.example/sse.pptx")
    agent._renderer = renderer  # type: ignore[assignment]
    agent._image_generator = FakeImageGenerator()  # type: ignore[assignment]
    agent._llm = FakeLLM(  # type: ignore[assignment]
        streams=[
            _stream("【开始生成PPT】信息充足。"),
            _stream("1. 封面"),
            _stream("SSE PPT已生成。"),
        ],
        completions=[
            _completion("背景资料"),
            _completion('{"templateCode":"ai","reason":"match"}'),
            _completion(_schema()),
        ],
    )

    with TestClient(app) as client:
        response = client.get(
            "/agent/pptx/stream",
            params={"query": "生成PPT", "conversationId": "ppt-sse"},
        )
        payloads = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]

        assert response.status_code == 200
        assert payloads[0]["type"] == "thinking"
        assert any(payload["type"] == "text" and payload["content"] == "SSE PPT已生成。" for payload in payloads)
        assert payloads[-1] == {"type": "complete"}

        with database.session_factory() as session:
            record = session.query(AiSession).filter_by(session_id="ppt-sse").one()
            assert record.agent_type == "pptx"
            assert record.answer == "SSE PPT已生成。"
            assert record.thinking is not None
            ppt = session.query(AiPptInst).filter_by(conversation_id="ppt-sse").one()
            assert ppt.status == PptStatus.SUCCESS.value
            assert ppt.file_url == "https://files.example/sse.pptx"


def test_main_pptx_stream_reports_unavailable_in_memory_mode() -> None:
    from app.main import create_app

    app = create_app(_settings(persistence_mode="memory"))
    with TestClient(app) as client:
        response = client.get(
            "/agent/pptx/stream",
            params={"query": "生成PPT", "conversationId": "ppt-disabled"},
        )
        payloads = [
            json.loads(line.removeprefix("data: "))
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]

    assert payloads[0]["type"] == "error"
    assert payloads[0]["code"] == "PPT_SERVICE_UNAVAILABLE"
    assert payloads[-1] == {"type": "complete"}


def test_ppt_image_generation_failure_is_best_effort_and_still_renders() -> None:
    async def scenario() -> None:
        database = _database()
        _seed_template(database)
        repository = PptRepository(database.session_factory)
        inst = repository.create_inst("ppt-image", "original")
        repository.update_template_code(inst.id, "ai", PptStatus.OUTLINE)
        repository.update_outline(inst.id, "outline", PptStatus.SCHEMA)

        renderer = FakeRenderer()
        generator = FakeImageGenerator(url=None)
        agent = PptBuilderAgent(
            _settings(),
            InMemoryConversationStore(),
            repository,
            renderer,  # type: ignore[arg-type]
            generator,  # type: ignore[arg-type]
            None,
        )
        agent._llm = FakeLLM(  # type: ignore[assignment]
            streams=[_stream("图片失败但PPT仍生成成功。")],
            completions=[_completion(_schema(with_image=True))],
        )

        events = [event async for event in agent.run("ppt-image", "继续")]

        latest = repository.get_latest_inst("ppt-image")
        assert latest is not None
        assert latest.status == PptStatus.SUCCESS.value
        schema = json.loads(latest.ppt_schema)
        assert schema["slides"][0]["data"]["image"]["url"] == ""
        assert generator.prompts == ["未来城市"]
        assert len(renderer.calls) == 1
        assert any(event.type == "thinking" and "图片生成失败" in str(event.content) for event in events)
        assert events[-1].type == "complete"
        database.dispose()

    asyncio.run(scenario())
