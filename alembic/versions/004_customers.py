from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "004_customers"
down_revision = "003_context_entries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("first_name", sa.String(length=120), nullable=True),
        sa.Column("last_name", sa.String(length=120), nullable=True),
        sa.Column("company_name", sa.String(length=180), nullable=True),
        sa.Column("email", sa.String(length=180), nullable=True),
        sa.Column("email_normalized", sa.String(length=180), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("secondary_phone", sa.String(length=40), nullable=True),
        sa.Column("phone_normalized", sa.String(length=32), nullable=True),
        sa.Column("secondary_phone_normalized", sa.String(length=32), nullable=True),
        sa.Column("address_line_1", sa.String(length=180), nullable=True),
        sa.Column("address_line_2", sa.String(length=180), nullable=True),
        sa.Column("city", sa.String(length=120), nullable=True),
        sa.Column("state", sa.String(length=80), nullable=True),
        sa.Column("postal_code", sa.String(length=20), nullable=True),
        sa.Column("preferred_contact_method", sa.String(length=40), nullable=True),
        sa.Column("internal_notes", sa.Text(), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        "ix_customers_owner_archived_updated",
        "customers",
        ["owner_user_id", "is_archived", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_customers_owner_name",
        "customers",
        ["owner_user_id", "last_name", "first_name"],
        unique=False,
    )
    op.create_index(
        "ix_customers_owner_company",
        "customers",
        ["owner_user_id", "company_name"],
        unique=False,
    )
    op.create_index(
        "ix_customers_owner_email",
        "customers",
        ["owner_user_id", "email_normalized"],
        unique=False,
    )
    op.create_index(
        "ix_customers_owner_phone",
        "customers",
        ["owner_user_id", "phone_normalized"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_customers_owner_phone", table_name="customers")
    op.drop_index("ix_customers_owner_email", table_name="customers")
    op.drop_index("ix_customers_owner_company", table_name="customers")
    op.drop_index("ix_customers_owner_name", table_name="customers")
    op.drop_index("ix_customers_owner_archived_updated", table_name="customers")
    op.drop_table("customers")
