from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "040_job_input_proposals"
down_revision = "039_job_compilation_release"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Recommendation-only AI (/goal): audit record of AI-proposed Job Compiler
    inputs for a diagnostic finding.

    Adds one table `job_input_proposals` holding the validated, draft-only
    proposal payload plus provenance (model, prompt version, validation outcome,
    disposition) and no secret. A proposal is never applied automatically -- it
    is a suggestion the owner reviews and feeds into the deterministic compile
    flow. Additive and reversible; no existing table or route is affected.
    """
    op.create_table(
        "job_input_proposals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "owner_user_id",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "shop_id",
            sa.Integer(),
            sa.ForeignKey("shops.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "finding_id",
            sa.Integer(),
            sa.ForeignKey("diagnostic_findings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="proposed"),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_version", sa.String(length=60), nullable=False),
        sa.Column(
            "validation_status", sa.String(length=20), nullable=False, server_default="valid"
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by_user_id",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'accepted', 'dismissed')",
            name="ck_job_input_proposals_status",
        ),
    )
    op.create_index("ix_job_input_proposals_shop_id", "job_input_proposals", ["shop_id"])
    op.create_index(
        "ix_job_input_proposals_finding_created",
        "job_input_proposals",
        ["finding_id", "created_at"],
    )
    op.create_index(
        "ix_job_input_proposals_owner_status_updated",
        "job_input_proposals",
        ["owner_user_id", "status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_job_input_proposals_owner_status_updated", table_name="job_input_proposals")
    op.drop_index("ix_job_input_proposals_finding_created", table_name="job_input_proposals")
    op.drop_index("ix_job_input_proposals_shop_id", table_name="job_input_proposals")
    op.drop_table("job_input_proposals")
