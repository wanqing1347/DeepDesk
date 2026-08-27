import asyncio
import json
from typing import Any

from app.persistence import AiPptTemplate, Base, Database
from app.persistence.ppt_repository import PptRepository
from app.ppt.domain import PptIntent, PptStatus
from app.ppt.intent import PptIntentRecognizer


class FakeLLM:
    def __init__(self, responses: list[dict[str, Any] | Exception]) -> None:
        self.responses = list(responses)
        self.calls: list[list[dict[str, Any]]] = []

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls.append(messages)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _completion(intent: str, reason: str = "reason") -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps({"intent": intent, "reason": reason}, ensure_ascii=False)
                }
            }
        ]
    }


def _database() -> Database:
    database = Database("sqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    return database


def test_ppt_repository_preserves_instance_and_template_contract() -> None:
    database = _database()
    repository = PptRepository(database.session_factory)

    first = repository.create_inst("conv", "first query")
    second = repository.create_inst("conv", "second query")
    assert first.status == PptStatus.INIT.value
    assert repository.get_latest_inst("conv").id == second.id
    assert [item.id for item in repository.list_by_conversation("conv")] == [second.id, first.id]

    repository.update_requirement(second.id, "requirement", PptStatus.SEARCH)
    repository.update_search_info(second.id, "facts", PptStatus.TEMPLATE)
    repository.update_template_code(second.id, "ai", PptStatus.OUTLINE)
    repository.update_outline(second.id, "outline", PptStatus.SCHEMA)
    repository.update_ppt_schema(second.id, '{"slides":[]}', PptStatus.RENDER)
    repository.update_file_url(second.id, "https://files.example/ppt.pptx", PptStatus.SUCCESS)
    updated = repository.get_by_id(second.id)
    assert updated is not None
    assert updated.requirement == "requirement"
    assert updated.search_info == "facts"
    assert updated.template_code == "ai"
    assert updated.outline == "outline"
    assert updated.ppt_schema == '{"slides":[]}'
    assert updated.file_url == "https://files.example/ppt.pptx"
    assert updated.status == PptStatus.SUCCESS.value
    assert [item.id for item in repository.get_completed("conv")] == [second.id]

    repository.update_error(second.id, "render failed", PptStatus.RENDER)
    failed = repository.get_by_id(second.id)
    assert failed is not None
    assert failed.status == PptStatus.RENDER.value
    assert failed.error_msg == "render failed"
    repository.clear_error(second.id, PptStatus.RENDER)
    assert repository.get_by_id(second.id).error_msg == ""

    with database.session_factory() as session:
        session.add(
            AiPptTemplate(
                template_code="ai",
                template_name="AI template",
                template_desc="tech",
                template_schema='{"slides":[]}',
                file_path="templates/ai.pptx",
                style_tags="AI,tech",
                slide_count=5,
            )
        )
        session.commit()

    templates = repository.get_all_templates()
    assert [item.template_code for item in templates] == ["ai"]
    assert repository.get_template_by_code("ai").file_path == "templates/ai.pptx"
    assert repository.get_template_by_code("missing") is None
    database.dispose()


def test_ppt_intent_without_instance_defaults_to_create_without_llm() -> None:
    async def scenario() -> None:
        database = _database()
        llm = FakeLLM([])
        recognizer = PptIntentRecognizer(PptRepository(database.session_factory), llm)  # type: ignore[arg-type]
        result = await recognizer.recognize("new-conversation", "做一个PPT")
        assert result.intent is PptIntent.CREATE_PPT
        assert llm.calls == []
        database.dispose()

    asyncio.run(scenario())


def test_ppt_intent_intermediate_state_resumes_unless_user_explicitly_requests_new() -> None:
    async def scenario() -> None:
        database = _database()
        repository = PptRepository(database.session_factory)
        inst = repository.create_inst("conv", "original")
        repository.update_requirement(inst.id, "confirmed", PptStatus.SEARCH)
        recognizer = PptIntentRecognizer(repository, FakeLLM([]))  # type: ignore[arg-type]

        resume = await recognizer.recognize("conv", "继续生成")
        assert resume.intent is PptIntent.RESUME_PPT
        implicit_resume = await recognizer.recognize("conv", "现在怎么样了")
        assert implicit_resume.intent is PptIntent.RESUME_PPT
        create = await recognizer.recognize("conv", "重新生成一个新的PPT")
        assert create.intent is PptIntent.CREATE_PPT
        database.dispose()

    asyncio.run(scenario())


def test_ppt_intent_error_always_resumes_from_persisted_stage() -> None:
    async def scenario() -> None:
        database = _database()
        repository = PptRepository(database.session_factory)
        inst = repository.create_inst("conv", "original")
        repository.update_error(inst.id, "schema failed", PptStatus.SCHEMA)
        recognizer = PptIntentRecognizer(repository, FakeLLM([]))  # type: ignore[arg-type]

        result = await recognizer.recognize("conv", "新建一个")
        assert result.intent is PptIntent.RESUME_PPT
        assert "SCHEMA" in result.reason
        database.dispose()

    asyncio.run(scenario())


def test_ppt_success_intent_uses_llm_for_modify_or_new_and_falls_back_to_create() -> None:
    async def scenario() -> None:
        database = _database()
        repository = PptRepository(database.session_factory)
        inst = repository.create_inst("conv", "original")
        repository.update_file_url(inst.id, "https://files/ppt.pptx", PptStatus.SUCCESS)
        llm = FakeLLM(
            [
                _completion("MODIFY_PPT", "change title"),
                _completion("CREATE_PPT", "new topic"),
                RuntimeError("provider down"),
            ]
        )
        recognizer = PptIntentRecognizer(repository, llm)  # type: ignore[arg-type]

        modify = await recognizer.recognize("conv", "把标题改一下")
        create = await recognizer.recognize("conv", "另外做一个新主题")
        fallback = await recognizer.recognize("conv", "无法识别")
        assert modify.intent is PptIntent.MODIFY_PPT
        assert create.intent is PptIntent.CREATE_PPT
        assert fallback.intent is PptIntent.CREATE_PPT
        assert len(llm.calls) == 3
        database.dispose()

    asyncio.run(scenario())
