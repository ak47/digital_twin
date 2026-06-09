"""Initial conversation persistence schema.

Revision ID: 001_initial
Revises:
Create Date: 2026-06-09

"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("visitor_name", sa.Text(), nullable=False, server_default="Rando"),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("needs_attention", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_escalation_email_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_conversations_last_activity",
        "conversations",
        ["last_activity_at"],
        unique=False,
    )
    op.create_index(
        "idx_conversations_needs_attention",
        "conversations",
        ["needs_attention"],
        unique=False,
        postgresql_where=sa.text("needs_attention = true"),
        sqlite_where=sa.text("needs_attention = 1"),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_calls", sa.JSON(), nullable=True),
        sa.Column("needs_attention_row", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_by_owner", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("role IN ('visitor', 'twin', 'owner')", name="ck_messages_role"),
    )
    op.create_index(
        "idx_messages_conversation_id",
        "messages",
        ["conversation_id", "id"],
        unique=False,
    )

    op.create_table(
        "owner_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("additional_instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("id = 1", name="ck_owner_settings_singleton"),
    )
    settings = sa.table(
        "owner_settings",
        sa.column("id", sa.Integer),
        sa.column("additional_instructions", sa.Text),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        settings,
        [{"id": 1, "additional_instructions": "", "updated_at": datetime.now(UTC)}],
    )

    op.create_table(
        "archive_messages",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_calls", sa.JSON(), nullable=True),
        sa.Column("needs_attention_row", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_by_owner", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("conversation_id", "id"),
    )
    op.create_index(
        "idx_archive_messages_archived_at",
        "archive_messages",
        ["archived_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_archive_messages_archived_at", table_name="archive_messages")
    op.drop_table("archive_messages")
    op.drop_table("owner_settings")
    op.drop_index("idx_messages_conversation_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("idx_conversations_needs_attention", table_name="conversations")
    op.drop_index("idx_conversations_last_activity", table_name="conversations")
    op.drop_table("conversations")
