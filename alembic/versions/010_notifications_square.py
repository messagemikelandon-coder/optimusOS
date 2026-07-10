from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "010_notifications_square"
down_revision = "009_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=20), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "entity_type IN ('estimate', 'work_order', 'invoice')",
            name="ck_notifications_entity_type",
        ),
        sa.CheckConstraint(
            "event IN ("
            "'estimate_sent', 'estimate_approved', 'estimate_declined', "
            "'work_order_status_changed', 'invoice_issued', 'payment_recorded', "
            "'payment_voided'"
            ")",
            name="ck_notifications_event",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_notifications_owner_read_created",
        "notifications",
        ["owner_user_id", "read_at", "created_at"],
    )
    op.create_index(
        "ix_notifications_owner_created",
        "notifications",
        ["owner_user_id", "created_at"],
    )
    op.add_column("invoices", sa.Column("square_invoice_id", sa.String(length=64), nullable=True))
    op.add_column("invoices", sa.Column("square_status", sa.String(length=40), nullable=True))
    op.add_column("invoices", sa.Column("square_payment_url", sa.String(length=500), nullable=True))
    # NULLs don't collide in a unique index, so unpushed invoices are unaffected;
    # a Square invoice id can never map to two local invoices.
    op.create_index(
        "uq_invoices_square_invoice_id",
        "invoices",
        ["square_invoice_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_invoices_square_invoice_id", table_name="invoices")
    op.drop_column("invoices", "square_payment_url")
    op.drop_column("invoices", "square_status")
    op.drop_column("invoices", "square_invoice_id")
    op.drop_index("ix_notifications_owner_created", table_name="notifications")
    op.drop_index("ix_notifications_owner_read_created", table_name="notifications")
    op.drop_table("notifications")
