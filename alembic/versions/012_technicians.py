from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "012_technicians"
down_revision = "011_multi_role_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "technicians",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("user_account_id", sa.Integer(), nullable=True),
        sa.Column("first_name", sa.String(length=120), nullable=True),
        sa.Column("last_name", sa.String(length=120), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("phone_normalized", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=180), nullable=True),
        sa.Column("email_normalized", sa.String(length=180), nullable=True),
        sa.Column("employment_status", sa.String(length=40), nullable=True),
        sa.Column("job_title", sa.String(length=120), nullable=True),
        sa.Column("hire_date", sa.Date(), nullable=True),
        sa.Column("hourly_cost", sa.Numeric(10, 2), nullable=True),
        sa.Column("certifications", sa.Text(), nullable=True),
        sa.Column("certification_expiration", sa.Date(), nullable=True),
        sa.Column("specialties", sa.Text(), nullable=True),
        sa.Column("driver_license_valid", sa.Boolean(), nullable=True),
        sa.Column("insurance_verified", sa.Boolean(), nullable=True),
        sa.Column("normal_availability", sa.Text(), nullable=True),
        sa.Column("safety_notes", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["user_account_id"], ["user_accounts.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("user_account_id", name="uq_technicians_user_account_id"),
    )
    op.create_index(
        "ix_technicians_owner_archived_updated",
        "technicians",
        ["owner_user_id", "is_archived", "updated_at"],
    )
    op.create_index(
        "ix_technicians_owner_name",
        "technicians",
        ["owner_user_id", "last_name", "first_name"],
    )

    op.create_table(
        "technician_time_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("technician_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("clock_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("clock_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["technician_id"], ["technicians.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_technician_time_entries_technician_created",
        "technician_time_entries",
        ["technician_id", "created_at"],
    )
    # Partial unique index: at most one open (clock_out_at IS NULL) time entry
    # per technician, enforced at the DB level so a request race can't double
    # clock a technician in.
    op.create_index(
        "ux_technician_time_entries_one_open_per_technician",
        "technician_time_entries",
        ["technician_id"],
        unique=True,
        postgresql_where=sa.text("clock_out_at IS NULL"),
        sqlite_where=sa.text("clock_out_at IS NULL"),
    )

    op.add_column(
        "work_orders",
        sa.Column("assigned_technician_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "work_orders",
        sa.Column("is_comeback", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_foreign_key(
        "fk_work_orders_assigned_technician_id",
        "work_orders",
        "technicians",
        ["assigned_technician_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_work_orders_assigned_technician",
        "work_orders",
        ["assigned_technician_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_work_orders_assigned_technician", table_name="work_orders")
    op.drop_constraint("fk_work_orders_assigned_technician_id", "work_orders", type_="foreignkey")
    op.drop_column("work_orders", "is_comeback")
    op.drop_column("work_orders", "assigned_technician_id")

    op.drop_index(
        "ux_technician_time_entries_one_open_per_technician",
        table_name="technician_time_entries",
    )
    op.drop_index(
        "ix_technician_time_entries_technician_created",
        table_name="technician_time_entries",
    )
    op.drop_table("technician_time_entries")

    op.drop_index("ix_technicians_owner_name", table_name="technicians")
    op.drop_index("ix_technicians_owner_archived_updated", table_name="technicians")
    op.drop_table("technicians")
