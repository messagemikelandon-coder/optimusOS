from __future__ import annotations

import json
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "035_operating_mode_confirmed_at"
down_revision = "034_operating_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """ADR-022 post-signup mode onboarding: adds `shops.operating_mode_confirmed_at`,
    a nullable timestamp recording when a shop's owner deliberately confirmed
    an operating mode after account creation. NULL means "not yet confirmed"
    -- which is exactly the state a brand-new shop should be in so its owner
    sees the one-time first-run mode picker.

    Additive and non-blocking: no route requires this column, and confirmation
    never gates signup or any other request.

    Column is added nullable with no default, then every *pre-existing* shop
    is backfilled to this migration's timestamp so established shops (already
    in daily use, see docs/context/GOAL_EVIDENCE_MATRIX.md Part A) are treated
    as already-confirmed and are never interrupted by the onboarding card --
    the same "never surprise a shop already in real use" grandfathering
    migrations 031 and 034 used. New shops created *after* this migration keep
    NULL (unconfirmed) because there is no server default. A `shop_events` row
    is written per backfilled shop, mirroring 034/031's audit-event precedent,
    including their explicit Python-computed `created_at` (a multi-revision
    `alembic upgrade head` runs in one transaction, so `now()` is frozen to
    the run's start and would mis-sort this event; the Python timestamp sorts
    it correctly after 034's backfill).
    """
    op.add_column(
        "shops",
        sa.Column("operating_mode_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )

    connection = op.get_bind()
    shop_ids = [row[0] for row in connection.execute(sa.text("SELECT id FROM shops"))]
    now = datetime.now(UTC)
    for shop_id in shop_ids:
        connection.execute(
            sa.text("UPDATE shops SET operating_mode_confirmed_at = :now WHERE id = :shop_id"),
            {"shop_id": shop_id, "now": now},
        )
        connection.execute(
            sa.text(
                "INSERT INTO shop_events (shop_id, event_type, actor_name, event_metadata, "
                "created_at) VALUES (:shop_id, 'operating_mode_confirmation_backfilled', "
                "'migration:035_operating_mode_confirmed_at', CAST(:metadata AS JSON), :now)"
            ),
            {
                "shop_id": shop_id,
                "metadata": json.dumps({"operating_mode_confirmed_at": now.isoformat()}),
                "now": now,
            },
        )


def downgrade() -> None:
    op.drop_column("shops", "operating_mode_confirmed_at")
