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
        sa.Column("approved_by", sa.String(128), nullable=True),
        sa.Column("approval_ref", sa.String(256), nullable=True),
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
            "AND approved_wallet_id IS NOT NULL "
            "AND approved_currency IS NOT NULL AND approved_currency = 'VND' "
            "AND approved_by IS NOT NULL AND length(approved_by) > 0 "
            "AND approval_ref IS NOT NULL AND length(approval_ref) > 0 "
            "AND cardinality(allowed_operator_ids) > 0)",
            name="ck_vietshare_gate_armed_complete",
        ),
    )
    op.execute(
        "INSERT INTO vietshare_write_gate_control (id, enabled, allowed_operator_ids) "
        "VALUES (1, false, ARRAY[]::varchar[])"
    )
    op.create_table(
        "vietshare_write_gate_events",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("allowed_operator_ids", postgresql.ARRAY(sa.String(128)), nullable=False),
        sa.Column("approved_test_id", sa.String(64), nullable=True),
        sa.Column("approved_product_id", sa.BigInteger(), nullable=True),
        sa.Column("approved_quantity", sa.Integer(), nullable=True),
        sa.Column("approved_max_unit_price_vnd", sa.BigInteger(), nullable=True),
        sa.Column("approved_spend_cap_vnd", sa.BigInteger(), nullable=True),
        sa.Column("approved_wallet_id", sa.String(128), nullable=True),
        sa.Column("approved_currency", sa.String(3), nullable=True),
        sa.Column("approved_by", sa.String(128), nullable=True),
        sa.Column("approval_ref", sa.String(256), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.execute(
        """CREATE FUNCTION audit_vietshare_gate_control()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            INSERT INTO vietshare_write_gate_events (
                enabled, allowed_operator_ids, approved_test_id,
                approved_product_id, approved_quantity,
                approved_max_unit_price_vnd, approved_spend_cap_vnd,
                approved_wallet_id, approved_currency, approved_by, approval_ref
            ) VALUES (
                NEW.enabled, NEW.allowed_operator_ids, NEW.approved_test_id,
                NEW.approved_product_id, NEW.approved_quantity,
                NEW.approved_max_unit_price_vnd, NEW.approved_spend_cap_vnd,
                NEW.approved_wallet_id, NEW.approved_currency, NEW.approved_by,
                NEW.approval_ref
            );
            RETURN NEW;
        END; $$"""
    )
    op.execute(
        "CREATE TRIGGER trg_vietshare_gate_audit "
        "AFTER UPDATE ON vietshare_write_gate_control FOR EACH ROW "
        "EXECUTE FUNCTION audit_vietshare_gate_control()"
    )
    op.execute(
        """CREATE FUNCTION prevent_vietshare_gate_event_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'VietShare gate audit events are immutable';
        END; $$"""
    )
    op.execute(
        "CREATE TRIGGER trg_vietshare_gate_events_immutable "
        "BEFORE UPDATE OR DELETE ON vietshare_write_gate_events FOR EACH ROW "
        "EXECUTE FUNCTION prevent_vietshare_gate_event_mutation()"
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
        sa.Column("wallet_debit_vnd", sa.BigInteger(), nullable=True),
        sa.Column("wallet_debit_evidence_ref", sa.String(256), nullable=True),
        sa.Column("wallet_debit_checked_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "wallet_debit_vnd IS NULL OR wallet_debit_vnd >= 0",
            name="ck_vietshare_journal_wallet_debit",
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
        sa.Column("canonical_sha256", sa.String(64), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("response_code", sa.String(64), nullable=True),
        sa.Column("retry_after_header", sa.String(256), nullable=True),
        sa.Column("outcome_state", sa.String(32), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "canonical_sha256 ~ '^[0-9a-f]{64}$'", name="ck_vietshare_auth_canonical_hash"
        ),
        sa.CheckConstraint(
            "http_status IS NULL OR http_status BETWEEN 100 AND 599",
            name="ck_vietshare_auth_http_status",
        ),
        sa.CheckConstraint(
            "outcome_state IS NULL OR outcome_state IN "
            "('UNKNOWN','RECONCILING','SUCCEEDED')",
            name="ck_vietshare_auth_outcome",
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
    op.execute(
        """CREATE FUNCTION prevent_vietshare_write_journal_delete()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'VietShare write journal rows cannot be deleted';
        END; $$"""
    )
    op.execute(
        "CREATE TRIGGER trg_vietshare_write_no_delete "
        "BEFORE DELETE ON vietshare_write_journal FOR EACH ROW "
        "EXECUTE FUNCTION prevent_vietshare_write_journal_delete()"
    )


def downgrade() -> None:
    op.drop_table("vietshare_write_auth_attempts")
    op.drop_index("uq_vietshare_unresolved_test", table_name="vietshare_write_journal")
    op.drop_table("vietshare_write_journal")
    op.execute("DROP FUNCTION prevent_vietshare_write_identity_update()")
    op.execute("DROP FUNCTION IF EXISTS prevent_vietshare_write_journal_delete()")
    op.execute("DROP TRIGGER IF EXISTS trg_vietshare_gate_audit ON vietshare_write_gate_control")
    op.execute("DROP FUNCTION IF EXISTS audit_vietshare_gate_control()")
    op.execute("DROP FUNCTION IF EXISTS prevent_vietshare_gate_event_mutation() CASCADE")
    op.execute("DROP TABLE IF EXISTS vietshare_write_gate_events")
    op.drop_table("vietshare_write_gate_control")
