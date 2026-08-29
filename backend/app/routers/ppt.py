from collections.abc import Callable

from fastapi import APIRouter, Depends
from sqlalchemy.exc import SQLAlchemyError

from ..api_schemas import BaseResult, PptInfoVO, PptListVO
from ..persistence.models import AiPptInst
from ..persistence.ppt_repository import PptRepository


def _to_ppt_info(inst: AiPptInst) -> PptInfoVO:
    return PptInfoVO(
        id=inst.id,
        conversationId=inst.conversation_id,
        templateCode=inst.template_code,
        status=inst.status or "INIT",
        query=inst.query,
        fileUrl=inst.file_url,
        errorMsg=inst.error_msg,
        createTime=inst.create_time,
        updateTime=inst.update_time,
    )


def build_ppt_router(repository_dependency: Callable[[], PptRepository]) -> APIRouter:
    router = APIRouter(prefix="/ppt", tags=["ppt"])

    @router.get("/list", response_model=BaseResult[PptListVO])
    def list_presentations(
        repository: PptRepository = Depends(repository_dependency),
    ) -> BaseResult[PptListVO]:
        try:
            rows = repository.list_all()
            return BaseResult[PptListVO].success(
                PptListVO(count=len(rows), presentations=[_to_ppt_info(item) for item in rows])
            )
        except SQLAlchemyError:
            return BaseResult[PptListVO].error("数据库暂时不可用，请稍后重试")
        except Exception as exc:
            return BaseResult[PptListVO].error(f"查询PPT列表失败: {exc}")

    @router.get("/{ppt_id}", response_model=BaseResult[PptInfoVO])
    def get_presentation(
        ppt_id: int,
        repository: PptRepository = Depends(repository_dependency),
    ) -> BaseResult[PptInfoVO]:
        try:
            inst = repository.get_by_id(ppt_id)
            if inst is None:
                return BaseResult[PptInfoVO].error("PPT不存在")
            return BaseResult[PptInfoVO].success(_to_ppt_info(inst))
        except SQLAlchemyError:
            return BaseResult[PptInfoVO].error("数据库暂时不可用，请稍后重试")
        except Exception as exc:
            return BaseResult[PptInfoVO].error(f"查询PPT详情失败: {exc}")

    @router.delete("/{ppt_id}", response_model=BaseResult[str])
    def delete_presentation(
        ppt_id: int,
        repository: PptRepository = Depends(repository_dependency),
    ) -> BaseResult[str]:
        try:
            if not repository.delete(ppt_id):
                return BaseResult[str].error("PPT不存在")
            return BaseResult[str].success(message="PPT删除成功")
        except SQLAlchemyError:
            return BaseResult[str].error("数据库暂时不可用，请稍后重试")
        except Exception as exc:
            return BaseResult[str].error(f"删除PPT失败: {exc}")

    return router
