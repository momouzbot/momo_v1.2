"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-25

TZ 9-bo'limdagi barcha asosiy jadvallarni yaratadi. Postgres mavjud
bo'lmagani sababli autogenerate emas, qo'lda yozilgan (modellarga mos).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

module_type_enum = sa.Enum(
    "admin", "support", "kino", "shop", "game_got", "game_mafia", "game_bunker", "custom",
    name="module_type",
)
tariff_code_enum = sa.Enum("start", "standard", "premium", name="tariff_code")
bot_status_enum = sa.Enum("active", "paused", "suspended", "deleted", name="bot_status")
payment_status_enum = sa.Enum("pending", "approved", "rejected", name="payment_status")
payment_kind_enum = sa.Enum("hosting", "tariff_upgrade", name="payment_kind")


def upgrade() -> None:
    bind = op.get_bind()
    module_type_enum.create(bind, checkfirst=True)
    tariff_code_enum.create(bind, checkfirst=True)
    bot_status_enum.create(bind, checkfirst=True)
    payment_status_enum.create(bind, checkfirst=True)
    payment_kind_enum.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("is_momo_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])

    op.create_table(
        "tariffs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", tariff_code_enum, nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("bot_limit", sa.Integer(), nullable=False),
        sa.Column("edit_limit_per_day", sa.Integer(), nullable=False),
        sa.Column("upgrade_price", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("base_hosting_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("user_threshold", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("duration_days", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "modules",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("code", module_type_enum, nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "bots",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_bot_id", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("token_encrypted", sa.String(512), nullable=False),
        sa.Column("module_type", module_type_enum, nullable=False),
        sa.Column("status", bot_status_enum, nullable=False, server_default="active"),
        sa.Column("webhook_set", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("force_subscribe_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("force_subscribe_channels", sa.String(), nullable=True),
        sa.Column("captcha_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("welcome_message", sa.String(), nullable=True),
        sa.Column("spam_filter_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_bots_telegram_bot_id", "bots", ["telegram_bot_id"])

    op.create_table(
        "bot_users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("bot_id", "telegram_user_id", name="uq_bot_user"),
    )

    op.create_table(
        "bot_tariffs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tariff_code", tariff_code_enum, nullable=False),
        sa.Column("started_at", sa.Date(), nullable=False),
        sa.Column("expires_at", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "edit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("bot_id", "date", name="uq_bot_edit_date"),
    )

    op.create_table(
        "hosting_payments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", payment_status_enum, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "tariff_upgrades",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tariff_code", tariff_code_enum, nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", payment_status_enum, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "payments",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", payment_kind_enum, nullable=False),
        sa.Column("reference_id", sa.BigInteger(), nullable=True),
        sa.Column("receipt_file_id", sa.String(255), nullable=False),
        sa.Column("status", payment_status_enum, nullable=False, server_default="pending"),
        sa.Column("reviewed_by_admin_id", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("rejection_reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "game_settings",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("max_players", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("max_active_sessions", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("scheduler_interval_minutes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "game_instances",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="waiting"),
        sa.Column("phase", sa.String(50), nullable=True),
        sa.Column("state", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "game_players",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("game_instance_id", sa.BigInteger(), sa.ForeignKey("game_instances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(50), nullable=True),
        sa.Column("is_alive", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("resources", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "custom_commands",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("buyruq", sa.String(64), nullable=False),
        sa.Column("javob_matni", sa.String(), nullable=True),
        sa.Column("media_file_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "custom_buttons",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), sa.ForeignKey("custom_buttons.id", ondelete="CASCADE"), nullable=True),
        sa.Column("matn", sa.String(100), nullable=False),
        sa.Column("turi", sa.String(50), nullable=False),
        sa.Column("target_command_id", sa.BigInteger(), sa.ForeignKey("custom_commands.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("custom_buttons")
    op.drop_table("custom_commands")
    op.drop_table("game_players")
    op.drop_table("game_instances")
    op.drop_table("game_settings")
    op.drop_table("payments")
    op.drop_table("tariff_upgrades")
    op.drop_table("hosting_payments")
    op.drop_table("edit_logs")
    op.drop_table("bot_tariffs")
    op.drop_table("bot_users")
    op.drop_table("bots")
    op.drop_table("modules")
    op.drop_table("tariffs")
    op.drop_table("users")

    bind = op.get_bind()
    payment_kind_enum.drop(bind, checkfirst=True)
    payment_status_enum.drop(bind, checkfirst=True)
    bot_status_enum.drop(bind, checkfirst=True)
    tariff_code_enum.drop(bind, checkfirst=True)
    module_type_enum.drop(bind, checkfirst=True)
