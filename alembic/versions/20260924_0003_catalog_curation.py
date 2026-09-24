"""Create the local versioned seller-catalog curation document.

Revision ID: 20260924_0003
Revises: 20260921_0002
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260924_0003"
down_revision: str | None = "20260921_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_curation_documents",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "id = 'seller-catalog'",
            name="ck_catalog_curation_documents_singleton",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_catalog_curation_documents_revision_positive",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(payload) = 'object'",
            name="ck_catalog_curation_documents_payload_object",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_catalog_curation_documents"),
    )


def downgrade() -> None:
    op.drop_table("catalog_curation_documents")
