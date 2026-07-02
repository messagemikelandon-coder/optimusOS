from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "006_estimate_approvals"
down_revision = "005_vehicles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "estimates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("estimate_number", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("current_revision_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("approved_revision_number", sa.Integer(), nullable=True),
        sa.Column("estimate_total", sa.Float(), nullable=True),
        sa.Column("payment_option_selected", sa.String(length=40), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "status IN ("
            "'draft', 'ready', 'awaiting_approval', 'approved', 'declined', "
            "'expired', 'superseded', 'archived'"
            ")",
            name="ck_estimates_status",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("estimate_number", name="uq_estimates_estimate_number"),
    )
    op.create_index(
        "ix_estimates_owner_status_updated",
        "estimates",
        ["owner_user_id", "status", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_estimates_owner_customer_updated",
        "estimates",
        ["owner_user_id", "customer_id", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_estimates_owner_vehicle_updated",
        "estimates",
        ["owner_user_id", "vehicle_id", "updated_at"],
        unique=False,
    )

    op.create_table(
        "estimate_revisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("estimate_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("customer_snapshot", sa.JSON(), nullable=False),
        sa.Column("vehicle_snapshot", sa.JSON(), nullable=False),
        sa.Column("estimate_request_payload", sa.JSON(), nullable=False),
        sa.Column("estimate_response_payload", sa.JSON(), nullable=False),
        sa.Column("terms_text", sa.Text(), nullable=False),
        sa.Column("payment_options_payload", sa.JSON(), nullable=False),
        sa.Column("approval_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["estimate_id"], ["estimates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "estimate_id",
            "revision_number",
            name="uq_estimate_revisions_estimate_revision",
        ),
    )
    op.create_index(
        "ix_estimate_revisions_owner_estimate_revision",
        "estimate_revisions",
        ["owner_user_id", "estimate_id", "revision_number"],
        unique=False,
    )

    op.create_table(
        "estimate_approval_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("estimate_id", sa.Integer(), nullable=False),
        sa.Column("estimate_revision_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), nullable=False),
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
        sa.CheckConstraint(
            "status IN ('active', 'used', 'expired', 'revoked')",
            name="ck_estimate_approval_requests_status",
        ),
        sa.ForeignKeyConstraint(["estimate_id"], ["estimates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["estimate_revision_id"],
            ["estimate_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["user_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token_hash", name="uq_estimate_approval_requests_token_hash"),
    )
    op.create_index(
        "ix_estimate_approval_requests_estimate_status",
        "estimate_approval_requests",
        ["estimate_id", "status", "expires_at"],
        unique=False,
    )

    op.create_table(
        "estimate_approval_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("estimate_id", sa.Integer(), nullable=False),
        sa.Column("estimate_revision_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("approval_request_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_name", sa.String(length=160), nullable=True),
        sa.Column("approval_method", sa.String(length=80), nullable=True),
        sa.Column("approval_evidence", sa.Text(), nullable=True),
        sa.Column("accepted_terms", sa.Boolean(), nullable=True),
        sa.Column("payment_option", sa.String(length=40), nullable=True),
        sa.Column("payment_plan_acknowledged", sa.Boolean(), nullable=True),
        sa.Column("decline_reason", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "event_type IN ("
            "'sent', 'approved', 'declined', 'expired', 'superseded', 'archived', 'internal_recorded'"
            ")",
            name="ck_estimate_approval_events_type",
        ),
        sa.ForeignKeyConstraint(["estimate_id"], ["estimates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["estimate_revision_id"],
            ["estimate_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["approval_request_id"],
            ["estimate_approval_requests.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user_accounts.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_estimate_approval_events_estimate_created",
        "estimate_approval_events",
        ["estimate_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_estimate_approval_events_estimate_created", table_name="estimate_approval_events")
    op.drop_table("estimate_approval_events")
    op.drop_index("ix_estimate_approval_requests_estimate_status", table_name="estimate_approval_requests")
    op.drop_table("estimate_approval_requests")
    op.drop_index("ix_estimate_revisions_owner_estimate_revision", table_name="estimate_revisions")
    op.drop_table("estimate_revisions")
    op.drop_index("ix_estimates_owner_vehicle_updated", table_name="estimates")
    op.drop_index("ix_estimates_owner_customer_updated", table_name="estimates")
    op.drop_index("ix_estimates_owner_status_updated", table_name="estimates")
    op.drop_table("estimates")
