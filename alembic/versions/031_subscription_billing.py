from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "031_subscription_billing"
down_revision = "030_workflow_gaps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shop_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "shop_id",
            sa.Integer(),
            sa.ForeignKey("shops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tier", sa.String(length=20), nullable=False),
        sa.Column("billing_status", sa.String(length=20), nullable=False),
        sa.Column("seat_limit", sa.Integer()),
        sa.Column("trial_ends_at", sa.DateTime(timezone=True)),
        sa.Column("current_period_start", sa.DateTime(timezone=True)),
        sa.Column("current_period_end", sa.DateTime(timezone=True)),
        sa.Column("grace_period_ends_at", sa.DateTime(timezone=True)),
        sa.Column("canceled_at", sa.DateTime(timezone=True)),
        sa.Column("square_customer_id", sa.String(length=120)),
        sa.Column("square_card_id", sa.String(length=120)),
        sa.Column("square_subscription_id", sa.String(length=120)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("shop_id", name="uq_shop_subscriptions_shop_id"),
        sa.CheckConstraint("tier IN ('solo', 'team', 'shop')", name="ck_shop_subscriptions_tier"),
        sa.CheckConstraint(
            "billing_status IN ('trialing', 'active', 'past_due', 'canceled')",
            name="ck_shop_subscriptions_billing_status",
        ),
    )

    # Grandfather every existing Shop (the real pilot install included) onto
    # the unlimited-seat tier with no trial timer and no Square objects --
    # this migration must never put a shop that is already in daily real use
    # onto a countdown that could lock its own owner out. Only shops created
    # from here forward via self-service signup (app/shop_store.py's
    # `signup_shop_owner`) get a real trial; bootstrap/synthetic owner
    # creation also grandfathers, per the same reasoning (see
    # app/shop_store.py::create_shop_for_new_owner's `created_via` branch).
    connection = op.get_bind()
    shop_ids = [row[0] for row in connection.execute(sa.text("SELECT id FROM shops"))]
    now = datetime.now(UTC)
    for shop_id in shop_ids:
        connection.execute(
            sa.text(
                "INSERT INTO shop_subscriptions "
                "(shop_id, tier, billing_status, seat_limit, created_at, updated_at) "
                "VALUES (:shop_id, 'shop', 'active', NULL, :now, :now)"
            ),
            {"shop_id": shop_id, "now": now},
        )
        connection.execute(
            sa.text(
                "INSERT INTO shop_events (shop_id, event_type, actor_name, event_metadata, "
                "created_at) VALUES (:shop_id, 'subscription_grandfathered', "
                "'031_subscription_billing migration', NULL, :now)"
            ),
            {"shop_id": shop_id, "now": now},
        )


def downgrade() -> None:
    op.drop_table("shop_subscriptions")
