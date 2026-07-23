from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "039_job_compilation_release"
down_revision = "038_intake_vehicle_draft"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Canonical release bridge (/goal): record the estimate a job compilation
    was released into.

    Adds three columns to `job_compilations` -- `released_estimate_id` (nullable
    FK to `estimates`, SET NULL so deleting an estimate never cascades away the
    compilation/audit trail), `released_at`, and `released_by_user_id` -- and
    widens the `job_compilation_events` type CHECK to allow the new `released`
    event. The pre-existing `released` boolean column (migration 037) now becomes
    load-bearing. Additive and reversible; no existing row or route is affected.
    """
    op.add_column(
        "job_compilations",
        sa.Column(
            "released_estimate_id",
            sa.Integer(),
            sa.ForeignKey("estimates.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "job_compilations", sa.Column("released_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "job_compilations",
        sa.Column(
            "released_by_user_id",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.drop_constraint("ck_job_compilation_events_type", "job_compilation_events", type_="check")
    op.create_check_constraint(
        "ck_job_compilation_events_type",
        "job_compilation_events",
        "event_type IN ('compiled', 'recompiled', 'superseded', 'released')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_job_compilation_events_type", "job_compilation_events", type_="check")
    op.create_check_constraint(
        "ck_job_compilation_events_type",
        "job_compilation_events",
        "event_type IN ('compiled', 'recompiled', 'superseded')",
    )
    op.drop_column("job_compilations", "released_by_user_id")
    op.drop_column("job_compilations", "released_at")
    op.drop_column("job_compilations", "released_estimate_id")
