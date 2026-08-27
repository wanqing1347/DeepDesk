from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ppt.domain import PptStatus
from .models import AiPptInst, AiPptTemplate


class PptRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def create_inst(self, conversation_id: str, query: str) -> AiPptInst:
        now = datetime.now()
        with self._session_factory() as session:
            inst = AiPptInst(
                conversation_id=conversation_id,
                query=query,
                status=PptStatus.INIT.value,
                create_time=now,
                update_time=now,
            )
            session.add(inst)
            session.commit()
            session.refresh(inst)
            return self._detach(session, inst)

    def get_by_id(self, inst_id: int) -> AiPptInst | None:
        with self._session_factory() as session:
            inst = session.get(AiPptInst, inst_id)
            return self._detach(session, inst) if inst is not None else None

    def get_latest_inst(self, conversation_id: str) -> AiPptInst | None:
        with self._session_factory() as session:
            inst = session.scalar(
                select(AiPptInst)
                .where(AiPptInst.conversation_id == conversation_id)
                .order_by(AiPptInst.create_time.desc(), AiPptInst.id.desc())
                .limit(1)
            )
            return self._detach(session, inst) if inst is not None else None

    def list_by_conversation(self, conversation_id: str) -> list[AiPptInst]:
        with self._session_factory() as session:
            rows = list(
                session.scalars(
                    select(AiPptInst)
                    .where(AiPptInst.conversation_id == conversation_id)
                    .order_by(AiPptInst.create_time.desc(), AiPptInst.id.desc())
                )
            )
            return [self._detach(session, item) for item in rows]

    def get_completed(self, conversation_id: str) -> list[AiPptInst]:
        with self._session_factory() as session:
            rows = list(
                session.scalars(
                    select(AiPptInst)
                    .where(
                        AiPptInst.conversation_id == conversation_id,
                        AiPptInst.status == PptStatus.SUCCESS.value,
                    )
                    .order_by(AiPptInst.create_time.desc(), AiPptInst.id.desc())
                )
            )
            return [self._detach(session, item) for item in rows]

    def update_status(self, inst_id: int, status: PptStatus) -> AiPptInst:
        return self._update(inst_id, status=status)

    def update_requirement(self, inst_id: int, requirement: str, status: PptStatus) -> AiPptInst:
        return self._update(inst_id, status=status, requirement=requirement)

    def update_search_info(self, inst_id: int, search_info: str, status: PptStatus) -> AiPptInst:
        return self._update(inst_id, status=status, search_info=search_info)

    def update_template_code(self, inst_id: int, template_code: str, status: PptStatus) -> AiPptInst:
        return self._update(inst_id, status=status, template_code=template_code)

    def update_outline(self, inst_id: int, outline: str, status: PptStatus) -> AiPptInst:
        return self._update(inst_id, status=status, outline=outline)

    def update_ppt_schema(self, inst_id: int, ppt_schema: str, status: PptStatus) -> AiPptInst:
        return self._update(inst_id, status=status, ppt_schema=ppt_schema)

    def update_file_url(self, inst_id: int, file_url: str, status: PptStatus) -> AiPptInst:
        return self._update(inst_id, status=status, file_url=file_url)

    def update_error(self, inst_id: int, error_msg: str, status: PptStatus) -> AiPptInst:
        return self._update(inst_id, status=status, error_msg=error_msg)

    def clear_error(self, inst_id: int, status: PptStatus) -> AiPptInst:
        return self._update(inst_id, status=status, error_msg="")

    def get_all_templates(self) -> list[AiPptTemplate]:
        with self._session_factory() as session:
            rows = list(session.scalars(select(AiPptTemplate).order_by(AiPptTemplate.id.asc())))
            return [self._detach(session, item) for item in rows]

    def get_template_by_code(self, template_code: str) -> AiPptTemplate | None:
        with self._session_factory() as session:
            item = session.scalar(
                select(AiPptTemplate).where(AiPptTemplate.template_code == template_code).limit(1)
            )
            return self._detach(session, item) if item is not None else None

    def _update(self, inst_id: int, *, status: PptStatus, **fields: str) -> AiPptInst:
        with self._session_factory() as session:
            inst = session.get(AiPptInst, inst_id)
            if inst is None:
                raise ValueError(f"PPT实例不存在: {inst_id}")
            inst.status = status.value
            inst.update_time = datetime.now()
            for name, value in fields.items():
                setattr(inst, name, value)
            session.commit()
            session.refresh(inst)
            return self._detach(session, inst)

    @staticmethod
    def _detach(session: Session, entity):
        session.expunge(entity)
        return entity
