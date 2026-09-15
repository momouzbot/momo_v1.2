"""add billing_period + weekly hosting price + tariff grace period, apply new pricing table

Revision ID: 0007_billing_period
Revises: 0006_user_registration
Create Date: 2026-09-14

Mijoz taqdim etgan yangi narx jadvaliga muvofiq:
    - hosting to'lovi endi HAFTALIK yoki OYLIK bo'lishi mumkin (billing_period)
    - har bir tarifning haftalik narxi alohida (weekly_hosting_price)
    - tarif muddati tugagach botlar yana necha kun faol qolishi (grace_period_days)
      — Premium uchun 30 kun, Standard uchun 0 (darhol)
    - uch tarifning barcha raqamlari (narx, muddat, bot soni, tahrir limiti)
      yuborilgan jadvalga moslab yangilangan
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ENUM as PGEnum

revision: str = "0007_billing_period"
down_revision: Union[str, None] = "0006_user_registration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

billing_period_enum = PGEnum("weekly", "monthly", name="billing_period", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    billing_period_enum.create(bind, checkfirst=True)

    # --- tariffs: yangi ustunlar ---
    op.add_column("tariffs", sa.Column("weekly_hosting_price", sa.Numeric(12, 2), nullable=False, server_default="0"))
    op.add_column("tariffs", sa.Column("grace_period_days", sa.Integer(), nullable=False, server_default="0"))

    # --- hosting_payments: period_month -> billing_period + period_start ---
    op.add_column(
        "hosting_payments",
        sa.Column("billing_period", billing_period_enum, nullable=False, server_default="monthly"),
    )
    op.add_column("hosting_payments", sa.Column("period_start", sa.Date(), nullable=True))
    op.execute("UPDATE hosting_payments SET period_start = period_month")
    op.alter_column("hosting_payments", "period_start", nullable=False)
    op.drop_column("hosting_payments", "period_month")

    # --- Mijoz taqdim etgan narx jadvali bo'yicha boshlang'ich qiymatlar ---
    op.execute(
        """
        UPDATE tariffs SET
            upgrade_price = 0, duration_days = NULL,
            bot_limit = 1, edit_limit_per_day = 3,
            base_hosting_price = 12000, weekly_hosting_price = 3900,
            grace_period_days = 0
        WHERE code = 'start'
        """
    )
    op.execute(
        """
        UPDATE tariffs SET
            upgrade_price = 49000, duration_days = 60,
            bot_limit = 3, edit_limit_per_day = 5,
            base_hosting_price = 10000, weekly_hosting_price = 2900,
            grace_period_days = 0
        WHERE code = 'standard'
        """
    )
    op.execute(
        """
        UPDATE tariffs SET
            upgrade_price = 150000, duration_days = 180,
            bot_limit = 5, edit_limit_per_day = 10,
            base_hosting_price = 7000, weekly_hosting_price = 1900,
            grace_period_days = 30
        WHERE code = 'premium'
        """
    )


def downgrade() -> None:
    op.add_column("hosting_payments", sa.Column("period_month", sa.Date(), nullable=True))
    op.execute("UPDATE hosting_payments SET period_month = period_start")
    op.alter_column("hosting_payments", "period_month", nullable=False)
    op.drop_column("hosting_payments", "period_start")
    op.drop_column("hosting_payments", "billing_period")

    op.drop_column("tariffs", "grace_period_days")
    op.drop_column("tariffs", "weekly_hosting_price")

    billing_period_enum.drop(op.get_bind(), checkfirst=True)
