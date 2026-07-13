from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "016_scheduling"
down_revision = "015_diagnostics_inspections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bays",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false"),
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
    )
    op.create_index("ix_bays_owner_archived_name", "bays", ["owner_user_id", "is_archived", "name"])

    op.create_table(
        "working_hours",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("technician_id", sa.Integer(), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("start_minute", sa.Integer(), nullable=False),
        sa.Column("end_minute", sa.Integer(), nullable=False),
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
        sa.ForeignKeyConstraint(["technician_id"], ["technicians.id"], ondelete="CASCADE"),
        sa.CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_working_hours_day_of_week"),
        sa.CheckConstraint(
            "start_minute >= 0 AND start_minute < 1440", name="ck_working_hours_start_minute"
        ),
        sa.CheckConstraint(
            "end_minute > 0 AND end_minute <= 1440", name="ck_working_hours_end_minute"
        ),
        sa.CheckConstraint("end_minute > start_minute", name="ck_working_hours_end_after_start"),
    )
    op.create_index(
        "ix_working_hours_owner_technician_day",
        "working_hours",
        ["owner_user_id", "technician_id", "day_of_week"],
    )

    op.create_table(
        "schedule_blocks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("technician_id", sa.Integer(), nullable=True),
        sa.Column("bay_id", sa.Integer(), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["technician_id"], ["technicians.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bay_id"], ["bays.id"], ondelete="CASCADE"),
        sa.CheckConstraint("end_time > start_time", name="ck_schedule_blocks_end_after_start"),
    )
    op.create_index(
        "ix_schedule_blocks_owner_technician_time",
        "schedule_blocks",
        ["owner_user_id", "technician_id", "start_time", "end_time"],
    )
    op.create_index(
        "ix_schedule_blocks_owner_bay_time",
        "schedule_blocks",
        ["owner_user_id", "bay_id", "start_time", "end_time"],
    )

    op.create_table(
        "appointments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("work_order_id", sa.Integer(), nullable=True),
        sa.Column("technician_id", sa.Integer(), nullable=False),
        sa.Column("bay_id", sa.Integer(), nullable=True),
        sa.Column("service_type", sa.String(length=160), nullable=False),
        sa.Column("service_location", sa.String(length=20), nullable=False, server_default="shop"),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("travel_buffer_minutes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="tentative"),
        sa.Column("customer_notes", sa.Text(), nullable=True),
        sa.Column("internal_notes", sa.Text(), nullable=True),
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
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["technician_id"], ["technicians.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["bay_id"], ["bays.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('tentative','confirmed','in_progress','completed','canceled','no_show')",
            name="ck_appointments_status",
        ),
        sa.CheckConstraint(
            "service_location IN ('shop','mobile')", name="ck_appointments_service_location"
        ),
        sa.CheckConstraint("end_time > start_time", name="ck_appointments_end_after_start"),
        sa.CheckConstraint(
            "travel_buffer_minutes >= 0", name="ck_appointments_travel_buffer_nonneg"
        ),
    )
    op.create_index(
        "ix_appointments_owner_technician_time",
        "appointments",
        ["owner_user_id", "technician_id", "start_time", "end_time"],
    )
    op.create_index(
        "ix_appointments_owner_bay_time",
        "appointments",
        ["owner_user_id", "bay_id", "start_time", "end_time"],
    )
    op.create_index(
        "ix_appointments_owner_status_start",
        "appointments",
        ["owner_user_id", "status", "start_time"],
    )
    op.create_index(
        "ix_appointments_owner_customer", "appointments", ["owner_user_id", "customer_id"]
    )
    op.create_index(
        "ix_appointments_owner_vehicle", "appointments", ["owner_user_id", "vehicle_id"]
    )
    op.create_index("ix_appointments_work_order", "appointments", ["work_order_id"])


def downgrade() -> None:
    op.drop_index("ix_appointments_work_order", table_name="appointments")
    op.drop_index("ix_appointments_owner_vehicle", table_name="appointments")
    op.drop_index("ix_appointments_owner_customer", table_name="appointments")
    op.drop_index("ix_appointments_owner_status_start", table_name="appointments")
    op.drop_index("ix_appointments_owner_bay_time", table_name="appointments")
    op.drop_index("ix_appointments_owner_technician_time", table_name="appointments")
    op.drop_table("appointments")

    op.drop_index("ix_schedule_blocks_owner_bay_time", table_name="schedule_blocks")
    op.drop_index("ix_schedule_blocks_owner_technician_time", table_name="schedule_blocks")
    op.drop_table("schedule_blocks")

    op.drop_index("ix_working_hours_owner_technician_day", table_name="working_hours")
    op.drop_table("working_hours")

    op.drop_index("ix_bays_owner_archived_name", table_name="bays")
    op.drop_table("bays")
