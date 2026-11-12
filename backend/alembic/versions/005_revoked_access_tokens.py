"""DB-backed access-token denylist.

Revision ID: 005_revoked_access_tokens
Revises: 004_refresh_tokens
Create Date: 2026-11-12
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "005_revoked_access_tokens"
down_revision = "004_refresh_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "revoked_access_tokens",
        sa.Column("jti", sa.String(length=36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("jti"),
    )
    op.create_index(
        "ix_revoked_access_tokens_expires_at",
        "revoked_access_tokens",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_revoked_access_tokens_expires_at", table_name="revoked_access_tokens"
    )
    op.drop_table("revoked_access_tokens")
