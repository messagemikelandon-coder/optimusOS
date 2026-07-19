from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "033_support_impersonation"
down_revision = "032_support_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """/goal Phase 8: lets a support account "act as" a shop's owner with
    that owner's own real session (not a new parallel access-control path --
    every existing owner-gated route works unchanged), while remaining
    fully auditable. `impersonated_by_user_account_id` is set only on the
    minted owner-identity session, never on the support account's own
    session, and is cleared (SET NULL) if the support account is ever
    deleted so historical sessions are never silently misattributed."""
    op.add_column(
        "auth_sessions",
        sa.Column(
            "impersonated_by_user_account_id",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_auth_sessions_impersonated_by",
        "auth_sessions",
        ["impersonated_by_user_account_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_auth_sessions_impersonated_by", table_name="auth_sessions")
    op.drop_column("auth_sessions", "impersonated_by_user_account_id")
