#!/usr/bin/env python3
"""Pre-flight check for /goal Phase 3 slice 6 (constrain shop_id to NOT
NULL). Reports how many rows in each of the 30 business tables still have
shop_id = NULL, and exits non-zero if any do.

Migration 025 (which adds the NOT NULL constraint) runs this same check
itself before altering any column, so this script is not the only
safety net -- but it's meant to be run manually against a real
staging/production database *before* attempting that migration, since a
clear, actionable report ahead of time beats discovering the problem via
a failed migration mid-deploy.

Usage:
    env UV_CACHE_DIR=/tmp/uv-cache uv run python scripts/check_shop_id_orphans.py
"""

from __future__ import annotations

from sqlalchemy import text

from app.config import get_settings
from app.db import build_engine

TABLES = (
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


def orphan_counts(connection) -> dict[str, int]:  # type: ignore[no-untyped-def]
    counts: dict[str, int] = {}
    for table in TABLES:
        count = connection.execute(
            text(f"SELECT count(*) FROM {table} WHERE shop_id IS NULL")
        ).scalar_one()
        if count:
            counts[table] = count
    return counts


def main() -> int:
    settings = get_settings()
    engine = build_engine(settings.database_url)
    with engine.connect() as connection:
        counts = orphan_counts(connection)
    engine.dispose()

    if not counts:
        print("No orphan shop_id rows found across all 30 business tables. Safe to proceed.")
        return 0

    print("Found orphan shop_id = NULL rows -- NOT safe to add a NOT NULL constraint yet:")
    for table, count in counts.items():
        print(f"  {table}: {count} row(s)")
    print(
        "\nInvestigate each row's owner_user_id -- it likely has no active owner-role "
        "ShopMembership (see alembic/versions/024_backfill_shop_id.py's own backfill logic "
        "for the exact join). Do not run migration 025 until this list is empty."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
