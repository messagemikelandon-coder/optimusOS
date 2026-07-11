from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "011_multi_role_auth"
down_revision = "010_notifications_square"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_accounts",
        sa.Column("shop_owner_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_user_accounts_shop_owner_id",
        "user_accounts",
        "user_accounts",
        ["shop_owner_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_user_accounts_shop_owner_id",
        "user_accounts",
        ["shop_owner_id"],
    )
    op.create_check_constraint(
        "ck_user_accounts_role",
        "user_accounts",
        "role IN ('owner', 'technician')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_user_accounts_role", "user_accounts", type_="check")
    op.drop_index("ix_user_accounts_shop_owner_id", table_name="user_accounts")
    op.drop_constraint("fk_user_accounts_shop_owner_id", "user_accounts", type_="foreignkey")
    op.drop_column("user_accounts", "shop_owner_id")
