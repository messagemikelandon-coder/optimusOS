from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "013_vendors_parts"
down_revision = "012_technicians"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("contact_name", sa.String(length=180), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("phone_normalized", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=180), nullable=True),
        sa.Column("email_normalized", sa.String(length=180), nullable=True),
        sa.Column("address_line_1", sa.String(length=180), nullable=True),
        sa.Column("address_line_2", sa.String(length=180), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("state", sa.String(length=80), nullable=True),
        sa.Column("postal_code", sa.String(length=20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false"),
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
    )
    op.create_index(
        "ix_vendors_owner_archived_updated",
        "vendors",
        ["owner_user_id", "is_archived", "updated_at"],
    )
    op.create_index("ix_vendors_owner_name", "vendors", ["owner_user_id", "name"])

    op.create_table(
        "parts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("vendor_id", sa.Integer(), nullable=True),
        sa.Column("part_number", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column("quantity_on_hand", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reorder_threshold", sa.Integer(), nullable=True),
        sa.Column("unit_cost", sa.Numeric(10, 2), nullable=True),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=True),
        sa.Column("location", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false"),
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
        sa.CheckConstraint("quantity_on_hand >= 0", name="ck_parts_quantity_non_negative"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_parts_owner_archived_updated",
        "parts",
        ["owner_user_id", "is_archived", "updated_at"],
    )
    op.create_index("ix_parts_owner_part_number", "parts", ["owner_user_id", "part_number"])
    op.create_index("ix_parts_vendor", "parts", ["vendor_id"])


def downgrade() -> None:
    op.drop_index("ix_parts_vendor", table_name="parts")
    op.drop_index("ix_parts_owner_part_number", table_name="parts")
    op.drop_index("ix_parts_owner_archived_updated", table_name="parts")
    op.drop_table("parts")

    op.drop_index("ix_vendors_owner_name", table_name="vendors")
    op.drop_index("ix_vendors_owner_archived_updated", table_name="vendors")
    op.drop_table("vendors")
