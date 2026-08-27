"""add admin_chat_id to bots

Revision ID: 0003_bot_admin_chat
Revises: 0002_appeals
Create Date: 2026-08-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_bot_admin_chat"
down_revision: Union[str, None] = "0002_appeals"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bots", sa.Column("admin_chat_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("bots", "admin_chat_id")
