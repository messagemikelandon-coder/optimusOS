from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "036_diagnostic_evidence"
down_revision = "035_operating_mode_confirmed_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Diagnostic Evidence Engine (/goal slice 3): enrich `diagnostic_findings`
    with structured, evidence-oriented fields so a finding records not just what
    was observed but how well the evidence supports the diagnosis and how urgent
    it is for safety.

    Adds four nullable columns -- `complaint` (the operator-reported complaint,
    distinct from the technician-observed `symptoms`), `confidence` (theory /
    probable / confirmed), `severity` (informational / advisory / service_soon /
    unsafe), and `recommended_next_test` (the next step that would raise
    confidence) -- plus two CHECK constraints bounding the enum columns to their
    allowed values (or NULL).

    Additive and non-blocking: every column is nullable with no server default,
    so all pre-existing findings simply have these fields unset (NULL). No route
    requires them, no existing behavior changes, and the CHECK constraints permit
    NULL so existing rows always satisfy them. The application store enforces the
    integrity rule that a `conclusion` may only be recorded together with a
    `confidence` level (so an un-evidenced diagnosis is never presented as fact);
    that rule is not expressed as a DB constraint because it only applies to
    rows written after this slice, and back-dating it onto historical rows would
    be a behavior change, not a schema addition.
    """
    op.add_column("diagnostic_findings", sa.Column("complaint", sa.Text(), nullable=True))
    op.add_column(
        "diagnostic_findings", sa.Column("confidence", sa.String(length=20), nullable=True)
    )
    op.add_column("diagnostic_findings", sa.Column("severity", sa.String(length=20), nullable=True))
    op.add_column(
        "diagnostic_findings", sa.Column("recommended_next_test", sa.Text(), nullable=True)
    )
    op.create_check_constraint(
        "ck_diagnostic_findings_confidence",
        "diagnostic_findings",
        "confidence IS NULL OR confidence IN ('theory', 'probable', 'confirmed')",
    )
    op.create_check_constraint(
        "ck_diagnostic_findings_severity",
        "diagnostic_findings",
        "severity IS NULL OR severity IN ('informational', 'advisory', 'service_soon', 'unsafe')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_diagnostic_findings_severity", "diagnostic_findings", type_="check")
    op.drop_constraint("ck_diagnostic_findings_confidence", "diagnostic_findings", type_="check")
    op.drop_column("diagnostic_findings", "recommended_next_test")
    op.drop_column("diagnostic_findings", "severity")
    op.drop_column("diagnostic_findings", "confidence")
    op.drop_column("diagnostic_findings", "complaint")
