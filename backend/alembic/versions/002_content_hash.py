"""Phase B: add documents.content_hash for per-owner dedupe.

Revision ID: 002_content_hash
Revises: 001_initial
Create Date: 2026-10-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "002_content_hash"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents", sa.Column("content_hash", sa.String(64), nullable=True)
    )
    op.create_index(
        "ix_documents_owner_content_hash",
        "documents",
        ["owner_id", "content_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_owner_content_hash", table_name="documents")
    op.drop_column("documents", "content_hash")
