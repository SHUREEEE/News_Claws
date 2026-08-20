"""add audit log

Revision ID: 8f4c6d2a91b0
Revises: 1db90b61a654
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8f4c6d2a91b0"
down_revision: str | None = "1db90b61a654"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=120), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("method", sa.String(length=12), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("client_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_log_action"), "audit_log", ["action"], unique=False)
    op.create_index(op.f("ix_audit_log_actor"), "audit_log", ["actor"], unique=False)
    op.create_index(op.f("ix_audit_log_created_at"), "audit_log", ["created_at"], unique=False)
    op.create_index(op.f("ix_audit_log_request_id"), "audit_log", ["request_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_audit_log_request_id"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_created_at"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_actor"), table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_action"), table_name="audit_log")
    op.drop_table("audit_log")
