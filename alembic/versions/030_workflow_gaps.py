from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "030_workflow_gaps"
down_revision = "029_account_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workflow_gaps",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "shop_id",
            sa.Integer(),
            sa.ForeignKey("shops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_account_id",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "updated_by_user_account_id",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="SET NULL"),
        ),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("workflow_area", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("workaround", sa.Text()),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "first_reported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_reported_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_workflow_gaps_severity",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'investigating', 'planned', 'resolved', 'wont_fix')",
            name="ck_workflow_gaps_status",
        ),
        sa.CheckConstraint("occurrence_count > 0", name="ck_workflow_gaps_occurrence_count"),
    )
    op.create_index(
        "ix_workflow_gaps_shop_status_updated",
        "workflow_gaps",
        ["shop_id", "status", "updated_at"],
    )
    op.create_index(
        "ix_workflow_gaps_shop_severity",
        "workflow_gaps",
        ["shop_id", "severity"],
    )
    op.create_table(
        "workflow_gap_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workflow_gap_id",
            sa.Integer(),
            sa.ForeignKey("workflow_gaps.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "shop_id",
            sa.Integer(),
            sa.ForeignKey("shops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_account_id",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="SET NULL"),
        ),
        sa.Column("actor_name", sa.String(length=200)),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("from_status", sa.String(length=20)),
        sa.Column("to_status", sa.String(length=20)),
        sa.Column("event_metadata", sa.JSON()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "event_type IN ('created', 'updated', 'status_changed', 'occurrence_recorded')",
            name="ck_workflow_gap_events_type",
        ),
    )
    op.create_index(
        "ix_workflow_gap_events_gap_created",
        "workflow_gap_events",
        ["workflow_gap_id", "created_at"],
    )
    op.create_index(
        "ix_workflow_gap_events_shop_id",
        "workflow_gap_events",
        ["shop_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_workflow_gap_events_shop_id", table_name="workflow_gap_events")
    op.drop_index("ix_workflow_gap_events_gap_created", table_name="workflow_gap_events")
    op.drop_table("workflow_gap_events")
    op.drop_index("ix_workflow_gaps_shop_severity", table_name="workflow_gaps")
    op.drop_index("ix_workflow_gaps_shop_status_updated", table_name="workflow_gaps")
    op.drop_table("workflow_gaps")
