from collections.abc import Callable, Iterator

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..api_schemas import BaseResult, PageResult, SessionDetailVO, SessionListVO
from ..persistence.session_repository import SessionRepository


def build_session_router(session_dependency: Callable[[], Iterator[Session]]) -> APIRouter:
    router = APIRouter(prefix="/session", tags=["session"])

    # Register the static /list route before /{conversation_id}; FastAPI/Starlette
    # route matching is order-sensitive for overlapping path shapes.
    @router.get("/list", response_model=BaseResult[PageResult[SessionListVO]])
    def list_sessions(
        page_num: int = Query(default=1, alias="pageNum", ge=1),
        page_size: int = Query(default=10, alias="pageSize", ge=1),
        db: Session = Depends(session_dependency),
    ) -> BaseResult[PageResult[SessionListVO]]:
        try:
            page = SessionRepository(db).list_sessions(page_num, page_size)
            return BaseResult[PageResult[SessionListVO]].success(page)
        except SQLAlchemyError:
            return BaseResult[PageResult[SessionListVO]].error("数据库暂时不可用，请稍后重试")
        except Exception as exc:
            return BaseResult[PageResult[SessionListVO]].error(f"查询会话列表失败: {exc}")

    @router.get("/{conversation_id}", response_model=BaseResult[SessionDetailVO])
    def get_session(
        conversation_id: str,
        db: Session = Depends(session_dependency),
    ) -> BaseResult[SessionDetailVO]:
        try:
            detail = SessionRepository(db).get_detail(conversation_id)
            if detail is None:
                return BaseResult[SessionDetailVO].error("会话不存在")
            return BaseResult[SessionDetailVO].success(detail)
        except SQLAlchemyError:
            return BaseResult[SessionDetailVO].error("数据库暂时不可用，请稍后重试")
        except Exception as exc:
            return BaseResult[SessionDetailVO].error(f"查询会话详情失败: {exc}")

    @router.delete("/{conversation_id}", response_model=BaseResult[str])
    def delete_session(
        conversation_id: str,
        db: Session = Depends(session_dependency),
    ) -> BaseResult[str]:
        try:
            repository = SessionRepository(db)
            deleted = repository.delete_conversation(conversation_id)
            if not deleted:
                db.rollback()
                return BaseResult[str].error("会话不存在")
            db.commit()
            return BaseResult[str].success(message="会话删除成功")
        except SQLAlchemyError:
            db.rollback()
            return BaseResult[str].error("数据库暂时不可用，请稍后重试")
        except Exception as exc:
            db.rollback()
            return BaseResult[str].error(f"删除会话失败: {exc}")

    return router
