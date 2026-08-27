from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, aliased

from ..api_schemas import MessageVO, PageResult, SessionDetailVO, SessionListVO
from .models import AiFileInfo, AiPptInst, AiSession


class SessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save_question(
        self,
        conversation_id: str,
        question: str,
        *,
        agent_type: str,
        fileid: str | None = None,
        tools: str | None = None,
        first_response_time: int | None = None,
    ) -> AiSession:
        now = datetime.now()
        record = AiSession(
            session_id=conversation_id,
            question=question,
            agent_type=agent_type,
            fileid=fileid,
            tools=tools,
            first_response_time=first_response_time,
            create_time=now,
            update_time=now,
        )
        self._session.add(record)
        self._session.flush()
        return record

    def update_answer(
        self,
        record_id: int,
        *,
        answer: str,
        thinking: str | None = None,
        tools: str | None = None,
        reference: str | None = None,
        recommend: str | None = None,
        first_response_time: int | None = None,
        total_response_time: int | None = None,
    ) -> bool:
        record = self._session.get(AiSession, record_id)
        if record is None:
            return False
        record.answer = answer
        record.update_time = datetime.now()
        if thinking is not None:
            record.thinking = thinking
        if tools is not None:
            record.tools = tools
        if reference is not None:
            record.reference = reference
        if recommend is not None:
            record.recommend = recommend
        if first_response_time is not None:
            record.first_response_time = first_response_time
        if total_response_time is not None:
            record.total_response_time = total_response_time
        self._session.flush()
        return True

    def update_recommendation(
        self,
        record_id: int,
        *,
        recommend: str,
        total_response_time: int | None = None,
    ) -> bool:
        record = self._session.get(AiSession, record_id)
        if record is None:
            return False
        record.recommend = recommend
        record.update_time = datetime.now()
        if total_response_time is not None:
            record.total_response_time = total_response_time
        self._session.flush()
        return True

    def find_recent(self, conversation_id: str, max_records: int = 30) -> list[AiSession]:
        statement = (
            select(AiSession)
            .where(AiSession.session_id == conversation_id)
            .order_by(AiSession.create_time.desc(), AiSession.id.desc())
            .limit(max_records)
        )
        return list(self._session.scalars(statement))

    def get_detail(self, conversation_id: str) -> SessionDetailVO | None:
        statement = (
            select(AiSession)
            .where(AiSession.session_id == conversation_id)
            .order_by(AiSession.create_time.asc(), AiSession.id.asc())
        )
        records = list(self._session.scalars(statement))
        if not records:
            return None
        first = records[0]
        return SessionDetailVO(
            conversationId=conversation_id,
            agentType=first.agent_type,
            fileid=first.fileid,
            messages=[
                MessageVO(
                    id=record.id,
                    question=record.question,
                    answer=record.answer,
                    thinking=record.thinking,
                    tools=record.tools,
                    reference=record.reference,
                    createTime=record.create_time,
                    fileid=record.fileid,
                    recommend=record.recommend,
                )
                for record in records
            ],
        )

    def list_sessions(self, page_num: int, page_size: int) -> PageResult[SessionListVO]:
        first_record = aliased(AiSession)
        candidate = aliased(AiSession)
        first_id = (
            select(candidate.id)
            .where(candidate.session_id == first_record.session_id)
            .order_by(candidate.create_time.asc(), candidate.id.asc())
            .limit(1)
            .correlate(first_record)
            .scalar_subquery()
        )
        statement = (
            select(first_record)
            .where(first_record.id == first_id)
            .order_by(first_record.update_time.desc(), first_record.id.desc())
            .offset((page_num - 1) * page_size)
            .limit(page_size)
        )
        records = list(self._session.scalars(statement))
        total = int(
            self._session.scalar(select(func.count(func.distinct(AiSession.session_id)))) or 0
        )
        return PageResult[SessionListVO](
            pageNum=page_num,
            pageSize=page_size,
            total=total,
            records=[
                SessionListVO(
                    conversationId=record.session_id,
                    agentType=record.agent_type,
                    question=record.question,
                    answer=record.answer,
                    messageCount=None,
                    createTime=record.create_time,
                    updateTime=record.update_time,
                    fileid=record.fileid,
                )
                for record in records
            ],
        )

    def delete_conversation(self, conversation_id: str) -> bool:
        exists = self._session.scalar(
            select(AiSession.id).where(AiSession.session_id == conversation_id).limit(1)
        )
        if exists is None:
            return False
        self._session.execute(delete(AiFileInfo).where(AiFileInfo.conversation_id == conversation_id))
        self._session.execute(delete(AiPptInst).where(AiPptInst.conversation_id == conversation_id))
        self._session.execute(delete(AiSession).where(AiSession.session_id == conversation_id))
        self._session.flush()
        return True
