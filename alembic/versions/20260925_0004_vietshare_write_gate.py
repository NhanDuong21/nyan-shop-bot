"""Persist a disabled, source-specific VietShare capped-test gate.

Revision ID: 20260925_0004
Revises: 20260924_0003
Create Date: 2026-09-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260925_0004"
down_revision: str | None = "20260924_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vietshare_write_gate_control",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "allowed_operator_ids", postgresql.ARRAY(sa.String(128)), nullable=False,
            server_default="{}",
        ),
        sa.Column("approved_test_id", sa.String(64), nullable=True),
        sa.Column("approved_product_id", sa.BigInteger(), nullable=True),
        sa.Column("approved_quantity", sa.Integer(), nullable=True),
        sa.Column("approved_max_unit_price_vnd", sa.BigInteger(), nullable=True),
        sa.Column("approved_spend_cap_vnd", sa.BigInteger(), nullable=True),
        sa.Column("approved_wallet_id", sa.String(128), nullable=True),
        sa.Column("approved_currency", sa.String(3), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("id = 1", name="ck_vietshare_gate_singleton"),
        sa.CheckConstraint(
            "approved_currency IS NULL OR approved_currency = 'VND'",
            name="ck_vietshare_gate_currency_vnd",
        ),
        sa.CheckConstraint(
            "NOT enabled OR (approved_test_id IS NOT NULL "
            "AND approved_product_id IS NOT NULL AND approved_product_id > 0 "
            "AND approved_quantity IS NOT NULL AND approved_quantity BETWEEN 1 AND 100 "
            "AND approved_max_unit_price_vnd IS NOT NULL AND approved_max_unit_price_vnd > 0 "
            "AND approved_spend_cap_vnd IS NOT NULL AND approved_spend_cap_vnd > 0 "
            "AND (approved_quantity::numeric * approved_max_unit_price_vnd) <= approved_spend_cap_vnd "
            "AND approved_wallet_id IS NOT NULL AND approved_currency = 'VND' "
            "AND cardinality(allowed_operator_ids) > 0)",
            name="ck_vietshare_gate_armed_complete",
        ),
    )
    op.execute(
        "INSERT INTO vietshare_write_gate_control (id, enabled, allowed_operator_ids) "
        "VALUES (1, false, ARRAY[]::varchar[])"
    )

    op.create_table(
        "vietshare_write_journal",
        sa.Column("test_id", sa.String(64), primary_key=True),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("raw_body", postgresql.BYTEA(), nullable=False),
        sa.Column("body_sha256", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("max_unit_price_vnd", sa.BigInteger(), nullable=False),
        sa.Column("absolute_spend_cap_vnd", sa.BigInteger(), nullable=False),
        sa.Column("wallet_id", sa.String(128), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("operator_id", sa.String(128), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("retry_not_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supplier_order_code", sa.String(128), nullable=True),
        sa.Column("last_error_code", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("source = 'vietshare'", name="ck_vietshare_journal_source"),
        sa.CheckConstraint("currency = 'VND'", name="ck_vietshare_journal_currency"),
        sa.CheckConstraint("product_id > 0", name="ck_vietshare_journal_product"),
        sa.CheckConstraint(
            "quantity BETWEEN 1 AND 100", name="ck_vietshare_journal_quantity"
        ),
        sa.CheckConstraint(
            "max_unit_price_vnd > 0 AND absolute_spend_cap_vnd > 0 "
            "AND (quantity::numeric * max_unit_price_vnd) <= absolute_spend_cap_vnd",
            name="ck_vietshare_journal_spend_cap",
        ),
        sa.CheckConstraint(
            "body_sha256 ~ '^[0-9a-f]{64}$'", name="ck_vietshare_journal_hash"
        ),
        sa.CheckConstraint(
            "idempotency_key ~ '^[A-Za-z0-9._:-]{8,128}$'",
            name="ck_vietshare_journal_key",
        ),
        sa.CheckConstraint(
            "state IN ('PREPARED','DISPATCHING','UNKNOWN','RECONCILING',"
            "'SUCCEEDED','FAILED_SAFE')",
            name="ck_vietshare_journal_state",
        ),
    )
    op.create_index(
        "uq_vietshare_unresolved_test", "vietshare_write_journal", ["source"],
        unique=True,
        postgresql_where=sa.text("state IN ('DISPATCHING','UNKNOWN','RECONCILING')"),
    )
    op.create_table(
        "vietshare_write_auth_attempts",
        sa.Column("nonce", sa.String(128), primary_key=True),
        sa.Column("test_id", sa.String(64), nullable=False),
        sa.Column("timestamp", sa.BigInteger(), nullable=False),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("body_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["test_id"], ["vietshare_write_journal.test_id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("test_id", "timestamp", name="uq_vietshare_auth_test_timestamp"),
        sa.CheckConstraint("method = 'POST'", name="ck_vietshare_auth_method"),
        sa.CheckConstraint(
            "body_sha256 ~ '^[0-9a-f]{64}$'", name="ck_vietshare_auth_hash"
        ),
    )
    op.execute(
        """CREATE FUNCTION prevent_vietshare_write_identity_update()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF (OLD.test_id, OLD.idempotency_key, OLD.raw_body, OLD.body_sha256,
                OLD.source, OLD.product_id, OLD.quantity, OLD.max_unit_price_vnd,
                OLD.absolute_spend_cap_vnd, OLD.wallet_id, OLD.currency, OLD.operator_id)
               IS DISTINCT FROM
               (NEW.test_id, NEW.idempotency_key, NEW.raw_body, NEW.body_sha256,
                NEW.source, NEW.product_id, NEW.quantity, NEW.max_unit_price_vnd,
                NEW.absolute_spend_cap_vnd, NEW.wallet_id, NEW.currency, NEW.operator_id)
            THEN
                RAISE EXCEPTION 'VietShare write identity is immutable';
            END IF;
            RETURN NEW;
        END; $$"""
    )
    op.execute(
        "CREATE TRIGGER trg_vietshare_write_identity_immutable "
        "BEFORE UPDATE ON vietshare_write_journal FOR EACH ROW "
        "EXECUTE FUNCTION prevent_vietshare_write_identity_update()"
    )


def downgrade() -> None:
    op.drop_table("vietshare_write_auth_attempts")
    op.drop_index("uq_vietshare_unresolved_test", table_name="vietshare_write_journal")
    op.drop_table("vietshare_write_journal")
    op.execute("DROP FUNCTION prevent_vietshare_write_identity_update()")
    op.drop_table("vietshare_write_gate_control")
