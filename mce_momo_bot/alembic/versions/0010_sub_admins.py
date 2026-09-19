"""add bot_sub_admins table (yordamchi moderatorlar)

Revision ID: 0010_sub_admins
Revises: 0009_broadcast_log
Create Date: 2026-09-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_sub_admins"
down_revision: Union[str, None] = "0009_broadcast_log"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bot_sub_admins",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("added_by_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("bot_id", "telegram_user_id", name="uq_bot_sub_admin"),
    )
    op.create_index("ix_bot_sub_admins_bot_id", "bot_sub_admins", ["bot_id"])


def downgrade() -> None:
    op.drop_index("ix_bot_sub_admins_bot_id", table_name="bot_sub_admins")
    op.drop_table("bot_sub_admins")
