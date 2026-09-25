"""Encrypted local delivery references for the dormant VietShare capped test.

Revision ID: 20260925_0005
Revises: 20260925_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260925_0005"
down_revision: str | None = "20260925_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "vietshare_write_journal",
        sa.Column("secret_delivery_ref", sa.String(32), nullable=True),
    )
    op.create_unique_constraint(
        "uq_vietshare_journal_secret_ref",
        "vietshare_write_journal",
        ["secret_delivery_ref"],
    )
    op.create_table(
        "vietshare_secret_deliveries",
        sa.Column("delivery_ref", sa.String(32), primary_key=True),
        sa.Column("test_id", sa.String(64), nullable=False, unique=True),
        sa.Column("supplier_order_code", sa.String(128), nullable=False),
        sa.Column("ciphertext", postgresql.BYTEA(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["test_id"], ["vietshare_write_journal.test_id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "delivery_ref ~ '^[0-9a-f]{32}$'",
            name="ck_vietshare_secret_delivery_ref",
        ),
        sa.CheckConstraint(
            "octet_length(ciphertext) BETWEEN 1 AND 65536",
            name="ck_vietshare_secret_ciphertext_size",
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name="ck_vietshare_secret_expiry",
        ),
    )
    op.create_index(
        "ix_vietshare_secret_expires_at",
        "vietshare_secret_deliveries",
        ["expires_at"],
    )
    op.create_table(
        "vietshare_recovery_events",
        sa.Column("event_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("test_id", sa.String(64), nullable=False),
        sa.Column("operator_id", sa.String(128), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("evidence_ref", sa.String(256), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["test_id"], ["vietshare_write_journal.test_id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "action IN ('DISPATCH_LOST','UNKNOWN_TO_RECONCILING')",
            name="ck_vietshare_recovery_action",
        ),
    )
    op.execute("""CREATE FUNCTION prevent_vietshare_recovery_event_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'VietShare recovery events are immutable';
        END; $$""")
    op.execute(
        "CREATE TRIGGER trg_vietshare_recovery_events_immutable "
        "BEFORE UPDATE OR DELETE ON vietshare_recovery_events FOR EACH ROW "
        "EXECUTE FUNCTION prevent_vietshare_recovery_event_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vietshare_recovery_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_vietshare_recovery_event_mutation()")
    op.drop_index("ix_vietshare_secret_expires_at", table_name="vietshare_secret_deliveries")
    op.drop_table("vietshare_secret_deliveries")
    op.drop_constraint(
        "uq_vietshare_journal_secret_ref", "vietshare_write_journal", type_="unique"
    )
    op.drop_column("vietshare_write_journal", "secret_delivery_ref")
