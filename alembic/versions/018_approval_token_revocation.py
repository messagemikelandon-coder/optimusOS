from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "018_approval_token_revocation"
down_revision = "017_synthetic_test_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "estimate_approval_requests",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "estimate_approval_requests",
        sa.Column("revoked_by_user_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_estimate_approval_requests_revoked_by_user_id",
        "estimate_approval_requests",
        "user_accounts",
        ["revoked_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.drop_constraint(
        "ck_estimate_approval_events_type", "estimate_approval_events", type_="check"
    )
    op.create_check_constraint(
        "ck_estimate_approval_events_type",
        "estimate_approval_events",
        "event_type IN ("
        "'sent', 'approved', 'declined', 'expired', 'superseded', 'archived', "
        "'internal_recorded', 'revoked'"
        ")",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_estimate_approval_events_type", "estimate_approval_events", type_="check"
    )
    op.create_check_constraint(
        "ck_estimate_approval_events_type",
        "estimate_approval_events",
        "event_type IN ("
        "'sent', 'approved', 'declined', 'expired', 'superseded', 'archived', "
        "'internal_recorded'"
        ")",
    )
    op.drop_constraint(
        "fk_estimate_approval_requests_revoked_by_user_id",
        "estimate_approval_requests",
        type_="foreignkey",
    )
    op.drop_column("estimate_approval_requests", "revoked_by_user_id")
    op.drop_column("estimate_approval_requests", "revoked_at")
