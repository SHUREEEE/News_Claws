"""add subscriptions

Revision ID: c31e8f2407ad
Revises: 8f4c6d2a91b0
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c31e8f2407ad"
down_revision: str | None = "8f4c6d2a91b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "subscription",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("company_ids", sa.JSON(), nullable=False),
        sa.Column("industry_ids", sa.JSON(), nullable=False),
        sa.Column("min_relevance", sa.Integer(), nullable=False),
        sa.Column("frequency", sa.String(length=24), nullable=False),
        sa.Column("digest_hour_utc", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_subscription_email"),
        "subscription",
        ["email"],
        unique=True,
    )
    op.create_index(
        op.f("ix_subscription_enabled"),
        "subscription",
        ["enabled"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_subscription_enabled"), table_name="subscription")
    op.drop_index(op.f("ix_subscription_email"), table_name="subscription")
    op.drop_table("subscription")
