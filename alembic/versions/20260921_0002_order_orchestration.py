"""Create the mock order orchestration persistence boundary.

Revision ID: 20260921_0002
Revises: 20260919_0001
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260921_0002"
down_revision: str | None = "20260919_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PURCHASE_STATES = (
    "PREPARED",
    "DISPATCHING",
    "SUCCEEDED",
    "FAILED_SAFE",
    "UNKNOWN",
    "RECONCILING",
)
DELIVERY_STATES = ("PENDING", "SUCCEEDED", "FAILED")


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "order_intents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("customer_reference", sa.String(length=128), nullable=False),
        sa.Column("product_id", sa.String(length=128), nullable=False),
        sa.Column("variant_id", sa.String(length=128), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("max_unit_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("money_unit", sa.String(length=32), nullable=False),
        sa.Column("purchase_state", sa.String(length=32), nullable=False),
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
        sa.CheckConstraint("quantity > 0", name="ck_order_intents_quantity_positive"),
        sa.CheckConstraint(
            "unit_price_minor >= 0",
            name="ck_order_intents_unit_price_nonnegative",
        ),
        sa.CheckConstraint(
            "max_unit_price_minor >= 0",
            name="ck_order_intents_price_nonnegative",
        ),
        sa.CheckConstraint(
            "unit_price_minor <= max_unit_price_minor",
            name="ck_order_intents_price_within_cap",
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'",
            name="ck_order_intents_currency_code",
        ),
        sa.CheckConstraint(
            "money_unit = 'minor'",
            name="ck_order_intents_money_unit_minor",
        ),
        sa.CheckConstraint(
            f"purchase_state IN ({_quoted(PURCHASE_STATES)})",
            name="ck_order_intents_purchase_state",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_order_intents"),
        sa.UniqueConstraint("idempotency_key", name="uq_order_intents_idempotency_key"),
    )

    op.create_table(
        "supplier_order_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("order_intent_id", sa.String(length=36), nullable=False),
        sa.Column("supplier_code", sa.String(length=64), nullable=False),
        sa.Column("request_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("supplier_order_reference", sa.String(length=128), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
            "char_length(request_fingerprint) = 64",
            name="ck_supplier_order_attempts_fingerprint_length",
        ),
        sa.CheckConstraint(
            f"status IN ({_quoted(PURCHASE_STATES)})",
            name="ck_supplier_order_attempts_status",
        ),
        sa.ForeignKeyConstraint(
            ("order_intent_id",),
            ("order_intents.id",),
            name="fk_supplier_order_attempts_order_intent",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_supplier_order_attempts"),
        sa.UniqueConstraint(
            "order_intent_id",
            name="uq_supplier_order_attempts_order_intent",
        ),
        sa.UniqueConstraint("request_key", name="uq_supplier_order_attempts_request_key"),
    )

    op.create_table(
        "delivery_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("order_intent_id", sa.String(length=36), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("delivery_key", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            "attempt_number > 0",
            name="ck_delivery_attempts_number_positive",
        ),
        sa.CheckConstraint(
            f"status IN ({_quoted(DELIVERY_STATES)})",
            name="ck_delivery_attempts_status",
        ),
        sa.ForeignKeyConstraint(
            ("order_intent_id",),
            ("order_intents.id",),
            name="fk_delivery_attempts_order_intent",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_delivery_attempts"),
        sa.UniqueConstraint(
            "order_intent_id",
            "attempt_number",
            name="uq_delivery_attempts_order_number",
        ),
        sa.UniqueConstraint("delivery_key", name="uq_delivery_attempts_delivery_key"),
    )


def downgrade() -> None:
    op.drop_table("delivery_attempts")
    op.drop_table("supplier_order_attempts")
    op.drop_table("order_intents")
