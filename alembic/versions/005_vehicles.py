from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "005_vehicles"
down_revision = "004_customers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vehicles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("vin", sa.String(length=17), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("make", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("trim", sa.String(length=120), nullable=True),
        sa.Column("engine", sa.String(length=120), nullable=True),
        sa.Column("drivetrain", sa.String(length=80), nullable=True),
        sa.Column("transmission", sa.String(length=120), nullable=True),
        sa.Column("license_plate", sa.String(length=32), nullable=True),
        sa.Column("license_plate_state", sa.String(length=40), nullable=True),
        sa.Column("license_plate_normalized", sa.String(length=32), nullable=True),
        sa.Column("color", sa.String(length=80), nullable=True),
        sa.Column("current_mileage", sa.Integer(), nullable=True),
        sa.Column("fleet_unit_number", sa.String(length=80), nullable=True),
        sa.Column("internal_notes", sa.Text(), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_vehicles_owner_archived_updated",
        "vehicles",
        ["owner_user_id", "is_archived", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_vehicles_owner_customer_archived_updated",
        "vehicles",
        ["owner_user_id", "customer_id", "is_archived", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_vehicles_owner_year_make_model",
        "vehicles",
        ["owner_user_id", "year", "make", "model"],
        unique=False,
    )
    op.create_index(
        "ix_vehicles_owner_license_plate",
        "vehicles",
        ["owner_user_id", "license_plate_normalized"],
        unique=False,
    )
    op.create_index("ix_vehicles_owner_vin", "vehicles", ["owner_user_id", "vin"], unique=False)
    op.create_index(
        "uq_vehicles_owner_active_vin",
        "vehicles",
        ["owner_user_id", "vin"],
        unique=True,
        postgresql_where=sa.text("vin IS NOT NULL AND is_archived = false"),
        sqlite_where=sa.text("vin IS NOT NULL AND is_archived = 0"),
    )


def downgrade() -> None:
    op.drop_index("uq_vehicles_owner_active_vin", table_name="vehicles")
    op.drop_index("ix_vehicles_owner_vin", table_name="vehicles")
    op.drop_index("ix_vehicles_owner_license_plate", table_name="vehicles")
    op.drop_index("ix_vehicles_owner_year_make_model", table_name="vehicles")
    op.drop_index("ix_vehicles_owner_customer_archived_updated", table_name="vehicles")
    op.drop_index("ix_vehicles_owner_archived_updated", table_name="vehicles")
    op.drop_table("vehicles")
