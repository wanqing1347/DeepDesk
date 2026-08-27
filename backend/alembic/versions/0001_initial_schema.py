"""Initial application schema for sessions, files, and PPT state.

Existing databases with this schema can be stamped to this revision.
Fresh databases may use `alembic upgrade head` to create the schema.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LONGTEXT = mysql.LONGTEXT().with_variant(sa.Text(), "sqlite")
BIGINT_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "ai_session",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(255), nullable=False),
        sa.Column("question", LONGTEXT),
        sa.Column("answer", LONGTEXT),
        sa.Column("tools", sa.String(1024)),
        sa.Column("first_response_time", sa.BigInteger()),
        sa.Column("total_response_time", sa.BigInteger()),
        sa.Column("create_time", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("update_time", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("reference", LONGTEXT),
        sa.Column("agent_type", sa.String(255)),
        sa.Column("thinking", LONGTEXT),
        sa.Column("fileid", sa.String(255)),
        sa.Column("recommend", sa.String(1000)),
    )
    op.create_index("idx_session_id", "ai_session", ["session_id"])
    op.create_index("idx_create_time", "ai_session", ["create_time"])

    op.create_table(
        "ai_file_info",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("file_id", sa.String(255), nullable=False),
        sa.Column("file_name", sa.String(500), nullable=False),
        sa.Column("file_type", sa.String(50)),
        sa.Column("file_size", sa.BigInteger()),
        sa.Column("minio_path", sa.String(1000)),
        sa.Column("extracted_text", LONGTEXT),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("conversation_id", sa.String(255)),
        sa.Column("status", sa.String(50), server_default=sa.text("'PENDING'")),
        sa.Column("update_time", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("embed", sa.Integer()),
    )
    op.create_index("uk_file_id", "ai_file_info", ["file_id"], unique=True)
    op.create_index("idx_conversation_id", "ai_file_info", ["conversation_id"])

    op.create_table(
        "ai_ppt_inst",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.String(64)),
        sa.Column("template_code", sa.String(50)),
        sa.Column("status", sa.String(32), server_default=sa.text("'INIT'")),
        sa.Column("query", sa.Text()),
        sa.Column("requirement", LONGTEXT),
        sa.Column("search_info", LONGTEXT),
        sa.Column("outline", LONGTEXT),
        sa.Column("ppt_schema", LONGTEXT),
        sa.Column("file_url", sa.String(1000)),
        sa.Column("error_msg", sa.Text()),
        sa.Column("create_time", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("update_time", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("idx_ppt_conversation_id", "ai_ppt_inst", ["conversation_id"])
    op.create_index("idx_status", "ai_ppt_inst", ["status"])
    op.create_index("idx_ppt_template_code", "ai_ppt_inst", ["template_code"])

    op.create_table(
        "ai_ppt_template",
        sa.Column("id", BIGINT_PK, primary_key=True, autoincrement=True),
        sa.Column("template_code", sa.String(50), nullable=False),
        sa.Column("template_name", sa.String(100), nullable=False),
        sa.Column("template_desc", sa.Text()),
        sa.Column("template_schema", LONGTEXT, nullable=False),
        sa.Column("file_path", sa.String(500), nullable=False),
        sa.Column("style_tags", sa.String(200)),
        sa.Column("slide_count", sa.Integer()),
        sa.Column("create_time", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("template_code", "ai_ppt_template", ["template_code"], unique=True)
    op.create_index("idx_ppt_template_definition_code", "ai_ppt_template", ["template_code"])


def downgrade() -> None:
    op.drop_index("idx_ppt_template_definition_code", table_name="ai_ppt_template")
    op.drop_index("template_code", table_name="ai_ppt_template")
    op.drop_table("ai_ppt_template")

    op.drop_index("idx_ppt_template_code", table_name="ai_ppt_inst")
    op.drop_index("idx_status", table_name="ai_ppt_inst")
    op.drop_index("idx_ppt_conversation_id", table_name="ai_ppt_inst")
    op.drop_table("ai_ppt_inst")

    op.drop_index("idx_conversation_id", table_name="ai_file_info")
    op.drop_index("uk_file_id", table_name="ai_file_info")
    op.drop_table("ai_file_info")

    op.drop_index("idx_create_time", table_name="ai_session")
    op.drop_index("idx_session_id", table_name="ai_session")
    op.drop_table("ai_session")
