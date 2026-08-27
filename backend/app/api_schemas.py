from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class BaseResult(ApiModel, Generic[T]):
    code: int = 200
    message: str = ""
    data: T | None = None

    @classmethod
    def success(cls, data: T | None = None, message: str = "") -> "BaseResult[T]":
        return cls(code=200, message=message, data=data)

    @classmethod
    def error(cls, message: str) -> "BaseResult[T]":
        return cls(code=500, message=message, data=None)


class FileInfoVO(ApiModel):
    file_id: str = Field(alias="fileId")
    file_name: str = Field(alias="fileName")
    file_type: str | None = Field(default=None, alias="fileType")
    file_size: int | None = Field(default=None, alias="fileSize")
    minio_path: str | None = Field(default=None, alias="minioPath")
    extracted_text: str | None = Field(default=None, alias="extractedText")
    created_at: datetime | None = Field(default=None, alias="createdAt")
    conversation_id: str | None = Field(default=None, alias="conversationId")
    status: str = "PENDING"
    embed: int | None = 0


class FileContentVO(ApiModel):
    content: str
    length: int


class FileListVO(ApiModel):
    count: int
    files: dict[str, FileInfoVO]


class MessageVO(ApiModel):
    id: int
    question: str | None = None
    answer: str | None = None
    thinking: str | None = None
    tools: str | None = None
    reference: str | None = None
    create_time: datetime | None = Field(default=None, alias="createTime")
    fileid: str | None = None
    recommend: str | None = None


class SessionDetailVO(ApiModel):
    conversation_id: str = Field(alias="conversationId")
    agent_type: str | None = Field(default=None, alias="agentType")
    fileid: str | None = None
    messages: list[MessageVO]


class SessionListVO(ApiModel):
    conversation_id: str = Field(alias="conversationId")
    agent_type: str | None = Field(default=None, alias="agentType")
    question: str | None = None
    answer: str | None = None
    message_count: int | None = Field(default=None, alias="messageCount")
    create_time: datetime | None = Field(default=None, alias="createTime")
    update_time: datetime | None = Field(default=None, alias="updateTime")
    fileid: str | None = None


class PageResult(ApiModel, Generic[T]):
    page_num: int = Field(alias="pageNum")
    page_size: int = Field(alias="pageSize")
    total: int
    records: list[T]
