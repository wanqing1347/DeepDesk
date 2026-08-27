from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..api_schemas import FileInfoVO
from .models import AiFileInfo


class FileRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create_processing(
        self,
        *,
        file_id: str,
        file_name: str,
        file_type: str,
        file_size: int,
        conversation_id: str | None = None,
    ) -> AiFileInfo:
        now = datetime.now()
        record = AiFileInfo(
            file_id=file_id,
            file_name=file_name,
            file_type=file_type,
            file_size=file_size,
            conversation_id=conversation_id,
            status="PROCESSING",
            embed=0,
            created_at=now,
            update_time=now,
        )
        self._session.add(record)
        self._session.flush()
        return record

    def get_record(self, file_id: str) -> AiFileInfo | None:
        return self._session.scalar(select(AiFileInfo).where(AiFileInfo.file_id == file_id).limit(1))

    def update_record(
        self,
        file_id: str,
        *,
        minio_path: str | None = None,
        extracted_text: str | None = None,
        status: str | None = None,
        embed: int | None = None,
    ) -> AiFileInfo | None:
        record = self.get_record(file_id)
        if record is None:
            return None
        if minio_path is not None:
            record.minio_path = minio_path
        if extracted_text is not None:
            record.extracted_text = extracted_text
        if status is not None:
            record.status = status
        if embed is not None:
            record.embed = embed
        record.update_time = datetime.now()
        self._session.flush()
        return record

    def delete(self, file_id: str) -> bool:
        exists = self._session.scalar(select(AiFileInfo.id).where(AiFileInfo.file_id == file_id).limit(1))
        if exists is None:
            return False
        self._session.execute(delete(AiFileInfo).where(AiFileInfo.file_id == file_id))
        self._session.flush()
        return True

    def exists(self, file_id: str) -> bool:
        return self._session.scalar(select(AiFileInfo.id).where(AiFileInfo.file_id == file_id).limit(1)) is not None

    def list_all(self) -> list[AiFileInfo]:
        return list(self._session.scalars(select(AiFileInfo).order_by(AiFileInfo.id.asc())))

    def count(self) -> int:
        return int(self._session.scalar(select(func.count(AiFileInfo.id))) or 0)

    @staticmethod
    def to_vo(record: AiFileInfo) -> FileInfoVO:
        status = record.status if record.status in {"PENDING", "PROCESSING", "SUCCESS", "FAILED"} else "PENDING"
        return FileInfoVO(
            fileId=record.file_id,
            fileName=record.file_name,
            fileType=record.file_type,
            fileSize=record.file_size,
            minioPath=record.minio_path,
            extractedText=record.extracted_text,
            createdAt=record.created_at,
            conversationId=record.conversation_id,
            status=status,
            embed=record.embed,
        )
