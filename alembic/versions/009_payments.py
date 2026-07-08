from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "009_payments"
down_revision = "008_invoices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoice_payments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("applies_to", sa.String(length=20), nullable=False),
        sa.Column("method_label", sa.String(length=60), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reversal_of_payment_id", sa.Integer(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "applies_to IN ('deposit', 'installment', 'balance', 'full', 'other')",
            name="ck_invoice_payments_applies_to",
        ),
        sa.CheckConstraint(
            "(reversal_of_payment_id IS NULL AND amount > 0) "
            "OR (reversal_of_payment_id IS NOT NULL AND amount < 0)",
            name="ck_invoice_payments_amount_sign",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["reversal_of_payment_id"],
            ["invoice_payments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["user_accounts.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("reversal_of_payment_id", name="uq_invoice_payments_reversal_of"),
    )
    op.create_index(
        "ix_invoice_payments_owner_invoice_recorded",
        "invoice_payments",
        ["owner_user_id", "invoice_id", "recorded_at"],
        unique=False,
    )

    op.create_table(
        "payment_schedules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("invoice_id", "sort_order", name="uq_payment_schedules_invoice_sort"),
    )
    op.create_index(
        "ix_payment_schedules_owner_invoice_sort",
        "payment_schedules",
        ["owner_user_id", "invoice_id", "sort_order"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_payment_schedules_owner_invoice_sort", table_name="payment_schedules")
    op.drop_table("payment_schedules")
    op.drop_index("ix_invoice_payments_owner_invoice_recorded", table_name="invoice_payments")
    op.drop_table("invoice_payments")
