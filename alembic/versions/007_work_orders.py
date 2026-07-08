from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "007_work_orders"
down_revision = "006_estimate_approvals"
branch_labels = None
depends_on = None

_WORK_ORDER_STATUS_VALUES = (
    "'pending_requirements', 'ready_to_schedule', 'scheduled', 'in_progress', "
    "'waiting_for_parts', 'waiting_for_approval', 'completed', 'cancelled'"
)
_WORK_ORDER_STATUS_CHECK = "status IN (" + _WORK_ORDER_STATUS_VALUES + ")"


def _status_check(column_name: str) -> str:
    return f"{column_name} IN ({_WORK_ORDER_STATUS_VALUES})"


def upgrade() -> None:
    op.create_table(
        "work_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("estimate_id", sa.Integer(), nullable=False),
        sa.Column("estimate_revision_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("estimate_number", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("complaint", sa.Text(), nullable=False),
        sa.Column("diagnosis", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("estimate_total", sa.Float(), nullable=True),
        sa.Column("labor_hours_estimate", sa.Float(), nullable=True),
        sa.Column("payment_option_selected", sa.String(length=40), nullable=True),
        sa.Column("deposit_received", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "authorization_confirmed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(_WORK_ORDER_STATUS_CHECK, name="ck_work_orders_status"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["estimate_id"], ["estimates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["estimate_revision_id"],
            ["estimate_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "estimate_id",
            "estimate_revision_id",
            name="uq_work_orders_estimate_revision",
        ),
    )
    op.create_index(
        "ix_work_orders_owner_status_updated",
        "work_orders",
        ["owner_user_id", "status", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_work_orders_owner_customer_updated",
        "work_orders",
        ["owner_user_id", "customer_id", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_work_orders_owner_vehicle_updated",
        "work_orders",
        ["owner_user_id", "vehicle_id", "updated_at"],
        unique=False,
    )

    op.create_table(
        "work_order_status_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("work_order_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("from_status", sa.String(length=40), nullable=True),
        sa.Column("to_status", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "from_status IS NULL OR " + _status_check("from_status"),
            name="ck_work_order_status_events_from_status",
        ),
        sa.CheckConstraint(
            _status_check("to_status"),
            name="ck_work_order_status_events_to_status",
        ),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["user_accounts.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_work_order_status_events_work_order_created",
        "work_order_status_events",
        ["work_order_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "work_order_notes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("work_order_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "visibility IN ('internal', 'customer')",
            name="ck_work_order_notes_visibility",
        ),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["user_accounts.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_work_order_notes_work_order_created",
        "work_order_notes",
        ["work_order_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_work_order_notes_work_order_created", table_name="work_order_notes")
    op.drop_table("work_order_notes")
    op.drop_index(
        "ix_work_order_status_events_work_order_created",
        table_name="work_order_status_events",
    )
    op.drop_table("work_order_status_events")
    op.drop_index("ix_work_orders_owner_vehicle_updated", table_name="work_orders")
    op.drop_index("ix_work_orders_owner_customer_updated", table_name="work_orders")
    op.drop_index("ix_work_orders_owner_status_updated", table_name="work_orders")
    op.drop_table("work_orders")
