from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "025_shop_id_not_null"
down_revision = "024_backfill_shop_id"
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
    """Constrains `shop_id` to NOT NULL on all 30 business tables (/goal
    Phase 3 slice 6) -- safe only because slice 3 backfilled every
    pre-existing row and slice 4 made every store module set `shop_id` on
    every new row. Refuses to proceed (raising, not silently skipping or
    fabricating a value) if any row is still unmatched, mirroring
    scripts/check_shop_id_orphans.py's own check so this migration is
    self-defending even if that script wasn't run first.
    """
    connection = op.get_bind()
    orphans: dict[str, int] = {}
    for table in _TABLES:
        count = connection.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE shop_id IS NULL")
        ).scalar_one()
        if count:
            orphans[table] = count
    if orphans:
        details = ", ".join(f"{table}={count}" for table, count in orphans.items())
        raise RuntimeError(
            "Refusing to add NOT NULL constraints -- found orphan shop_id rows: "
            f"{details}. Run scripts/check_shop_id_orphans.py, investigate each "
            "row's owner_user_id (see migration 024's backfill join), and resolve "
            "before retrying this migration."
        )

    op.alter_column("customers", "shop_id", nullable=False)
    op.alter_column("vehicles", "shop_id", nullable=False)
    op.alter_column("estimates", "shop_id", nullable=False)
    op.alter_column("estimate_revisions", "shop_id", nullable=False)
    op.alter_column("estimate_approval_requests", "shop_id", nullable=False)
    op.alter_column("estimate_approval_events", "shop_id", nullable=False)
    op.alter_column("technicians", "shop_id", nullable=False)
    op.alter_column("technician_time_entries", "shop_id", nullable=False)
    op.alter_column("work_orders", "shop_id", nullable=False)
    op.alter_column("work_order_status_events", "shop_id", nullable=False)
    op.alter_column("work_order_notes", "shop_id", nullable=False)
    op.alter_column("invoices", "shop_id", nullable=False)
    op.alter_column("invoice_payments", "shop_id", nullable=False)
    op.alter_column("payment_schedules", "shop_id", nullable=False)
    op.alter_column("notifications", "shop_id", nullable=False)
    op.alter_column("vendors", "shop_id", nullable=False)
    op.alter_column("parts", "shop_id", nullable=False)
    op.alter_column("purchase_orders", "shop_id", nullable=False)
    op.alter_column("purchase_order_receipts", "shop_id", nullable=False)
    op.alter_column("part_allocations", "shop_id", nullable=False)
    op.alter_column("part_allocation_events", "shop_id", nullable=False)
    op.alter_column("intake_requests", "shop_id", nullable=False)
    op.alter_column("diagnostic_findings", "shop_id", nullable=False)
    op.alter_column("diagnostic_finding_events", "shop_id", nullable=False)
    op.alter_column("inspections", "shop_id", nullable=False)
    op.alter_column("inspection_events", "shop_id", nullable=False)
    op.alter_column("bays", "shop_id", nullable=False)
    op.alter_column("working_hours", "shop_id", nullable=False)
    op.alter_column("schedule_blocks", "shop_id", nullable=False)
    op.alter_column("appointments", "shop_id", nullable=False)


def downgrade() -> None:
    op.alter_column("appointments", "shop_id", nullable=True)
    op.alter_column("schedule_blocks", "shop_id", nullable=True)
    op.alter_column("working_hours", "shop_id", nullable=True)
    op.alter_column("bays", "shop_id", nullable=True)
    op.alter_column("inspection_events", "shop_id", nullable=True)
    op.alter_column("inspections", "shop_id", nullable=True)
    op.alter_column("diagnostic_finding_events", "shop_id", nullable=True)
    op.alter_column("diagnostic_findings", "shop_id", nullable=True)
    op.alter_column("intake_requests", "shop_id", nullable=True)
    op.alter_column("part_allocation_events", "shop_id", nullable=True)
    op.alter_column("part_allocations", "shop_id", nullable=True)
    op.alter_column("purchase_order_receipts", "shop_id", nullable=True)
    op.alter_column("purchase_orders", "shop_id", nullable=True)
    op.alter_column("parts", "shop_id", nullable=True)
    op.alter_column("vendors", "shop_id", nullable=True)
    op.alter_column("notifications", "shop_id", nullable=True)
    op.alter_column("payment_schedules", "shop_id", nullable=True)
    op.alter_column("invoice_payments", "shop_id", nullable=True)
    op.alter_column("invoices", "shop_id", nullable=True)
    op.alter_column("work_order_notes", "shop_id", nullable=True)
    op.alter_column("work_order_status_events", "shop_id", nullable=True)
    op.alter_column("work_orders", "shop_id", nullable=True)
    op.alter_column("technician_time_entries", "shop_id", nullable=True)
    op.alter_column("technicians", "shop_id", nullable=True)
    op.alter_column("estimate_approval_events", "shop_id", nullable=True)
    op.alter_column("estimate_approval_requests", "shop_id", nullable=True)
    op.alter_column("estimate_revisions", "shop_id", nullable=True)
    op.alter_column("estimates", "shop_id", nullable=True)
    op.alter_column("vehicles", "shop_id", nullable=True)
    op.alter_column("customers", "shop_id", nullable=True)
