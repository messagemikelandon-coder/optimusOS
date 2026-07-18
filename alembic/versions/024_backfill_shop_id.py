from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "024_backfill_shop_id"
down_revision = "023_shop_id_nullable_columns"
branch_labels = None
depends_on = None

_TABLES = (
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


def upgrade() -> None:
    """Backfills the real `shop_id` value onto every existing business-table
    row, via each row's own `owner_user_id` -> that owner's active
    `ShopMembership` -> `shop_id` (/goal Phase 3 slice 3). Still no NOT NULL
    constraint and no store-module query changes -- every existing query
    keeps scoping by `owner_user_id`/`effective_owner_id` exactly as
    before. Idempotent (`WHERE t.shop_id IS NULL`) and safe to re-run.
    Any row whose `owner_user_id` has no matching active owner
    `ShopMembership` is left NULL and reported via a warning rather than
    failing the migration or fabricating a shop assignment -- investigate
    before the later constrain/cutover slices if any are reported.
    """
    # Table names below are interpolated into raw SQL, but every one comes
    # exclusively from the hardcoded `_TABLES` tuple above (never from user
    # input, a request, or any other runtime-controlled value), so this is
    # not a SQL-injection risk -- equivalent to writing 30 literal UPDATE
    # statements by hand, just generated without copy-paste drift.
    connection = op.get_bind()
    for table in _TABLES:
        result = connection.execute(
            sa.text(
                f"""
                UPDATE {table} AS t
                SET shop_id = sm.shop_id
                FROM shop_memberships AS sm
                WHERE sm.user_account_id = t.owner_user_id
                  AND sm.role = 'owner'
                  AND sm.is_active = true
                  AND t.shop_id IS NULL
                """
            )
        )
        print(f"Backfilled shop_id for {result.rowcount} row(s) in {table}.")

    for table in _TABLES:
        unmatched_count = connection.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE shop_id IS NULL")
        ).scalar_one()
        if unmatched_count:
            print(
                f"WARNING: {unmatched_count} row(s) in {table} have no matching active owner "
                "ShopMembership and were left with shop_id = NULL -- investigate before the "
                "later NOT NULL/cutover slices."
            )


def downgrade() -> None:
    """Reverses the backfill by setting `shop_id` back to NULL on every
    business table -- the column itself and its FK/index (added in
    migration 023) are left in place; only the data is undone here.
    """
    connection = op.get_bind()
    for table in reversed(_TABLES):
        connection.execute(sa.text(f"UPDATE {table} SET shop_id = NULL"))
