"""Create the initial catalog snapshot table.

Revision ID: 20260919_0001
Revises: None
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260919_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "catalog_items",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("supplier", sa.String(length=64), nullable=False),
        sa.Column("price_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("available_quantity", sa.Integer(), nullable=False),
        sa.Column(
            "is_mock",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("price_minor >= 0", name="ck_catalog_items_price_nonnegative"),
        sa.CheckConstraint(
            "available_quantity >= 0",
            name="ck_catalog_items_quantity_nonnegative",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_catalog_items"),
    )


def downgrade() -> None:
    op.drop_table("catalog_items")
