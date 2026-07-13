from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "017_synthetic_test_accounts"
down_revision = "016_scheduling"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_accounts",
        sa.Column(
            "is_synthetic_test_account",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.create_index(
        "ix_user_accounts_is_synthetic_test_account",
        "user_accounts",
        ["is_synthetic_test_account"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_accounts_is_synthetic_test_account", table_name="user_accounts")
    op.drop_column("user_accounts", "is_synthetic_test_account")
