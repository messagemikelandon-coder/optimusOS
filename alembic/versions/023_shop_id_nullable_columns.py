from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "023_shop_id_nullable_columns"
down_revision = "022_shop_tenant_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Adds a nullable `shop_id` FK + index to every business table (/goal
    Phase 3 slice 2). Purely additive: no NOT NULL constraint, no backfill,
    no store-module query changes -- every existing query still scopes by
    `owner_user_id`/`effective_owner_id` exactly as before. This is
    deliberately its own slice per the goal's staged migration plan
    (nullable column -> backfill -> constrain -> cutover -> cleanup), so a
    schema-only change stays reviewable independently of the higher-risk
    data-migration and query-cutover slices that follow it.
    """
    op.add_column("customers", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_customers_shop_id_shops", "customers", "shops", ["shop_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_customers_shop_id", "customers", ["shop_id"])

    op.add_column("vehicles", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_vehicles_shop_id_shops", "vehicles", "shops", ["shop_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_vehicles_shop_id", "vehicles", ["shop_id"])

    op.add_column("estimates", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_estimates_shop_id_shops", "estimates", "shops", ["shop_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_estimates_shop_id", "estimates", ["shop_id"])

    op.add_column("estimate_revisions", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_estimate_revisions_shop_id_shops",
        "estimate_revisions",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_estimate_revisions_shop_id", "estimate_revisions", ["shop_id"])

    op.add_column("estimate_approval_requests", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_estimate_approval_requests_shop_id_shops",
        "estimate_approval_requests",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_estimate_approval_requests_shop_id", "estimate_approval_requests", ["shop_id"]
    )

    op.add_column("estimate_approval_events", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_estimate_approval_events_shop_id_shops",
        "estimate_approval_events",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_estimate_approval_events_shop_id", "estimate_approval_events", ["shop_id"])

    op.add_column("technicians", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_technicians_shop_id_shops",
        "technicians",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_technicians_shop_id", "technicians", ["shop_id"])

    op.add_column("technician_time_entries", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_technician_time_entries_shop_id_shops",
        "technician_time_entries",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_technician_time_entries_shop_id", "technician_time_entries", ["shop_id"])

    op.add_column("work_orders", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_work_orders_shop_id_shops",
        "work_orders",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_work_orders_shop_id", "work_orders", ["shop_id"])

    op.add_column("work_order_status_events", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_work_order_status_events_shop_id_shops",
        "work_order_status_events",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_work_order_status_events_shop_id", "work_order_status_events", ["shop_id"])

    op.add_column("work_order_notes", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_work_order_notes_shop_id_shops",
        "work_order_notes",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_work_order_notes_shop_id", "work_order_notes", ["shop_id"])

    op.add_column("invoices", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_invoices_shop_id_shops", "invoices", "shops", ["shop_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_invoices_shop_id", "invoices", ["shop_id"])

    op.add_column("invoice_payments", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_invoice_payments_shop_id_shops",
        "invoice_payments",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_invoice_payments_shop_id", "invoice_payments", ["shop_id"])

    op.add_column("payment_schedules", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_payment_schedules_shop_id_shops",
        "payment_schedules",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_payment_schedules_shop_id", "payment_schedules", ["shop_id"])

    op.add_column("notifications", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_notifications_shop_id_shops",
        "notifications",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_notifications_shop_id", "notifications", ["shop_id"])

    op.add_column("vendors", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_vendors_shop_id_shops", "vendors", "shops", ["shop_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_vendors_shop_id", "vendors", ["shop_id"])

    op.add_column("parts", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_parts_shop_id_shops", "parts", "shops", ["shop_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_parts_shop_id", "parts", ["shop_id"])

    op.add_column("purchase_orders", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_purchase_orders_shop_id_shops",
        "purchase_orders",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_purchase_orders_shop_id", "purchase_orders", ["shop_id"])

    op.add_column("purchase_order_receipts", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_purchase_order_receipts_shop_id_shops",
        "purchase_order_receipts",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_purchase_order_receipts_shop_id", "purchase_order_receipts", ["shop_id"])

    op.add_column("part_allocations", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_part_allocations_shop_id_shops",
        "part_allocations",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_part_allocations_shop_id", "part_allocations", ["shop_id"])

    op.add_column("part_allocation_events", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_part_allocation_events_shop_id_shops",
        "part_allocation_events",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_part_allocation_events_shop_id", "part_allocation_events", ["shop_id"])

    op.add_column("intake_requests", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_intake_requests_shop_id_shops",
        "intake_requests",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_intake_requests_shop_id", "intake_requests", ["shop_id"])

    op.add_column("diagnostic_findings", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_diagnostic_findings_shop_id_shops",
        "diagnostic_findings",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_diagnostic_findings_shop_id", "diagnostic_findings", ["shop_id"])

    op.add_column("diagnostic_finding_events", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_diagnostic_finding_events_shop_id_shops",
        "diagnostic_finding_events",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_diagnostic_finding_events_shop_id", "diagnostic_finding_events", ["shop_id"]
    )

    op.add_column("inspections", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_inspections_shop_id_shops",
        "inspections",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_inspections_shop_id", "inspections", ["shop_id"])

    op.add_column("inspection_events", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_inspection_events_shop_id_shops",
        "inspection_events",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_inspection_events_shop_id", "inspection_events", ["shop_id"])

    op.add_column("bays", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_bays_shop_id_shops", "bays", "shops", ["shop_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_bays_shop_id", "bays", ["shop_id"])

    op.add_column("working_hours", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_working_hours_shop_id_shops",
        "working_hours",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_working_hours_shop_id", "working_hours", ["shop_id"])

    op.add_column("schedule_blocks", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_schedule_blocks_shop_id_shops",
        "schedule_blocks",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_schedule_blocks_shop_id", "schedule_blocks", ["shop_id"])

    op.add_column("appointments", sa.Column("shop_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_appointments_shop_id_shops",
        "appointments",
        "shops",
        ["shop_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_appointments_shop_id", "appointments", ["shop_id"])


def downgrade() -> None:
    op.drop_index("ix_appointments_shop_id", table_name="appointments")
    op.drop_constraint("fk_appointments_shop_id_shops", "appointments", type_="foreignkey")
    op.drop_column("appointments", "shop_id")

    op.drop_index("ix_schedule_blocks_shop_id", table_name="schedule_blocks")
    op.drop_constraint("fk_schedule_blocks_shop_id_shops", "schedule_blocks", type_="foreignkey")
    op.drop_column("schedule_blocks", "shop_id")

    op.drop_index("ix_working_hours_shop_id", table_name="working_hours")
    op.drop_constraint("fk_working_hours_shop_id_shops", "working_hours", type_="foreignkey")
    op.drop_column("working_hours", "shop_id")

    op.drop_index("ix_bays_shop_id", table_name="bays")
    op.drop_constraint("fk_bays_shop_id_shops", "bays", type_="foreignkey")
    op.drop_column("bays", "shop_id")

    op.drop_index("ix_inspection_events_shop_id", table_name="inspection_events")
    op.drop_constraint(
        "fk_inspection_events_shop_id_shops", "inspection_events", type_="foreignkey"
    )
    op.drop_column("inspection_events", "shop_id")

    op.drop_index("ix_inspections_shop_id", table_name="inspections")
    op.drop_constraint("fk_inspections_shop_id_shops", "inspections", type_="foreignkey")
    op.drop_column("inspections", "shop_id")

    op.drop_index("ix_diagnostic_finding_events_shop_id", table_name="diagnostic_finding_events")
    op.drop_constraint(
        "fk_diagnostic_finding_events_shop_id_shops",
        "diagnostic_finding_events",
        type_="foreignkey",
    )
    op.drop_column("diagnostic_finding_events", "shop_id")

    op.drop_index("ix_diagnostic_findings_shop_id", table_name="diagnostic_findings")
    op.drop_constraint(
        "fk_diagnostic_findings_shop_id_shops", "diagnostic_findings", type_="foreignkey"
    )
    op.drop_column("diagnostic_findings", "shop_id")

    op.drop_index("ix_intake_requests_shop_id", table_name="intake_requests")
    op.drop_constraint("fk_intake_requests_shop_id_shops", "intake_requests", type_="foreignkey")
    op.drop_column("intake_requests", "shop_id")

    op.drop_index("ix_part_allocation_events_shop_id", table_name="part_allocation_events")
    op.drop_constraint(
        "fk_part_allocation_events_shop_id_shops", "part_allocation_events", type_="foreignkey"
    )
    op.drop_column("part_allocation_events", "shop_id")

    op.drop_index("ix_part_allocations_shop_id", table_name="part_allocations")
    op.drop_constraint("fk_part_allocations_shop_id_shops", "part_allocations", type_="foreignkey")
    op.drop_column("part_allocations", "shop_id")

    op.drop_index("ix_purchase_order_receipts_shop_id", table_name="purchase_order_receipts")
    op.drop_constraint(
        "fk_purchase_order_receipts_shop_id_shops", "purchase_order_receipts", type_="foreignkey"
    )
    op.drop_column("purchase_order_receipts", "shop_id")

    op.drop_index("ix_purchase_orders_shop_id", table_name="purchase_orders")
    op.drop_constraint("fk_purchase_orders_shop_id_shops", "purchase_orders", type_="foreignkey")
    op.drop_column("purchase_orders", "shop_id")

    op.drop_index("ix_parts_shop_id", table_name="parts")
    op.drop_constraint("fk_parts_shop_id_shops", "parts", type_="foreignkey")
    op.drop_column("parts", "shop_id")

    op.drop_index("ix_vendors_shop_id", table_name="vendors")
    op.drop_constraint("fk_vendors_shop_id_shops", "vendors", type_="foreignkey")
    op.drop_column("vendors", "shop_id")

    op.drop_index("ix_notifications_shop_id", table_name="notifications")
    op.drop_constraint("fk_notifications_shop_id_shops", "notifications", type_="foreignkey")
    op.drop_column("notifications", "shop_id")

    op.drop_index("ix_payment_schedules_shop_id", table_name="payment_schedules")
    op.drop_constraint(
        "fk_payment_schedules_shop_id_shops", "payment_schedules", type_="foreignkey"
    )
    op.drop_column("payment_schedules", "shop_id")

    op.drop_index("ix_invoice_payments_shop_id", table_name="invoice_payments")
    op.drop_constraint("fk_invoice_payments_shop_id_shops", "invoice_payments", type_="foreignkey")
    op.drop_column("invoice_payments", "shop_id")

    op.drop_index("ix_invoices_shop_id", table_name="invoices")
    op.drop_constraint("fk_invoices_shop_id_shops", "invoices", type_="foreignkey")
    op.drop_column("invoices", "shop_id")

    op.drop_index("ix_work_order_notes_shop_id", table_name="work_order_notes")
    op.drop_constraint("fk_work_order_notes_shop_id_shops", "work_order_notes", type_="foreignkey")
    op.drop_column("work_order_notes", "shop_id")

    op.drop_index("ix_work_order_status_events_shop_id", table_name="work_order_status_events")
    op.drop_constraint(
        "fk_work_order_status_events_shop_id_shops", "work_order_status_events", type_="foreignkey"
    )
    op.drop_column("work_order_status_events", "shop_id")

    op.drop_index("ix_work_orders_shop_id", table_name="work_orders")
    op.drop_constraint("fk_work_orders_shop_id_shops", "work_orders", type_="foreignkey")
    op.drop_column("work_orders", "shop_id")

    op.drop_index("ix_technician_time_entries_shop_id", table_name="technician_time_entries")
    op.drop_constraint(
        "fk_technician_time_entries_shop_id_shops", "technician_time_entries", type_="foreignkey"
    )
    op.drop_column("technician_time_entries", "shop_id")

    op.drop_index("ix_technicians_shop_id", table_name="technicians")
    op.drop_constraint("fk_technicians_shop_id_shops", "technicians", type_="foreignkey")
    op.drop_column("technicians", "shop_id")

    op.drop_index("ix_estimate_approval_events_shop_id", table_name="estimate_approval_events")
    op.drop_constraint(
        "fk_estimate_approval_events_shop_id_shops", "estimate_approval_events", type_="foreignkey"
    )
    op.drop_column("estimate_approval_events", "shop_id")

    op.drop_index("ix_estimate_approval_requests_shop_id", table_name="estimate_approval_requests")
    op.drop_constraint(
        "fk_estimate_approval_requests_shop_id_shops",
        "estimate_approval_requests",
        type_="foreignkey",
    )
    op.drop_column("estimate_approval_requests", "shop_id")

    op.drop_index("ix_estimate_revisions_shop_id", table_name="estimate_revisions")
    op.drop_constraint(
        "fk_estimate_revisions_shop_id_shops", "estimate_revisions", type_="foreignkey"
    )
    op.drop_column("estimate_revisions", "shop_id")

    op.drop_index("ix_estimates_shop_id", table_name="estimates")
    op.drop_constraint("fk_estimates_shop_id_shops", "estimates", type_="foreignkey")
    op.drop_column("estimates", "shop_id")

    op.drop_index("ix_vehicles_shop_id", table_name="vehicles")
    op.drop_constraint("fk_vehicles_shop_id_shops", "vehicles", type_="foreignkey")
    op.drop_column("vehicles", "shop_id")

    op.drop_index("ix_customers_shop_id", table_name="customers")
    op.drop_constraint("fk_customers_shop_id_shops", "customers", type_="foreignkey")
    op.drop_column("customers", "shop_id")
