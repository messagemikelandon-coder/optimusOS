from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "003_context_entries"
down_revision = "002_authentication_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "context_entries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("auth_session_id", sa.Integer(), nullable=True),
        sa.Column("project_key", sa.String(length=120), nullable=False),
        sa.Column("scope_type", sa.String(length=20), nullable=False),
        sa.Column("scope_key", sa.String(length=200), nullable=False),
        sa.Column("context_key", sa.String(length=120), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["auth_session_id"], ["auth_sessions.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "scope_type IN ('project', 'session')",
            name="ck_context_entries_scope_type",
        ),
        sa.CheckConstraint(
            "(scope_type = 'project' AND auth_session_id IS NULL) "
            "OR (scope_type = 'session' AND auth_session_id IS NOT NULL)",
            name="ck_context_entries_scope_session_match",
        ),
        sa.UniqueConstraint(
            "user_id",
            "scope_type",
            "scope_key",
            "context_key",
            name="uq_context_entries_scope_key",
        ),
    )
    op.create_index(
        "ix_context_entries_user_project",
        "context_entries",
        ["user_id", "project_key"],
        unique=False,
    )
    op.create_index("ix_context_entries_scope_key", "context_entries", ["scope_key"], unique=False)
    op.create_index(
        "ix_context_entries_updated_at",
        "context_entries",
        ["updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_context_entries_updated_at", table_name="context_entries")
    op.drop_index("ix_context_entries_scope_key", table_name="context_entries")
    op.drop_index("ix_context_entries_user_project", table_name="context_entries")
    op.drop_table("context_entries")
