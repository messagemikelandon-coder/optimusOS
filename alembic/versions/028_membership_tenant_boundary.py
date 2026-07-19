from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "028_membership_tenant_boundary"
down_revision = "027_email_verification"
branch_labels = None
depends_on = None

_BUSINESS_TABLES = (
    "customers",
    "vehicles",
    "estimates",
    "estimate_revisions",
    "estimate_approval_requests",
    "estimate_approval_events",
    "technicians",
    "technician_time_entries",
    "work_orders",
    "work_order_status_events",
    "work_order_notes",
    "invoices",
    "invoice_payments",
    "payment_schedules",
    "notifications",
    "vendors",
    "parts",
    "purchase_orders",
    "purchase_order_receipts",
    "part_allocations",
    "part_allocation_events",
    "intake_requests",
    "diagnostic_findings",
    "diagnostic_finding_events",
    "inspections",
    "inspection_events",
    "bays",
    "working_hours",
    "schedule_blocks",
    "appointments",
)


def _replace_user_role_constraint(allowed_roles: str) -> None:
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
    """Make active Shop membership the account and tenant authority.

    Existing technician logins predate memberships and are backfilled through
    their compatibility `shop_owner_id` pointer. Manager becomes a first-class
    account role. Because sessions do not yet contain a shop selector, one
    active membership per account is enforced for every role.
    """
    _replace_user_role_constraint("'owner', 'manager', 'technician'")

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "INSERT INTO shop_memberships (shop_id, user_account_id, role, is_active) "
            "SELECT owner_membership.shop_id, technician.id, 'technician', technician.is_active "
            "FROM user_accounts AS technician "
            "JOIN shop_memberships AS owner_membership "
            "  ON owner_membership.user_account_id = technician.shop_owner_id "
            " AND owner_membership.role = 'owner' "
            " AND owner_membership.is_active = true "
            "LEFT JOIN shop_memberships AS existing "
            "  ON existing.user_account_id = technician.id "
            "WHERE technician.role = 'technician' "
            "  AND technician.is_synthetic_test_account = false "
            "  AND existing.id IS NULL"
        )
    )
    # Migration 022 created active memberships for every pre-existing real
    # technician, including accounts that had already been offboarded. Align
    # those historical rows with account activity before enforcing the new
    # boundary.
    connection.execute(
        sa.text(
            "UPDATE shop_memberships AS membership SET is_active = false "
            "WHERE membership.is_active = true AND EXISTS ("
            "  SELECT 1 FROM user_accounts AS account "
            "  WHERE account.id = membership.user_account_id "
            "    AND account.is_active = false"
            ")"
        )
    )

    invalid_membership_count = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM user_accounts AS account "
            "WHERE account.is_synthetic_test_account = false "
            "  AND account.role IN ('owner', 'manager', 'technician') "
            "  AND ((account.is_active = true "
            "        AND (SELECT COUNT(*) FROM shop_memberships AS membership "
            "             WHERE membership.user_account_id = account.id "
            "               AND membership.role = account.role "
            "               AND membership.is_active = true) <> 1) "
            "       OR (account.is_active = false "
            "           AND (SELECT COUNT(*) FROM shop_memberships AS membership "
            "                WHERE membership.user_account_id = account.id "
            "                  AND membership.is_active = true) <> 0))"
        )
    )
    if invalid_membership_count:
        raise RuntimeError(
            "Cannot enable the membership tenant boundary: "
            f"{invalid_membership_count} real account(s) have membership state that does not "
            "match account activity and role."
        )

    conflicting_active_count = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM ("
            "  SELECT user_account_id FROM shop_memberships "
            "  WHERE is_active = true GROUP BY user_account_id HAVING COUNT(*) > 1"
            ") AS conflicts"
        )
    )
    if conflicting_active_count:
        raise RuntimeError(
            "Cannot enable the membership tenant boundary: "
            f"{conflicting_active_count} account(s) have multiple active memberships."
        )

    invalid_active_membership_count = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM shop_memberships AS membership "
            "JOIN user_accounts AS account ON account.id = membership.user_account_id "
            "WHERE membership.is_active = true "
            "  AND (account.is_active = false OR account.role <> membership.role)"
        )
    )
    if invalid_active_membership_count:
        raise RuntimeError(
            "Cannot enable the membership tenant boundary: "
            f"{invalid_active_membership_count} active membership(s) belong to an inactive or "
            "role-mismatched account."
        )

    technician_profile_mismatch_count = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM technicians AS technician "
            "JOIN user_accounts AS account ON account.id = technician.user_account_id "
            "JOIN shop_memberships AS membership "
            "  ON membership.user_account_id = account.id AND membership.is_active = true "
            "WHERE technician.shop_id <> membership.shop_id "
            "   OR account.role <> 'technician' "
            "   OR membership.role <> 'technician'"
        )
    )
    if technician_profile_mismatch_count:
        raise RuntimeError(
            "Cannot enable the membership tenant boundary: "
            f"{technician_profile_mismatch_count} technician profile(s) disagree with their "
            "account membership."
        )

    # Repair compatibility pointers from membership before they can be used
    # by legacy FKs or future writes. The earliest active owner membership is
    # the stable compatibility owner when a shop has multiple owners.
    connection.execute(
        sa.text(
            "UPDATE user_accounts AS account "
            "SET shop_owner_id = ("
            "  SELECT owner_membership.user_account_id "
            "  FROM shop_memberships AS own_membership "
            "  JOIN shop_memberships AS owner_membership "
            "    ON owner_membership.shop_id = own_membership.shop_id "
            "   AND owner_membership.role = 'owner' "
            "   AND owner_membership.is_active = true "
            "  JOIN user_accounts AS owner_account "
            "    ON owner_account.id = owner_membership.user_account_id "
            "   AND owner_account.role = 'owner' "
            "   AND owner_account.is_active = true "
            "  WHERE own_membership.user_account_id = account.id "
            "    AND own_membership.is_active = true "
            "  ORDER BY owner_membership.id LIMIT 1"
            ") WHERE account.role IN ('manager', 'technician') "
            "AND EXISTS (SELECT 1 FROM shop_memberships AS active_membership "
            "            WHERE active_membership.user_account_id = account.id "
            "              AND active_membership.is_active = true)"
        )
    )

    for table in _BUSINESS_TABLES:
        missing_owner_count = connection.scalar(
            sa.text(
                f"SELECT COUNT(*) FROM {table} AS record WHERE NOT EXISTS ("
                "  SELECT 1 FROM shop_memberships AS owner_membership "
                "  JOIN user_accounts AS owner_account "
                "    ON owner_account.id = owner_membership.user_account_id "
                "  WHERE owner_membership.shop_id = record.shop_id "
                "    AND owner_membership.role = 'owner' "
                "    AND owner_membership.is_active = true"
                "    AND owner_account.role = 'owner' "
                "    AND owner_account.is_active = true"
                ")"
            )
        )
        if missing_owner_count:
            raise RuntimeError(
                f"Cannot canonicalize {table}: {missing_owner_count} row(s) belong to a Shop "
                "without an active owner membership."
            )
        connection.execute(
            sa.text(
                f"UPDATE {table} AS record SET owner_user_id = ("
                "  SELECT owner_membership.user_account_id "
                "  FROM shop_memberships AS owner_membership "
                "  JOIN user_accounts AS owner_account "
                "    ON owner_account.id = owner_membership.user_account_id "
                "  WHERE owner_membership.shop_id = record.shop_id "
                "    AND owner_membership.role = 'owner' "
                "    AND owner_membership.is_active = true "
                "    AND owner_account.role = 'owner' "
                "    AND owner_account.is_active = true "
                "  ORDER BY owner_membership.id LIMIT 1"
                ")"
            )
        )

    op.drop_index("uq_shop_memberships_one_active_owner_per_user", table_name="shop_memberships")
    op.create_index(
        "uq_shop_memberships_one_active_per_user",
        "shop_memberships",
        ["user_account_id"],
        unique=True,
        postgresql_where=sa.text("is_active = true"),
        sqlite_where=sa.text("is_active = 1"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    manager_count = connection.scalar(
        sa.text("SELECT COUNT(*) FROM user_accounts WHERE role = 'manager'")
    )
    if manager_count:
        raise RuntimeError(
            "Cannot downgrade membership tenant boundary while manager accounts exist."
        )

    op.drop_index("uq_shop_memberships_one_active_per_user", table_name="shop_memberships")
    op.create_index(
        "uq_shop_memberships_one_active_owner_per_user",
        "shop_memberships",
        ["user_account_id"],
        unique=True,
        postgresql_where=sa.text("role = 'owner' AND is_active = true"),
        sqlite_where=sa.text("role = 'owner' AND is_active = 1"),
    )
    _replace_user_role_constraint("'owner', 'technician'")
