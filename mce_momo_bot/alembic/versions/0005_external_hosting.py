"""add external hosting fields to bots

Revision ID: 0005_external_hosting
Revises: 0004_movies
Create Date: 2026-08-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_external_hosting"
down_revision: Union[str, None] = "0004_movies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bots",
        sa.Column("is_externally_hosted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("bots", sa.Column("external_api_key", sa.String(64), nullable=True))
    op.add_column(
        "bots",
        sa.Column("external_user_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("bots", "external_user_count")
    op.drop_column("bots", "external_api_key")
    op.drop_column("bots", "is_externally_hosted")
