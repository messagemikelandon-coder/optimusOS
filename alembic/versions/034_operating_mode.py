from __future__ import annotations

import json
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "034_operating_mode"
down_revision = "033_support_impersonation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """ADR-022 capability foundation, slice 1: adds `shops.operating_mode`
    (solo/mobile_field/shop) as a workflow-shaping axis kept deliberately
    separate from `shop_subscriptions.tier` (a commercial-entitlement axis).
    This column is additive only -- no route, store function, or UI reads
    it after this migration; a later, separate slice adds enforcement.

    Column is added nullable first, explicitly backfilled, then set
    NOT NULL -- the same nullable-then-backfill-then-not-null shape already
    used for `shop_id` (migrations 023-025). Every existing shop backfills
    to 'shop' for backward compatibility, since every shop in this codebase
    today already uses bays/technicians/shop-based scheduling (see
    docs/context/GOAL_EVIDENCE_MATRIX.md Part A) -- mirroring migration
    031's identical "never put a shop already in daily real use onto a
    surprising new state" reasoning for the subscription-tier grandfather.
    A `shop_events` row is recorded per shop, mirroring 031's own
    'subscription_grandfathered' audit-event precedent -- including that
    precedent's explicit Python-computed `created_at` rather than the
    table's `server_default=func.now()`. A multi-revision `alembic upgrade
    head` run executes every migration in one outer transaction, so
    Postgres's `now()` is frozen to that whole run's start time, not
    per-statement -- relying on it here would tie this event's timestamp
    with migration 022's much-earlier backfill event instead of sorting
    after 031's, which is exactly the bug an e2e regression test caught
    when this migration first used the server default.
    """
    op.add_column(
        "shops",
        sa.Column("operating_mode", sa.String(length=20), nullable=True),
    )

    connection = op.get_bind()
    shop_ids = [row[0] for row in connection.execute(sa.text("SELECT id FROM shops"))]
    now = datetime.now(UTC)
    for shop_id in shop_ids:
        connection.execute(
            sa.text("UPDATE shops SET operating_mode = 'shop' WHERE id = :shop_id"),
            {"shop_id": shop_id},
        )
        connection.execute(
            sa.text(
                "INSERT INTO shop_events (shop_id, event_type, actor_name, event_metadata, "
                "created_at) VALUES (:shop_id, 'operating_mode_backfilled', "
                "'migration:034_operating_mode', CAST(:metadata AS JSON), :now)"
            ),
            {
                "shop_id": shop_id,
                "metadata": json.dumps({"operating_mode": "shop"}),
                "now": now,
            },
        )

    op.alter_column(
        "shops",
        "operating_mode",
        nullable=False,
        server_default="shop",
    )
    op.create_check_constraint(
        "ck_shops_operating_mode",
        "shops",
        "operating_mode IN ('solo', 'mobile_field', 'shop')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_shops_operating_mode", "shops", type_="check")
    op.drop_column("shops", "operating_mode")
