from __future__ import annotations

import json

import sqlalchemy as sa

from alembic import op
from app.config import get_settings

revision = "022_shop_tenant_model"
down_revision = "021_part_allocations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shops",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("legal_business_name", sa.String(length=200), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("address_line_1", sa.String(length=200), nullable=True),
        sa.Column("address_line_2", sa.String(length=200), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("state", sa.String(length=80), nullable=True),
        sa.Column("postal_code", sa.String(length=20), nullable=True),
        sa.Column("country", sa.String(length=80), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("email", sa.String(length=180), nullable=True),
        sa.Column(
            "timezone", sa.String(length=80), nullable=False, server_default="America/Chicago"
        ),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="USD"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pilot"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('pilot', 'active', 'suspended', 'cancelled')", name="ck_shops_status"
        ),
    )

    op.create_table(
        "shop_settings",
        sa.Column("shop_id", sa.Integer(), primary_key=True),
        sa.Column("labor_rate", sa.Numeric(10, 2), nullable=True),
        sa.Column("mobile_service_fee", sa.Numeric(10, 2), nullable=True),
        sa.Column("shop_supplies_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("parts_tax_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("operating_hours", sa.JSON(), nullable=True),
        sa.Column("service_area", sa.JSON(), nullable=True),
        sa.Column("estimate_terms_text", sa.Text(), nullable=True),
        sa.Column("invoice_terms_text", sa.Text(), nullable=True),
        sa.Column("payment_plan_settings", sa.JSON(), nullable=True),
        sa.Column("branding_reference", sa.String(length=300), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
    )

    op.create_table(
        "shop_memberships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("user_account_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_account_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("shop_id", "user_account_id", name="uq_shop_memberships_shop_user"),
        sa.CheckConstraint(
            "role IN ('owner', 'manager', 'technician')", name="ck_shop_memberships_role"
        ),
    )
    op.create_index("ix_shop_memberships_shop_id", "shop_memberships", ["shop_id"])
    op.create_index("ix_shop_memberships_user_account_id", "shop_memberships", ["user_account_id"])

    op.create_table(
        "shop_invitations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=180), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("invited_by_user_account_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["invited_by_user_account_id"], ["user_accounts.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'manager', 'technician')", name="ck_shop_invitations_role"
        ),
    )
    op.create_index("ix_shop_invitations_shop_id", "shop_invitations", ["shop_id"])
    op.create_index(
        "ix_shop_invitations_token_hash", "shop_invitations", ["token_hash"], unique=True
    )

    op.create_table(
        "shop_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("shop_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("actor_user_account_id", sa.Integer(), nullable=True),
        sa.Column("actor_name", sa.String(length=200), nullable=True),
        sa.Column("event_metadata", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["shop_id"], ["shops.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["actor_user_account_id"], ["user_accounts.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_shop_events_shop_id_created_at", "shop_events", ["shop_id", "created_at"])

    _backfill_existing_owners_as_shops()


def _backfill_existing_owners_as_shops() -> None:
    """Create one Shop per existing real (non-synthetic) owner account and
    attach that owner plus their technicians as memberships.

    In every real deployment this runs against, there is exactly one such
    owner (Landon Motor Works) -- synthetic test-support accounts are
    created via runtime API calls only after migrations have already run,
    so they are never present at this point in a normal flow. The loop
    below still handles more than one non-synthetic owner defensively
    (e.g. an unusual long-lived dev database) without crashing, rather
    than assuming the single-owner case.

    Values come from already-configured app.config.Settings (real,
    already-live configuration) or from the owner's own existing account
    row (real data) -- never invented. Every Shop/ShopSettings field this
    codebase has no known real value for (address, phone, email, hours,
    terms text, payment-plan settings, branding) is left NULL.
    """
    connection = op.get_bind()
    settings = get_settings()

    owners = connection.execute(
        sa.text(
            "SELECT id, username, display_name FROM user_accounts "
            "WHERE role = 'owner' AND is_synthetic_test_account = false "
            "ORDER BY id"
        )
    ).fetchall()

    for owner in owners:
        display_name = (
            settings.business_name
            if len(owners) == 1
            else f"{settings.business_name} ({owner.username})"
        )
        shop_id = connection.execute(
            sa.text(
                "INSERT INTO shops (display_name, status) "
                "VALUES (:display_name, 'active') RETURNING id"
            ),
            {"display_name": display_name},
        ).scalar_one()

        connection.execute(
            sa.text(
                "INSERT INTO shop_settings "
                "(shop_id, labor_rate, mobile_service_fee, shop_supplies_percent, parts_tax_rate) "
                "VALUES (:shop_id, :labor_rate, :mobile_service_fee, :shop_supplies_percent, "
                ":parts_tax_rate)"
            ),
            {
                "shop_id": shop_id,
                "labor_rate": settings.labor_rate,
                "mobile_service_fee": settings.mobile_service_fee,
                "shop_supplies_percent": settings.shop_supplies_percent,
                "parts_tax_rate": settings.parts_tax_rate,
            },
        )

        connection.execute(
            sa.text(
                "INSERT INTO shop_memberships (shop_id, user_account_id, role) "
                "VALUES (:shop_id, :owner_id, 'owner')"
            ),
            {"shop_id": shop_id, "owner_id": owner.id},
        )

        technicians = connection.execute(
            sa.text(
                "SELECT id FROM user_accounts "
                "WHERE role = 'technician' AND shop_owner_id = :owner_id "
                "AND is_synthetic_test_account = false"
            ),
            {"owner_id": owner.id},
        ).fetchall()
        for technician in technicians:
            connection.execute(
                sa.text(
                    "INSERT INTO shop_memberships (shop_id, user_account_id, role) "
                    "VALUES (:shop_id, :technician_id, 'technician')"
                ),
                {"shop_id": shop_id, "technician_id": technician.id},
            )

        connection.execute(
            sa.text(
                "INSERT INTO shop_events (shop_id, event_type, actor_name, event_metadata) "
                "VALUES (:shop_id, 'shop_backfilled_from_existing_owner', 'migration:022', "
                "CAST(:metadata AS JSON))"
            ),
            {
                "shop_id": shop_id,
                "metadata": json.dumps(
                    {"owner_user_account_id": owner.id, "technician_count": len(technicians)}
                ),
            },
        )


def downgrade() -> None:
    op.drop_index("ix_shop_events_shop_id_created_at", table_name="shop_events")
    op.drop_table("shop_events")

    op.drop_index("ix_shop_invitations_token_hash", table_name="shop_invitations")
    op.drop_index("ix_shop_invitations_shop_id", table_name="shop_invitations")
    op.drop_table("shop_invitations")

    op.drop_index("ix_shop_memberships_user_account_id", table_name="shop_memberships")
    op.drop_index("ix_shop_memberships_shop_id", table_name="shop_memberships")
    op.drop_table("shop_memberships")

    op.drop_table("shop_settings")

    op.drop_table("shops")
