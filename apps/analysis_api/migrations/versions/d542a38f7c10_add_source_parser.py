"""add source parser

Revision ID: d542a38f7c10
Revises: c31e8f2407ad
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d542a38f7c10"
down_revision: str | None = "c31e8f2407ad"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source",
        sa.Column("parser", sa.String(length=32), nullable=False, server_default="auto"),
    )


def downgrade() -> None:
    op.drop_column("source", "parser")
