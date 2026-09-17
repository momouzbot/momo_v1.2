"""add feature_usage_logs table (dedicated per-feature daily limits)

Revision ID: 0008_feature_usage
Revises: 0007_billing_period
Create Date: 2026-09-15

Kinobot yakuniy tahrir rejasi bo'yicha: ba'zi funksiyalar (kino qo'shish,
ommaviy xabar, mavsum ochish va h.k.) Momo tarifidan mustaqil, hamma uchun
bir xil kunlik limitga ega bo'lishi kerak. Bu jadval shu maqsadda umumiy
(qayta ishlatiladigan) hisoblagich sifatida ishlatiladi.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_feature_usage"
down_revision: Union[str, None] = "0007_billing_period"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feature_usage_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("feature_key", sa.String(64), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("bot_id", "feature_key", "date", name="uq_bot_feature_date"),
    )
    op.create_index("ix_feature_usage_logs_bot_id", "feature_usage_logs", ["bot_id"])


def downgrade() -> None:
    op.drop_index("ix_feature_usage_logs_bot_id", table_name="feature_usage_logs")
    op.drop_table("feature_usage_logs")
