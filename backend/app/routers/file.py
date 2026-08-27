from collections.abc import Callable

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.exc import SQLAlchemyError

from ..api_schemas import BaseResult, FileContentVO, FileInfoVO, FileListVO
from ..files.service import FileService


def build_file_router(service_dependency: Callable[[], FileService]) -> APIRouter:
    router = APIRouter(prefix="/file", tags=["file"])

    @router.post("/upload", response_model=BaseResult[FileInfoVO])
    def upload_file(
        file: UploadFile = File(...),
        service: FileService = Depends(service_dependency),
    ) -> BaseResult[FileInfoVO]:
        try:
            # Read one byte beyond the configured limit so oversized requests can
            # be rejected without buffering an unbounded file in application code.
            content = file.file.read(service.max_file_size_bytes + 1)
            info = service.upload(
                file_name=file.filename or "unknown",
                content=content,
                content_type=file.content_type,
            )
            return BaseResult[FileInfoVO].success(info)
        except SQLAlchemyError:
            return BaseResult[FileInfoVO].error("数据库暂时不可用，请稍后重试")
        except Exception as exc:
            return BaseResult[FileInfoVO].error(f"文件上传失败: {exc}")

    @router.get("/info/{file_id}", response_model=BaseResult[FileInfoVO])
    def get_file_info(
        file_id: str,
        service: FileService = Depends(service_dependency),
    ) -> BaseResult[FileInfoVO]:
        try:
            return BaseResult[FileInfoVO].success(service.get_info(file_id))
        except SQLAlchemyError:
            return BaseResult[FileInfoVO].error("数据库暂时不可用，请稍后重试")
        except Exception as exc:
            return BaseResult[FileInfoVO].error(f"获取文件信息失败: {exc}")

    @router.get("/content/{file_id}", response_model=BaseResult[FileContentVO])
    def get_file_content(
        file_id: str,
        service: FileService = Depends(service_dependency),
    ) -> BaseResult[FileContentVO]:
        try:
            return BaseResult[FileContentVO].success(service.get_content(file_id))
        except SQLAlchemyError:
            return BaseResult[FileContentVO].error("数据库暂时不可用，请稍后重试")
        except Exception as exc:
            return BaseResult[FileContentVO].error(f"获取文件内容失败: {exc}")

    @router.delete("/{file_id}", response_model=BaseResult[str])
    def delete_file(
        file_id: str,
        service: FileService = Depends(service_dependency),
    ) -> BaseResult[str]:
        try:
            service.delete(file_id)
            return BaseResult[str].success(message="文件删除成功")
        except SQLAlchemyError:
            return BaseResult[str].error("数据库暂时不可用，请稍后重试")
        except Exception as exc:
            return BaseResult[str].error(f"删除文件失败: {exc}")

    @router.get("/list", response_model=BaseResult[FileListVO])
    def list_files(service: FileService = Depends(service_dependency)) -> BaseResult[FileListVO]:
        try:
            return BaseResult[FileListVO].success(service.list_files())
        except SQLAlchemyError:
            return BaseResult[FileListVO].error("数据库暂时不可用，请稍后重试")
        except Exception as exc:
            return BaseResult[FileListVO].error(f"获取文件列表失败: {exc}")

    @router.get("/exists/{file_id}", response_model=BaseResult[bool])
    def file_exists(
        file_id: str,
        service: FileService = Depends(service_dependency),
    ) -> BaseResult[bool]:
        try:
            return BaseResult[bool].success(service.exists(file_id))
        except SQLAlchemyError:
            return BaseResult[bool].error("数据库暂时不可用，请稍后重试")
        except Exception as exc:
            return BaseResult[bool].error(f"检查文件存在失败: {exc}")

    return router
