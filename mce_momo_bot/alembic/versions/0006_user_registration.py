"""add user registration fields (phone, preferred tariff) + tariff description

Revision ID: 0006_user_registration
Revises: 0005_external_hosting
Create Date: 2026-09-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_user_registration"
down_revision: Union[str, None] = "0005_external_hosting"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("phone_number", sa.String(32), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "preferred_tariff_code",
            sa.Enum("start", "standard", "premium", name="tariff_code"),
            nullable=True,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "registration_completed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("tariffs", sa.Column("description", sa.String(1000), nullable=True))


def downgrade() -> None:
    op.drop_column("tariffs", "description")
    op.drop_column("users", "registration_completed")
    op.drop_column("users", "preferred_tariff_code")
    op.drop_column("users", "phone_number")
