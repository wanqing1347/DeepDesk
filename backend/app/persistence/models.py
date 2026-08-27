from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base

_SQLITE_PK = BigInteger().with_variant(Integer, "sqlite")
_LONGTEXT = Text().with_variant(LONGTEXT(), "mysql")


class AiSession(Base):
    __tablename__ = "ai_session"
    __table_args__ = (
        Index("idx_session_id", "session_id"),
        Index("idx_create_time", "create_time"),
    )

    id: Mapped[int] = mapped_column(_SQLITE_PK, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False)
    question: Mapped[str | None] = mapped_column(_LONGTEXT)
    answer: Mapped[str | None] = mapped_column(_LONGTEXT)
    tools: Mapped[str | None] = mapped_column(String(1024))
    first_response_time: Mapped[int | None] = mapped_column(BigInteger)
    total_response_time: Mapped[int | None] = mapped_column(BigInteger)
    create_time: Mapped[datetime | None] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    update_time: Mapped[datetime | None] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
    )
    reference: Mapped[str | None] = mapped_column(_LONGTEXT)
    agent_type: Mapped[str | None] = mapped_column(String(255))
    thinking: Mapped[str | None] = mapped_column(_LONGTEXT)
    fileid: Mapped[str | None] = mapped_column(String(255))
    recommend: Mapped[str | None] = mapped_column(String(1000))


class AiFileInfo(Base):
    __tablename__ = "ai_file_info"
    __table_args__ = (
        Index("uk_file_id", "file_id", unique=True),
        Index("idx_conversation_id", "conversation_id"),
    )

    id: Mapped[int] = mapped_column(_SQLITE_PK, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(50))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    minio_path: Mapped[str | None] = mapped_column(String(1000))
    extracted_text: Mapped[str | None] = mapped_column(_LONGTEXT)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    conversation_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str | None] = mapped_column(String(50), server_default=text("'PENDING'"))
    update_time: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    embed: Mapped[int | None] = mapped_column(Integer)


class AiPptInst(Base):
    __tablename__ = "ai_ppt_inst"
    __table_args__ = (
        Index("idx_ppt_conversation_id", "conversation_id"),
        Index("idx_status", "status"),
        Index("idx_ppt_template_code", "template_code"),
    )

    id: Mapped[int] = mapped_column(_SQLITE_PK, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str | None] = mapped_column(String(64))
    template_code: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str | None] = mapped_column(String(32), server_default=text("'INIT'"))
    query: Mapped[str | None] = mapped_column(Text)
    requirement: Mapped[str | None] = mapped_column(_LONGTEXT)
    search_info: Mapped[str | None] = mapped_column(_LONGTEXT)
    outline: Mapped[str | None] = mapped_column(_LONGTEXT)
    ppt_schema: Mapped[str | None] = mapped_column(_LONGTEXT)
    file_url: Mapped[str | None] = mapped_column(String(1000))
    error_msg: Mapped[str | None] = mapped_column(Text)
    create_time: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    update_time: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class AiPptTemplate(Base):
    __tablename__ = "ai_ppt_template"
    __table_args__ = (
        Index("template_code", "template_code", unique=True),
        Index("idx_ppt_template_definition_code", "template_code"),
    )

    id: Mapped[int] = mapped_column(_SQLITE_PK, primary_key=True, autoincrement=True)
    template_code: Mapped[str] = mapped_column(String(50), nullable=False)
    template_name: Mapped[str] = mapped_column(String(100), nullable=False)
    template_desc: Mapped[str | None] = mapped_column(Text)
    template_schema: Mapped[str] = mapped_column(_LONGTEXT, nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    style_tags: Mapped[str | None] = mapped_column(String(200))
    slide_count: Mapped[int | None] = mapped_column(Integer)
    create_time: Mapped[datetime | None] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
