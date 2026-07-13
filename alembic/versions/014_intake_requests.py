from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "014_intake_requests"
down_revision = "013_vendors_parts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "intake_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("customer_name", sa.String(length=200), nullable=False),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("phone_normalized", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=180), nullable=True),
        sa.Column("email_normalized", sa.String(length=180), nullable=True),
        sa.Column("vehicle_description", sa.String(length=300), nullable=True),
        sa.Column("complaint", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="phone"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="new"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("converted_customer_id", sa.Integer(), nullable=True),
        sa.Column("converted_vehicle_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["converted_customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["converted_vehicle_id"], ["vehicles.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_intake_requests_owner_status_updated",
        "intake_requests",
        ["owner_user_id", "status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_intake_requests_owner_status_updated", table_name="intake_requests")
    op.drop_table("intake_requests")
