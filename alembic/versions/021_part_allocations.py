from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "021_part_allocations"
down_revision = "020_purchase_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "part_allocations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("work_order_id", sa.Integer(), nullable=False),
        sa.Column("part_id", sa.Integer(), nullable=False),
        sa.Column("quantity_required", sa.Integer(), nullable=False),
        sa.Column("quantity_allocated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quantity_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("quantity_returned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unit_cost_snapshot", sa.Numeric(10, 2), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
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
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["part_id"], ["parts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["user_accounts.id"], ondelete="SET NULL"),
        sa.CheckConstraint("quantity_required > 0", name="ck_part_allocations_required_positive"),
        sa.CheckConstraint(
            "quantity_allocated >= 0", name="ck_part_allocations_allocated_non_negative"
        ),
        sa.CheckConstraint("quantity_used >= 0", name="ck_part_allocations_used_non_negative"),
        sa.CheckConstraint(
            "quantity_returned >= 0", name="ck_part_allocations_returned_non_negative"
        ),
        sa.CheckConstraint(
            "quantity_used <= quantity_allocated", name="ck_part_allocations_used_le_allocated"
        ),
        sa.CheckConstraint(
            "quantity_returned <= quantity_used",
            name="ck_part_allocations_returned_le_used",
        ),
    )
    op.create_index(
        "ix_part_allocations_owner_work_order",
        "part_allocations",
        ["owner_user_id", "work_order_id"],
    )
    op.create_index("ix_part_allocations_part", "part_allocations", ["part_id"])

    op.create_table(
        "part_allocation_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("allocation_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("quantity_delta", sa.Integer(), nullable=False),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_name", sa.String(length=160), nullable=True),
        sa.Column("inventory_override", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["allocation_id"], ["part_allocations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user_accounts.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "event_type IN ('allocated', 'used', 'returned')",
            name="ck_part_allocation_events_type",
        ),
        sa.CheckConstraint(
            "actor_type IN ('owner', 'technician')",
            name="ck_part_allocation_events_actor_type",
        ),
    )
    op.create_index(
        "ix_part_allocation_events_allocation_created",
        "part_allocation_events",
        ["allocation_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_part_allocation_events_allocation_created", table_name="part_allocation_events"
    )
    op.drop_table("part_allocation_events")

    op.drop_index("ix_part_allocations_part", table_name="part_allocations")
    op.drop_index("ix_part_allocations_owner_work_order", table_name="part_allocations")
    op.drop_table("part_allocations")
