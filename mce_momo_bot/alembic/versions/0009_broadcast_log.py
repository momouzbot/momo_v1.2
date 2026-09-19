"""add broadcast_logs table (ommaviy xabar tarixi)

Revision ID: 0009_broadcast_log
Revises: 0008_feature_usage
Create Date: 2026-09-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_broadcast_log"
down_revision: Union[str, None] = "0008_feature_usage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "broadcast_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sent_by_telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("total_recipients", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_broadcast_logs_bot_id", "broadcast_logs", ["bot_id"])


def downgrade() -> None:
    op.drop_index("ix_broadcast_logs_bot_id", table_name="broadcast_logs")
    op.drop_table("broadcast_logs")
