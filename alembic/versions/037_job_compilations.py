from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "037_job_compilations"
down_revision = "036_diagnostic_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Deterministic Job Compiler (/goal Priority 1): persist the compilation of
    an approved diagnostic finding into a priced draft job.

    Adds two tables:

    - ``job_compilations`` -- one row per compilation revision, linked to a
      ``diagnostic_findings`` row (CASCADE) and its ``vehicles`` row. Holds the
      deterministic result (labor lines, aggregated part needs, work-order task
      descriptors, reconciled totals) as JSON, the source finding's
      evidence snapshot (severity / confidence / conclusion / derived
      unverified flag), the ``content_hash`` used for idempotent recompilation,
      and a self-referencing ``superseded_by_id`` so a changed recompile
      supersedes the prior draft and points at its replacement. ``released``
      defaults false -- a compilation is always an internal draft and is never
      automatically sent to the customer, ordered, or paid.
    - ``job_compilation_events`` -- append-only audit trail
      (compiled / recompiled / superseded), actor owner or manager.

    Additive only: no existing table or column is changed, so every pre-existing
    row and route is unaffected. Rollback drops both tables (downgrade).
    """
    op.create_table(
        "job_compilations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "owner_user_id",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "shop_id",
            sa.Integer(),
            sa.ForeignKey("shops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "finding_id",
            sa.Integer(),
            sa.ForeignKey("diagnostic_findings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "vehicle_id",
            sa.Integer(),
            sa.ForeignKey("vehicles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("released", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("source_severity", sa.String(length=20), nullable=True),
        sa.Column("source_confidence", sa.String(length=20), nullable=True),
        sa.Column("source_conclusion", sa.Text(), nullable=True),
        sa.Column(
            "source_diagnosis_unverified",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("labor_rate", sa.Numeric(10, 2), nullable=False),
        sa.Column("labor_lines", sa.JSON(), nullable=False),
        sa.Column("part_lines", sa.JSON(), nullable=False),
        sa.Column("tasks", sa.JSON(), nullable=False),
        sa.Column("totals", sa.JSON(), nullable=False),
        sa.Column(
            "superseded_by_id",
            sa.Integer(),
            sa.ForeignKey("job_compilations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by_user_id",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("status IN ('draft', 'superseded')", name="ck_job_compilations_status"),
    )
    op.create_index("ix_job_compilations_shop_id", "job_compilations", ["shop_id"])
    op.create_index(
        "ix_job_compilations_finding_status", "job_compilations", ["finding_id", "status"]
    )
    op.create_index(
        "ix_job_compilations_owner_status_updated",
        "job_compilations",
        ["owner_user_id", "status", "updated_at"],
    )

    op.create_table(
        "job_compilation_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "compilation_id",
            sa.Integer(),
            sa.ForeignKey("job_compilations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_user_id",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "shop_id",
            sa.Integer(),
            sa.ForeignKey("shops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_name", sa.String(length=160), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "event_type IN ('compiled', 'recompiled', 'superseded')",
            name="ck_job_compilation_events_type",
        ),
        sa.CheckConstraint(
            "actor_type IN ('owner', 'manager')",
            name="ck_job_compilation_events_actor_type",
        ),
    )
    op.create_index(
        "ix_job_compilation_events_compilation_created",
        "job_compilation_events",
        ["compilation_id", "created_at"],
    )
    op.create_index("ix_job_compilation_events_shop_id", "job_compilation_events", ["shop_id"])


def downgrade() -> None:
    op.drop_index("ix_job_compilation_events_shop_id", table_name="job_compilation_events")
    op.drop_index(
        "ix_job_compilation_events_compilation_created", table_name="job_compilation_events"
    )
    op.drop_table("job_compilation_events")
    op.drop_index("ix_job_compilations_owner_status_updated", table_name="job_compilations")
    op.drop_index("ix_job_compilations_finding_status", table_name="job_compilations")
    op.drop_index("ix_job_compilations_shop_id", table_name="job_compilations")
    op.drop_table("job_compilations")
