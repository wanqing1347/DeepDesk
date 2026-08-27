import asyncio
import json

from app.persistence import AiSession, Base, Database
from app.persistence.conversation_store import SqlConversationStore


def test_sql_conversation_store_persists_question_then_full_metadata() -> None:
    async def scenario() -> None:
        database = Database("sqlite:///:memory:")
        Base.metadata.create_all(database.engine)
        store = SqlConversationStore(database.session_factory)

        handle = await store.begin_turn("conv-1", "问题", agent_type="websearch")

        with database.session_factory() as session:
            record = session.get(AiSession, handle.record_id)
            assert record is not None
            assert record.question == "问题"
            assert record.answer is None
            assert record.agent_type == "websearch"

        await store.finish_turn(
            handle,
            question="问题",
            answer="回答",
            thinking="思考过程",
            tools="web_search",
            reference='{"type":"reference","content":"[]","count":0}',
            first_response_time=12,
            total_response_time=345,
        )
        await store.update_recommendation(
            handle,
            recommend=json.dumps(["追问1", "追问2", "追问3"], ensure_ascii=False),
            total_response_time=400,
        )

        assert await store.get("conv-1") == [
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": "回答"},
        ]

        with database.session_factory() as session:
            record = session.get(AiSession, handle.record_id)
            assert record is not None
            assert record.thinking == "思考过程"
            assert record.tools == "web_search"
            assert record.first_response_time == 12
            assert record.total_response_time == 400
            assert record.recommend == '["追问1", "追问2", "追问3"]'

    asyncio.run(scenario())


def test_sql_conversation_store_uses_30_message_window() -> None:
    async def scenario() -> None:
        database = Database("sqlite:///:memory:")
        Base.metadata.create_all(database.engine)
        store = SqlConversationStore(database.session_factory, max_messages=30)

        for index in range(20):
            handle = await store.begin_turn("conv-window", f"q{index}", agent_type="websearch")
            await store.finish_turn(handle, question=f"q{index}", answer=f"a{index}")

        messages = await store.get("conv-window")
        assert len(messages) == 30
        assert messages[0] == {"role": "user", "content": "q5"}
        assert messages[-1] == {"role": "assistant", "content": "a19"}

    asyncio.run(scenario())
