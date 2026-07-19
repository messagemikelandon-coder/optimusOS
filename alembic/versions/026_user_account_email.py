from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "026_user_account_email"
down_revision = "025_shop_id_not_null"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Adds an optional `email`/`email_normalized` pair to `user_accounts`
    (/goal Phase 4 self-service shop signup). Nullable: the bootstrapped
    owner and every technician account predate this column and have no
    email at all -- nothing fabricates one for them. A partial unique
    index enforces uniqueness only where an email is actually present, so
    NULL rows (the pre-existing majority) never collide with each other.
    """
    op.add_column("user_accounts", sa.Column("email", sa.String(length=180), nullable=True))
    op.add_column(
        "user_accounts", sa.Column("email_normalized", sa.String(length=180), nullable=True)
    )
    op.create_index(
        "uq_user_accounts_email_normalized",
        "user_accounts",
        ["email_normalized"],
        unique=True,
        postgresql_where=sa.text("email_normalized IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_user_accounts_email_normalized", table_name="user_accounts")
    op.drop_column("user_accounts", "email_normalized")
    op.drop_column("user_accounts", "email")
