import asyncio
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from ..memory import TurnHandle
from .session_repository import SessionRepository


class SqlConversationStore:
    """ChatMemory + turn persistence backed by the existing ai_session table."""

    def __init__(self, session_factory: Callable[[], Session], *, max_messages: int = 30) -> None:
        self._session_factory = session_factory
        self._max_messages = max_messages

    async def get(self, conversation_id: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._get_sync, conversation_id)

    def _get_sync(self, conversation_id: str) -> list[dict[str, Any]]:
        with self._session_factory() as session:
            records = SessionRepository(session).find_recent(conversation_id, 30)
            messages: list[dict[str, Any]] = []
            for record in reversed(records):
                if record.question is not None:
                    messages.append({"role": "user", "content": record.question})
                if record.answer is not None:
                    messages.append({"role": "assistant", "content": record.answer})
            return messages[-self._max_messages :]

    async def begin_turn(
        self,
        conversation_id: str,
        question: str,
        *,
        agent_type: str,
        fileid: str | None = None,
    ) -> TurnHandle:
        record_id = await asyncio.to_thread(
            self._begin_turn_sync,
            conversation_id,
            question,
            agent_type,
            fileid,
        )
        return TurnHandle(conversation_id=conversation_id, record_id=record_id)

    def _begin_turn_sync(
        self,
        conversation_id: str,
        question: str,
        agent_type: str,
        fileid: str | None,
    ) -> int:
        with self._session_factory() as session:
            repository = SessionRepository(session)
            record = repository.save_question(
                conversation_id,
                question,
                agent_type=agent_type,
                fileid=fileid,
            )
            session.commit()
            return record.id

    async def finish_turn(
        self,
        handle: TurnHandle,
        *,
        question: str,
        answer: str,
        thinking: str | None = None,
        tools: str | None = None,
        reference: str | None = None,
        recommend: str | None = None,
        first_response_time: int | None = None,
        total_response_time: int | None = None,
    ) -> None:
        if handle.record_id is None:
            raise RuntimeError("数据库会话缺少 record_id")
        await asyncio.to_thread(
            self._finish_turn_sync,
            handle.record_id,
            answer,
            thinking,
            tools,
            reference,
            recommend,
            first_response_time,
            total_response_time,
        )

    def _finish_turn_sync(
        self,
        record_id: int,
        answer: str,
        thinking: str | None,
        tools: str | None,
        reference: str | None,
        recommend: str | None,
        first_response_time: int | None,
        total_response_time: int | None,
    ) -> None:
        with self._session_factory() as session:
            repository = SessionRepository(session)
            updated = repository.update_answer(
                record_id,
                answer=answer,
                thinking=thinking,
                tools=tools,
                reference=reference,
                recommend=recommend,
                first_response_time=first_response_time,
                total_response_time=total_response_time,
            )
            if not updated:
                session.rollback()
                raise RuntimeError(f"ai_session 记录不存在: {record_id}")
            session.commit()

    async def update_recommendation(
        self,
        handle: TurnHandle,
        *,
        recommend: str,
        total_response_time: int | None = None,
    ) -> None:
        if handle.record_id is None:
            raise RuntimeError("数据库会话缺少 record_id")
        await asyncio.to_thread(
            self._update_recommendation_sync,
            handle.record_id,
            recommend,
            total_response_time,
        )

    def _update_recommendation_sync(
        self,
        record_id: int,
        recommend: str,
        total_response_time: int | None,
    ) -> None:
        with self._session_factory() as session:
            repository = SessionRepository(session)
            updated = repository.update_recommendation(
                record_id,
                recommend=recommend,
                total_response_time=total_response_time,
            )
            if not updated:
                session.rollback()
                raise RuntimeError(f"ai_session 记录不存在: {record_id}")
            session.commit()
