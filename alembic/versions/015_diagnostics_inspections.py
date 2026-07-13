from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "015_diagnostics_inspections"
down_revision = "014_intake_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "diagnostic_findings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("work_order_id", sa.Integer(), nullable=True),
        sa.Column("technician_id", sa.Integer(), nullable=True),
        sa.Column("codes", sa.Text(), nullable=True),
        sa.Column("symptoms", sa.Text(), nullable=False),
        sa.Column("tests_performed", sa.Text(), nullable=True),
        sa.Column("conclusion", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["technician_id"], ["technicians.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_diagnostic_findings_owner_vehicle_updated",
        "diagnostic_findings",
        ["owner_user_id", "vehicle_id", "updated_at"],
    )
    op.create_index("ix_diagnostic_findings_work_order", "diagnostic_findings", ["work_order_id"])

    op.create_table(
        "inspections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("work_order_id", sa.Integer(), nullable=True),
        sa.Column("technician_id", sa.Integer(), nullable=True),
        sa.Column("inspection_type", sa.String(length=120), nullable=True),
        sa.Column("items", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("overall_notes", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["work_order_id"], ["work_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["technician_id"], ["technicians.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_inspections_owner_vehicle_updated",
        "inspections",
        ["owner_user_id", "vehicle_id", "updated_at"],
    )
    op.create_index("ix_inspections_work_order", "inspections", ["work_order_id"])


def downgrade() -> None:
    op.drop_index("ix_inspections_work_order", table_name="inspections")
    op.drop_index("ix_inspections_owner_vehicle_updated", table_name="inspections")
    op.drop_table("inspections")

    op.drop_index("ix_diagnostic_findings_work_order", table_name="diagnostic_findings")
    op.drop_index("ix_diagnostic_findings_owner_vehicle_updated", table_name="diagnostic_findings")
    op.drop_table("diagnostic_findings")
