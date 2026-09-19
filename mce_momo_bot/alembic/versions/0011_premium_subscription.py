"""add premium subscription system (kino module)

Revision ID: 0011_premium_subscription
Revises: 0010_sub_admins
Create Date: 2026-09-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PGEnum

revision: str = "0011_premium_subscription"
down_revision: Union[str, None] = "0010_sub_admins"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

payment_status_enum = PGEnum("pending", "approved", "rejected", name="payment_status", create_type=False)


def upgrade() -> None:
    op.add_column(
        "bots", sa.Column("premium_subscription_enabled", sa.Boolean(), nullable=False, server_default="false")
    )
    op.add_column(
        "bots", sa.Column("premium_subscription_price", sa.Numeric(12, 2), nullable=False, server_default="0")
    )
    op.add_column(
        "bots",
        sa.Column("premium_subscription_duration_days", sa.Integer(), nullable=False, server_default="30"),
    )

    op.add_column("movies", sa.Column("is_premium", sa.Boolean(), nullable=False, server_default="false"))

    op.create_table(
        "premium_subscribers",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("bot_id", "telegram_user_id", name="uq_premium_subscriber"),
    )
    op.create_index("ix_premium_subscribers_bot_id", "premium_subscribers", ["bot_id"])

    op.create_table(
        "premium_subscription_payments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("receipt_file_id", sa.String(255), nullable=False),
        sa.Column("status", payment_status_enum, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index(
        "ix_premium_subscription_payments_bot_id", "premium_subscription_payments", ["bot_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_premium_subscription_payments_bot_id", table_name="premium_subscription_payments")
    op.drop_table("premium_subscription_payments")

    op.drop_index("ix_premium_subscribers_bot_id", table_name="premium_subscribers")
    op.drop_table("premium_subscribers")

    op.drop_column("movies", "is_premium")

    op.drop_column("bots", "premium_subscription_duration_days")
    op.drop_column("bots", "premium_subscription_price")
    op.drop_column("bots", "premium_subscription_enabled")
