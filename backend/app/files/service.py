import mimetypes
import uuid
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import ClassVar, Protocol

from sqlalchemy.orm import Session

from ..api_schemas import FileContentVO, FileInfoVO, FileListVO
from ..config import Settings
from ..persistence.file_repository import FileRepository
from ..providers.multimodal import ImageDescriber
from .parser import FileParser
from .storage import ObjectStore


class VectorIndexer(Protocol):
    def index(self, *, file_id: str, text: str) -> bool: ...

    def delete(self, *, file_id: str) -> None: ...


class FileService:
    TEXT_TYPES: ClassVar[frozenset[str]] = frozenset({"pdf", "doc", "docx", "txt"})
    IMAGE_TYPES: ClassVar[frozenset[str]] = frozenset({"jpg", "jpeg", "png", "gif", "bmp"})

    def __init__(
        self,
        settings: Settings,
        session_factory: Callable[[], Session],
        *,
        object_store: ObjectStore | None,
        parser: FileParser,
        image_describer: ImageDescriber | None,
        vector_indexer: VectorIndexer | None = None,
    ) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._object_store = object_store
        self._parser = parser
        self._image_describer = image_describer
        self._vector_indexer = vector_indexer

    @property
    def max_file_size_bytes(self) -> int:
        return self._settings.max_file_size_bytes

    def upload(
        self,
        *,
        file_name: str,
        content: bytes,
        content_type: str | None,
        conversation_id: str | None = None,
    ) -> FileInfoVO:
        if not content:
            raise ValueError("文件不能为空")
        if len(content) > self._settings.max_file_size_bytes:
            raise ValueError("文件大小不能超过50MB")

        file_type = FileParser.file_type(file_name)
        file_id = str(uuid.uuid4())
        with self._session_factory() as session:
            repository = FileRepository(session)
            repository.create_processing(
                file_id=file_id,
                file_name=file_name,
                file_type=file_type,
                file_size=len(content),
                conversation_id=conversation_id,
            )
            session.commit()

        try:
            if self._object_store is None:
                raise RuntimeError("MinIO 未配置，无法上传文件")

            object_name = self.generate_object_name(file_id, file_type)
            resolved_content_type = content_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream"
            minio_path = self._object_store.upload(
                object_name=object_name,
                content=content,
                content_type=resolved_content_type,
            )

            extracted_text: str | None = None
            embed = 0
            if file_type in self.TEXT_TYPES:
                result = self._parser.parse(file_name=file_name, content=content)
                extracted_text = result.truncated_text
                if (
                    len(result.full_text) >= self._settings.large_file_threshold_chars
                    and self._vector_indexer is not None
                ):
                    try:
                        embed = 1 if self._vector_indexer.index(file_id=file_id, text=result.full_text) else 0
                    except Exception:
                        # Vectorization is best effort: upload remains
                        # successful and FileContent falls back to direct text.
                        embed = 0
            elif file_type in self.IMAGE_TYPES:
                if self._image_describer is None:
                    raise RuntimeError("图片识别服务未配置")
                extracted_text = self._image_describer.describe(
                    content=content,
                    content_type=resolved_content_type,
                )

            with self._session_factory() as session:
                repository = FileRepository(session)
                record = repository.update_record(
                    file_id,
                    minio_path=minio_path,
                    extracted_text=extracted_text,
                    status="SUCCESS",
                    embed=embed,
                )
                if record is None:
                    raise RuntimeError(f"文件记录不存在: {file_id}")
                session.commit()
                return repository.to_vo(record)
        except Exception:
            self._mark_failed(file_id)
            raise

    def get_info(self, file_id: str) -> FileInfoVO:
        with self._session_factory() as session:
            repository = FileRepository(session)
            record = repository.get_record(file_id)
            if record is None:
                raise ValueError(f"文件不存在: {file_id}")
            return repository.to_vo(record)

    def get_content(self, file_id: str) -> FileContentVO:
        info = self.get_info(file_id)
        if info.status != "SUCCESS":
            raise RuntimeError(f"文件尚未处理完成，当前状态: {info.status}")
        content = info.extracted_text or "该文件没有可识别的内容"
        return FileContentVO(content=content, length=len(content))

    def list_files(self) -> FileListVO:
        with self._session_factory() as session:
            repository = FileRepository(session)
            records = repository.list_all()
            files = {record.file_id: repository.to_vo(record) for record in records}
            return FileListVO(count=len(files), files=files)

    def exists(self, file_id: str) -> bool:
        with self._session_factory() as session:
            return FileRepository(session).exists(file_id)

    def delete(self, file_id: str) -> None:
        with self._session_factory() as session:
            repository = FileRepository(session)
            record = repository.get_record(file_id)
            if record is None:
                raise ValueError(f"文件不存在: {file_id}")
            minio_path = record.minio_path

        if self._vector_indexer is not None and record.embed == 1:
            # Delete vectors before touching MinIO. If PgVector is unavailable,
            # the operation fails without partially deleting the object file.
            self._vector_indexer.delete(file_id=file_id)
            with self._session_factory() as session:
                repository = FileRepository(session)
                updated = repository.update_record(file_id, embed=0)
                if updated is None:
                    raise ValueError(f"文件不存在: {file_id}")
                session.commit()

        if minio_path:
            if self._object_store is None:
                raise RuntimeError("MinIO 未配置，无法删除对象文件")
            self._object_store.delete(PurePosixPath(minio_path).name)

        with self._session_factory() as session:
            repository = FileRepository(session)
            if not repository.delete(file_id):
                raise ValueError(f"文件不存在: {file_id}")
            session.commit()

    def _mark_failed(self, file_id: str) -> None:
        with self._session_factory() as session:
            record = FileRepository(session).update_record(file_id, status="FAILED")
            if record is not None:
                session.commit()

    @staticmethod
    def generate_object_name(file_id: str, file_type: str) -> str:
        return f"file-{file_id.replace('-', '')}.{file_type.lower()}"
