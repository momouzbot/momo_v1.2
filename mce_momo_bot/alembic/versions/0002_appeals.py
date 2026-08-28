"""add appeals table

Revision ID: 0002_appeals
Revises: 0001_initial
Create Date: 2026-08-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PGEnum

revision: str = "0002_appeals"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# postgresql.ENUM + create_type=False — create_table() CREATE TYPE'ni yana
# avtomatik chiqarmasligi uchun (0001_initial.py dagi izohga qarang).
appeal_status_enum = PGEnum("new", "in_progress", "answered", "closed", name="appeal_status", create_type=False)
appeal_category_enum = PGEnum("technical", "financial", "general", name="appeal_category", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    appeal_status_enum.create(bind, checkfirst=True)
    appeal_category_enum.create(bind, checkfirst=True)

    op.create_table(
        "appeals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("category", appeal_category_enum, nullable=False, server_default="general"),
        sa.Column("status", appeal_status_enum, nullable=False, server_default="new"),
        sa.Column("message_text", sa.String(), nullable=False),
        sa.Column("admin_reply_text", sa.String(), nullable=True),
        sa.Column("forwarded_message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_appeals_bot_id", "appeals", ["bot_id"])


def downgrade() -> None:
    op.drop_index("ix_appeals_bot_id", table_name="appeals")
    op.drop_table("appeals")

    bind = op.get_bind()
    appeal_category_enum.drop(bind, checkfirst=True)
    appeal_status_enum.drop(bind, checkfirst=True)
