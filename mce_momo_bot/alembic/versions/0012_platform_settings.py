"""add platform_settings table (to'lov rekvizitlari)

Revision ID: 0012_platform_settings
Revises: 0011_premium_subscription
Create Date: 2026-09-21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_platform_settings"
down_revision: Union[str, None] = "0011_premium_subscription"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_settings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("payment_card_number", sa.String(64), nullable=True),
        sa.Column("payment_card_holder", sa.String(255), nullable=True),
        sa.Column("payment_instructions", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("platform_settings")
