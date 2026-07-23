from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "038_intake_vehicle_draft"
down_revision = "037_job_compilations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Customer-optional intake bridge (/goal Priority 2): let an intake request
    hold structured, VIN-decodable vehicle data before any customer or canonical
    `vehicles` row exists.

    Adds seven nullable columns to `intake_requests` -- `vehicle_vin`,
    `vehicle_year`, `vehicle_make`, `vehicle_model`, `vehicle_trim`,
    `vehicle_engine`, `vehicle_drivetrain`. This deliberately does NOT make
    `vehicles.customer_id` nullable: the canonical vehicle still requires a
    customer. Instead the *draft* (`intake_requests`) carries the identified
    vehicle until conversion atomically creates (or attaches) a customer and the
    canonical vehicle. Every column is nullable with no server default, so all
    pre-existing intake requests are unaffected. Rollback drops the columns
    (downgrade).
    """
    op.add_column("intake_requests", sa.Column("vehicle_vin", sa.String(length=17), nullable=True))
    op.add_column("intake_requests", sa.Column("vehicle_year", sa.Integer(), nullable=True))
    op.add_column(
        "intake_requests", sa.Column("vehicle_make", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "intake_requests", sa.Column("vehicle_model", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "intake_requests", sa.Column("vehicle_trim", sa.String(length=120), nullable=True)
    )
    op.add_column(
        "intake_requests", sa.Column("vehicle_engine", sa.String(length=120), nullable=True)
    )
    op.add_column(
        "intake_requests", sa.Column("vehicle_drivetrain", sa.String(length=80), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("intake_requests", "vehicle_drivetrain")
    op.drop_column("intake_requests", "vehicle_engine")
    op.drop_column("intake_requests", "vehicle_trim")
    op.drop_column("intake_requests", "vehicle_model")
    op.drop_column("intake_requests", "vehicle_make")
    op.drop_column("intake_requests", "vehicle_year")
    op.drop_column("intake_requests", "vehicle_vin")
