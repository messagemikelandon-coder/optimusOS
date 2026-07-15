from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "020_purchase_orders"
down_revision = "019_diag_inspection_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("vendor_id", sa.Integer(), nullable=False),
        sa.Column("po_number", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("subtotal", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("total", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user_accounts.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('draft', 'submitted', 'partially_received', 'received', 'cancelled')",
            name="ck_purchase_orders_status",
        ),
        sa.UniqueConstraint("po_number", name="uq_purchase_orders_po_number"),
    )
    op.create_index(
        "ix_purchase_orders_owner_status_updated",
        "purchase_orders",
        ["owner_user_id", "status", "updated_at"],
    )
    op.create_index(
        "ix_purchase_orders_owner_vendor", "purchase_orders", ["owner_user_id", "vendor_id"]
    )

    op.create_table(
        "purchase_order_line_items",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("part_id", sa.Integer(), nullable=False),
        sa.Column("quantity_ordered", sa.Integer(), nullable=False),
        sa.Column("quantity_received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unit_cost", sa.Numeric(10, 2), nullable=False),
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
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["part_id"], ["parts.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("quantity_ordered > 0", name="ck_po_line_items_quantity_ordered"),
        sa.CheckConstraint(
            "quantity_received >= 0", name="ck_po_line_items_quantity_received_non_negative"
        ),
        sa.CheckConstraint(
            "quantity_received <= quantity_ordered",
            name="ck_po_line_items_quantity_received_le_ordered",
        ),
    )
    op.create_index(
        "ix_po_line_items_purchase_order", "purchase_order_line_items", ["purchase_order_id"]
    )
    op.create_index("ix_po_line_items_part", "purchase_order_line_items", ["part_id"])

    op.create_table(
        "purchase_order_receipts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("line_item_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("quantity_received", sa.Integer(), nullable=False),
        sa.Column("received_by_user_id", sa.Integer(), nullable=True),
        sa.Column("received_by_name", sa.String(length=160), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["line_item_id"], ["purchase_order_line_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["received_by_user_id"], ["user_accounts.id"], ondelete="SET NULL"),
        sa.CheckConstraint("quantity_received > 0", name="ck_po_receipts_quantity_positive"),
    )
    op.create_index(
        "ix_po_receipts_purchase_order_created",
        "purchase_order_receipts",
        ["purchase_order_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_po_receipts_purchase_order_created", table_name="purchase_order_receipts")
    op.drop_table("purchase_order_receipts")

    op.drop_index("ix_po_line_items_part", table_name="purchase_order_line_items")
    op.drop_index("ix_po_line_items_purchase_order", table_name="purchase_order_line_items")
    op.drop_table("purchase_order_line_items")

    op.drop_index("ix_purchase_orders_owner_vendor", table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_owner_status_updated", table_name="purchase_orders")
    op.drop_table("purchase_orders")
