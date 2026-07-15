from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "019_diag_inspection_audit"
down_revision = "018_approval_token_revocation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("diagnostic_findings", "inspections"):
        op.add_column(
            table,
            sa.Column(
                "is_archived",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
        op.add_column(table, sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column("created_by_user_id", sa.Integer(), nullable=True))
        op.add_column(table, sa.Column("updated_by_user_id", sa.Integer(), nullable=True))
        op.add_column(table, sa.Column("archived_by_user_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_created_by_user_id",
            table,
            "user_accounts",
            ["created_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_foreign_key(
            f"fk_{table}_updated_by_user_id",
            table,
            "user_accounts",
            ["updated_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_foreign_key(
            f"fk_{table}_archived_by_user_id",
            table,
            "user_accounts",
            ["archived_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(
            f"ix_{table}_owner_archived_updated",
            table,
            ["owner_user_id", "is_archived", "updated_at"],
        )

    op.create_table(
        "diagnostic_finding_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("finding_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_name", sa.String(length=160), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["finding_id"], ["diagnostic_findings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user_accounts.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "event_type IN ('created', 'updated', 'archived')",
            name="ck_diagnostic_finding_events_type",
        ),
        sa.CheckConstraint(
            "actor_type IN ('owner', 'technician')",
            name="ck_diagnostic_finding_events_actor_type",
        ),
    )
    op.create_index(
        "ix_diagnostic_finding_events_finding_created",
        "diagnostic_finding_events",
        ["finding_id", "created_at"],
    )

    op.create_table(
        "inspection_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("inspection_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("actor_name", sa.String(length=160), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["inspection_id"], ["inspections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["user_accounts.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "event_type IN ('created', 'updated', 'archived')",
            name="ck_inspection_events_type",
        ),
        sa.CheckConstraint(
            "actor_type IN ('owner', 'technician')",
            name="ck_inspection_events_actor_type",
        ),
    )
    op.create_index(
        "ix_inspection_events_inspection_created",
        "inspection_events",
        ["inspection_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_inspection_events_inspection_created", table_name="inspection_events")
    op.drop_table("inspection_events")

    op.drop_index(
        "ix_diagnostic_finding_events_finding_created", table_name="diagnostic_finding_events"
    )
    op.drop_table("diagnostic_finding_events")

    for table in ("diagnostic_findings", "inspections"):
        op.drop_index(f"ix_{table}_owner_archived_updated", table_name=table)
        op.drop_constraint(f"fk_{table}_archived_by_user_id", table, type_="foreignkey")
        op.drop_constraint(f"fk_{table}_updated_by_user_id", table, type_="foreignkey")
        op.drop_constraint(f"fk_{table}_created_by_user_id", table, type_="foreignkey")
        op.drop_column(table, "archived_by_user_id")
        op.drop_column(table, "updated_by_user_id")
        op.drop_column(table, "created_by_user_id")
        op.drop_column(table, "archived_at")
        op.drop_column(table, "is_archived")
