from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "029_account_lifecycle"
down_revision = "028_membership_tenant_boundary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_accounts",
        sa.Column("account_status", sa.String(length=20), nullable=False, server_default="active"),
    )
    op.add_column(
        "user_accounts",
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("user_accounts", sa.Column("locked_until", sa.DateTime(timezone=True)))
    op.add_column("user_accounts", sa.Column("last_failed_login_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_user_accounts_account_status",
        "user_accounts",
        "account_status IN ('active', 'disabled', 'suspended')",
    )
    op.execute("UPDATE user_accounts SET account_status = 'disabled' WHERE is_active = false")

    op.create_table(
        "password_reset_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_account_id",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('active', 'used', 'expired', 'revoked')",
            name="ck_password_reset_tokens_status",
        ),
    )
    op.create_index(
        "ix_password_reset_tokens_user_account_id",
        "password_reset_tokens",
        ["user_account_id"],
    )
    op.create_index(
        "uq_password_reset_tokens_token_hash",
        "password_reset_tokens",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "uq_password_reset_tokens_active_user",
        "password_reset_tokens",
        ["user_account_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "auth_login_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_account_id",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "auth_session_id",
            sa.Integer(),
            sa.ForeignKey("auth_sessions.id", ondelete="SET NULL"),
        ),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("ip_address", sa.String(length=64)),
        sa.Column("user_agent", sa.String(length=512)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "event_type IN ('succeeded', 'failed', 'locked', 'blocked')",
            name="ck_auth_login_events_type",
        ),
    )
    op.create_index(
        "ix_auth_login_events_user_created",
        "auth_login_events",
        ["user_account_id", "created_at"],
    )

    op.create_table(
        "auth_mfa_factors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_account_id",
            sa.Integer(),
            sa.ForeignKey("user_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("factor_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("label", sa.String(length=120)),
        sa.Column("external_credential_id", sa.String(length=255)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "factor_type IN ('totp', 'webauthn', 'external')",
            name="ck_auth_mfa_factors_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'revoked')",
            name="ck_auth_mfa_factors_status",
        ),
    )
    op.create_index("ix_auth_mfa_factors_user_account_id", "auth_mfa_factors", ["user_account_id"])

    op.add_column("shop_invitations", sa.Column("email_normalized", sa.String(length=180)))
    op.execute("UPDATE shop_invitations SET email_normalized = lower(trim(email))")
    # Pre-029 allowed multiple unresolved invitations whose email differed
    # only by case/whitespace. Keep the earliest row pending and revoke later
    # duplicates deterministically before adding the normalized unique index.
    op.execute(
        "UPDATE shop_invitations AS invitation SET revoked_at = CURRENT_TIMESTAMP "
        "WHERE invitation.accepted_at IS NULL AND invitation.revoked_at IS NULL "
        "AND EXISTS (SELECT 1 FROM shop_invitations AS earlier "
        "            WHERE earlier.shop_id = invitation.shop_id "
        "              AND earlier.email_normalized = invitation.email_normalized "
        "              AND earlier.accepted_at IS NULL "
        "              AND earlier.revoked_at IS NULL "
        "              AND earlier.id < invitation.id)"
    )
    op.alter_column("shop_invitations", "email_normalized", nullable=False)
    op.create_index(
        "ix_shop_invitations_email_normalized", "shop_invitations", ["email_normalized"]
    )
    op.create_index(
        "uq_shop_invitations_pending_email",
        "shop_invitations",
        ["shop_id", "email_normalized"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
        sqlite_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_shop_invitations_pending_email", table_name="shop_invitations")
    op.drop_index("ix_shop_invitations_email_normalized", table_name="shop_invitations")
    op.drop_column("shop_invitations", "email_normalized")

    op.drop_index("ix_auth_mfa_factors_user_account_id", table_name="auth_mfa_factors")
    op.drop_table("auth_mfa_factors")
    op.drop_index("ix_auth_login_events_user_created", table_name="auth_login_events")
    op.drop_table("auth_login_events")
    op.drop_index("uq_password_reset_tokens_active_user", table_name="password_reset_tokens")
    op.drop_index("uq_password_reset_tokens_token_hash", table_name="password_reset_tokens")
    op.drop_index("ix_password_reset_tokens_user_account_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")

    op.drop_constraint("ck_user_accounts_account_status", "user_accounts", type_="check")
    op.drop_column("user_accounts", "last_failed_login_at")
    op.drop_column("user_accounts", "locked_until")
    op.drop_column("user_accounts", "failed_login_attempts")
    op.drop_column("user_accounts", "account_status")
