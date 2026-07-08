from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "008_invoices"
down_revision = "007_work_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invoices",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("work_order_id", sa.Integer(), nullable=False),
        sa.Column("estimate_id", sa.Integer(), nullable=False),
        sa.Column("estimate_revision_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("invoice_number", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("complaint", sa.Text(), nullable=False),
        sa.Column("payment_option_selected", sa.String(length=40), nullable=True),
        sa.Column("customer_snapshot", sa.JSON(), nullable=False),
        sa.Column("vehicle_snapshot", sa.JSON(), nullable=False),
        sa.Column("labor_total", sa.Float(), nullable=False),
        sa.Column("parts_total", sa.Float(), nullable=False),
        sa.Column("fees_total", sa.Float(), nullable=False),
        sa.Column("invoice_total", sa.Float(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('draft', 'issued', 'partially_paid', 'paid', 'overdue', 'void')",
            name="ck_invoices_status",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["estimate_id"], ["estimates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["estimate_revision_id"],
            ["estimate_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("work_order_id", name="uq_invoices_work_order"),
        sa.UniqueConstraint("invoice_number", name="uq_invoices_invoice_number"),
    )
    op.create_index(
        "ix_invoices_owner_status_updated",
        "invoices",
        ["owner_user_id", "status", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_invoices_owner_work_order",
        "invoices",
        ["owner_user_id", "work_order_id"],
        unique=False,
    )

    op.create_table(
        "invoice_line_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("invoice_id", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit_amount", sa.Float(), nullable=False),
        sa.Column("line_total", sa.Float(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('labor', 'part', 'fee')",
            name="ck_invoice_line_items_kind",
        ),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_invoice_line_items_invoice_sort",
        "invoice_line_items",
        ["invoice_id", "sort_order"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_invoice_line_items_invoice_sort", table_name="invoice_line_items")
    op.drop_table("invoice_line_items")
    op.drop_index("ix_invoices_owner_work_order", table_name="invoices")
    op.drop_index("ix_invoices_owner_status_updated", table_name="invoices")
    op.drop_table("invoices")
