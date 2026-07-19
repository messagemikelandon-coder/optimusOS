from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "027_email_verification"
down_revision = "026_user_account_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Adds email-verification support (/goal Phase 5): a nullable
    `email_verified_at` timestamp on `user_accounts` (NULL means
    unverified or no email at all -- the pre-existing bootstrapped owner
    and every technician account have no email and stay NULL forever,
    same as `email`/`email_normalized` from migration 026), plus a new
    `email_verification_tokens` table storing only a hash of each raw
    token, matching the token-handling conventions already established
    by `estimate_approval_requests` (random, hashed at rest, expiring,
    single-use via `status`, revocable, auditable).
    """
    op.add_column(
        "user_accounts", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )

    op.create_table(
        "email_verification_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_account_id",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('active', 'used', 'expired', 'revoked')",
            name="ck_email_verification_tokens_status",
        ),
    )
    op.create_index(
        "ix_email_verification_tokens_user_account_id",
        "email_verification_tokens",
        ["user_account_id"],
    )
    op.create_index(
        "uq_email_verification_tokens_token_hash",
        "email_verification_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "uq_email_verification_tokens_active_user",
        "email_verification_tokens",
        ["user_account_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_email_verification_tokens_active_user", table_name="email_verification_tokens"
    )
    op.drop_index("uq_email_verification_tokens_token_hash", table_name="email_verification_tokens")
    op.drop_index(
        "ix_email_verification_tokens_user_account_id", table_name="email_verification_tokens"
    )
    op.drop_table("email_verification_tokens")
    op.drop_column("user_accounts", "email_verified_at")
