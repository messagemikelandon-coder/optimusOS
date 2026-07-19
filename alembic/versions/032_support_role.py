from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "032_support_role"
down_revision = "031_subscription_billing"
branch_labels = None
depends_on = None


def _replace_user_role_constraint(allowed_roles: str) -> None:
    """Mirrors migration 028's own helper (not shared/exported -- it is a
    local, one-off DDL helper there too) for widening/narrowing
    `ck_user_accounts_role` across both SQLite (test suite) and Postgres."""
    connection = op.get_bind()
    condition = f"role IN ({allowed_roles})"
    if connection.dialect.name == "sqlite":
        with op.batch_alter_table("user_accounts") as batch_op:
            batch_op.drop_constraint("ck_user_accounts_role", type_="check")
            batch_op.create_check_constraint("ck_user_accounts_role", condition)
        return
    op.drop_constraint("ck_user_accounts_role", "user_accounts", type_="check")
    op.create_check_constraint("ck_user_accounts_role", "user_accounts", condition)


def upgrade() -> None:
    """/goal Phase 8: adds `support` as a fourth `UserAccount.role` value for
    a platform-side, read-only operator role (see app/support_store.py).
    Deliberately does NOT touch `shop_memberships`/`shop_invitations` --
    a support account has no Shop membership at all, by design, since it
    is not scoped to any single shop."""
    _replace_user_role_constraint("'owner', 'manager', 'technician', 'support'")


def downgrade() -> None:
    connection = op.get_bind()
    support_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM user_accounts WHERE role = 'support'")
    ).scalar()
    if support_count:
        raise RuntimeError("Cannot downgrade support role while support accounts exist.")
    _replace_user_role_constraint("'owner', 'manager', 'technician'")
