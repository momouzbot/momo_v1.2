"""add movies table

Revision ID: 0004_movies
Revises: 0003_bot_admin_chat
Create Date: 2026-08-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_movies"
down_revision: Union[str, None] = "0003_bot_admin_chat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "movies",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bot_id", sa.BigInteger(), sa.ForeignKey("bots.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("file_type", sa.String(20), nullable=False, server_default="video"),
        sa.Column("file_id", sa.String(255), nullable=False),
        sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("bot_id", "code", name="uq_bot_movie_code"),
    )
    op.create_index("ix_movies_bot_id", "movies", ["bot_id"])


def downgrade() -> None:
    op.drop_index("ix_movies_bot_id", table_name="movies")
    op.drop_table("movies")
