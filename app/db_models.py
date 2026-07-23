from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class UserAccount(Base):
    __tablename__ = "user_accounts"
    __table_args__ = (
        UniqueConstraint("username", name="uq_user_accounts_username"),
        CheckConstraint(
            "role IN ('owner', 'manager', 'technician', 'support')", name="ck_user_accounts_role"
        ),
        CheckConstraint(
            "account_status IN ('active', 'disabled', 'suspended')",
            name="ck_user_accounts_account_status",
        ),
        # Partial (not a plain UniqueConstraint) because pre-existing rows
        # and technician accounts have no email at all -- NULL must stay
        # unconstrained, only a real, provided email must be unique
        # platform-wide (/goal Phase 4 self-service signup).
        Index(
            "uq_user_accounts_email_normalized",
            "email_normalized",
            unique=True,
            sqlite_where=text("email_normalized IS NOT NULL"),
            postgresql_where=text("email_normalized IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="owner")
    shop_owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=True,
    )
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # Nullable: no email exists anywhere in this codebase before /goal Phase 4
    # -- the bootstrapped owner and every technician account predate this
    # column and have none. Only self-service signup (Phase 4) and,
    # eventually, an owner-editable profile field populate it.
    email: Mapped[str | None] = mapped_column(String(180))
    email_normalized: Mapped[str | None] = mapped_column(String(180))
    # NULL means "unverified" -- also true, permanently, for every account
    # with no email at all (bootstrapped owner, technicians). /goal Phase 5.
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    account_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    failed_login_attempts: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failed_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    is_synthetic_test_account: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sessions: Mapped[list[AuthSession]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="AuthSession.user_id",
    )
    context_entries: Mapped[list[ContextEntry]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    customers: Mapped[list[Customer]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
    )
    vehicles: Mapped[list[Vehicle]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
    )
    estimates: Mapped[list[Estimate]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
    )
    work_orders: Mapped[list[WorkOrder]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
    )
    invoices: Mapped[list[Invoice]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
    )


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        Index("ix_auth_sessions_user_id", "user_id"),
        Index("ix_auth_sessions_expires_at", "expires_at"),
        Index("ix_auth_sessions_impersonated_by", "impersonated_by_user_account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_accounts.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    # /goal Phase 8: set only on a session minted by support-initiated
    # impersonation (this session belongs to the real target owner account,
    # not the support account) -- never set on the support account's own
    # session. SET NULL (not CASCADE) so deleting the support account can
    # never silently delete/corrupt the impersonated owner's session history.
    impersonated_by_user_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL")
    )

    user: Mapped[UserAccount] = relationship(back_populates="sessions", foreign_keys=[user_id])
    context_entries: Mapped[list[ContextEntry]] = relationship(back_populates="auth_session")


class EmailVerificationToken(Base):
    """Token requirements (/goal Phase 5): random, hashed at rest,
    expiring, single-use (`status`), revocable, auditable -- matches the
    established `EstimateApprovalRequest` token pattern. Only
    `token_hash` is ever stored; the raw token exists only in memory
    long enough to be included in the (non-sending, /goal Phase 5)
    verification email."""

    __tablename__ = "email_verification_tokens"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'used', 'expired', 'revoked')",
            name="ck_email_verification_tokens_status",
        ),
        Index("ix_email_verification_tokens_user_account_id", "user_account_id"),
        Index("uq_email_verification_tokens_token_hash", "token_hash", unique=True),
        Index(
            "uq_email_verification_tokens_active_user",
            "user_account_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_account_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'used', 'expired', 'revoked')",
            name="ck_password_reset_tokens_status",
        ),
        Index("ix_password_reset_tokens_user_account_id", "user_account_id"),
        Index("uq_password_reset_tokens_token_hash", "token_hash", unique=True),
        Index(
            "uq_password_reset_tokens_active_user",
            "user_account_id",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_account_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuthLoginEvent(Base):
    __tablename__ = "auth_login_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('succeeded', 'failed', 'locked', 'blocked')",
            name="ck_auth_login_events_type",
        ),
        Index("ix_auth_login_events_user_created", "user_account_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_account_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    auth_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuthMfaFactor(Base):
    """Provider-neutral MFA metadata; no raw shared secret is stored here."""

    __tablename__ = "auth_mfa_factors"
    __table_args__ = (
        CheckConstraint(
            "factor_type IN ('totp', 'webauthn', 'external')",
            name="ck_auth_mfa_factors_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'active', 'revoked')",
            name="ck_auth_mfa_factors_status",
        ),
        Index("ix_auth_mfa_factors_user_account_id", "user_account_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_account_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    factor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    label: Mapped[str | None] = mapped_column(String(120))
    external_credential_id: Mapped[str | None] = mapped_column(String(255))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ContextEntry(Base):
    __tablename__ = "context_entries"
    __table_args__ = (
        CheckConstraint(
            "scope_type IN ('project', 'session')",
            name="ck_context_entries_scope_type",
        ),
        CheckConstraint(
            "(scope_type = 'project' AND auth_session_id IS NULL) "
            "OR (scope_type = 'session' AND auth_session_id IS NOT NULL)",
            name="ck_context_entries_scope_session_match",
        ),
        UniqueConstraint(
            "user_id",
            "scope_type",
            "scope_key",
            "context_key",
            name="uq_context_entries_scope_key",
        ),
        Index("ix_context_entries_user_project", "user_id", "project_key"),
        Index("ix_context_entries_scope_key", "scope_key"),
        Index("ix_context_entries_updated_at", "updated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user_accounts.id", ondelete="CASCADE"))
    auth_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("auth_sessions.id", ondelete="CASCADE"),
        nullable=True,
    )
    project_key: Mapped[str] = mapped_column(String(120), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(200), nullable=False)
    context_key: Mapped[str] = mapped_column(String(120), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    revision: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    user: Mapped[UserAccount] = relationship(back_populates="context_entries")
    auth_session: Mapped[AuthSession | None] = relationship(back_populates="context_entries")


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        Index("ix_customers_owner_archived_updated", "owner_user_id", "is_archived", "updated_at"),
        Index("ix_customers_owner_name", "owner_user_id", "last_name", "first_name"),
        Index("ix_customers_owner_company", "owner_user_id", "company_name"),
        Index("ix_customers_owner_email", "owner_user_id", "email_normalized"),
        Index("ix_customers_owner_phone", "owner_user_id", "phone_normalized"),
        Index("ix_customers_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(120))
    last_name: Mapped[str | None] = mapped_column(String(120))
    company_name: Mapped[str | None] = mapped_column(String(180))
    email: Mapped[str | None] = mapped_column(String(180))
    email_normalized: Mapped[str | None] = mapped_column(String(180))
    phone: Mapped[str | None] = mapped_column(String(40))
    secondary_phone: Mapped[str | None] = mapped_column(String(40))
    phone_normalized: Mapped[str | None] = mapped_column(String(32))
    secondary_phone_normalized: Mapped[str | None] = mapped_column(String(32))
    address_line_1: Mapped[str | None] = mapped_column(String(180))
    address_line_2: Mapped[str | None] = mapped_column(String(180))
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(80))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    preferred_contact_method: Mapped[str | None] = mapped_column(String(40))
    internal_notes: Mapped[str | None] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    owner: Mapped[UserAccount] = relationship(back_populates="customers")
    vehicles: Mapped[list[Vehicle]] = relationship(back_populates="customer")
    estimates: Mapped[list[Estimate]] = relationship(back_populates="customer")


class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        Index("ix_vehicles_owner_archived_updated", "owner_user_id", "is_archived", "updated_at"),
        Index(
            "ix_vehicles_owner_customer_archived_updated",
            "owner_user_id",
            "customer_id",
            "is_archived",
            "updated_at",
        ),
        Index("ix_vehicles_owner_year_make_model", "owner_user_id", "year", "make", "model"),
        Index("ix_vehicles_owner_license_plate", "owner_user_id", "license_plate_normalized"),
        Index("ix_vehicles_owner_vin", "owner_user_id", "vin"),
        Index(
            "uq_vehicles_owner_active_vin",
            "owner_user_id",
            "vin",
            unique=True,
            sqlite_where=text("vin IS NOT NULL AND is_archived = 0"),
            postgresql_where=text("vin IS NOT NULL AND is_archived = false"),
        ),
        Index("ix_vehicles_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    vin: Mapped[str | None] = mapped_column(String(17))
    year: Mapped[int | None] = mapped_column(nullable=True)
    make: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    trim: Mapped[str | None] = mapped_column(String(120))
    engine: Mapped[str | None] = mapped_column(String(120))
    drivetrain: Mapped[str | None] = mapped_column(String(80))
    transmission: Mapped[str | None] = mapped_column(String(120))
    license_plate: Mapped[str | None] = mapped_column(String(32))
    license_plate_state: Mapped[str | None] = mapped_column(String(40))
    license_plate_normalized: Mapped[str | None] = mapped_column(String(32))
    color: Mapped[str | None] = mapped_column(String(80))
    current_mileage: Mapped[int | None] = mapped_column(nullable=True)
    fleet_unit_number: Mapped[str | None] = mapped_column(String(80))
    internal_notes: Mapped[str | None] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    owner: Mapped[UserAccount] = relationship(back_populates="vehicles")
    customer: Mapped[Customer] = relationship(back_populates="vehicles")
    estimates: Mapped[list[Estimate]] = relationship(back_populates="vehicle")


class Estimate(Base):
    __tablename__ = "estimates"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'draft', 'ready', 'awaiting_approval', 'approved', 'declined', "
            "'expired', 'superseded', 'archived'"
            ")",
            name="ck_estimates_status",
        ),
        Index("ix_estimates_owner_status_updated", "owner_user_id", "status", "updated_at"),
        Index(
            "ix_estimates_owner_customer_updated",
            "owner_user_id",
            "customer_id",
            "updated_at",
        ),
        Index(
            "ix_estimates_owner_vehicle_updated",
            "owner_user_id",
            "vehicle_id",
            "updated_at",
        ),
        UniqueConstraint("estimate_number", name="uq_estimates_estimate_number"),
        Index("ix_estimates_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    estimate_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft")
    current_revision_number: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
        server_default="1",
    )
    approved_revision_number: Mapped[int | None] = mapped_column(nullable=True)
    estimate_total: Mapped[float | None] = mapped_column(nullable=True)
    payment_option_selected: Mapped[str | None] = mapped_column(String(40))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_archived: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    owner: Mapped[UserAccount] = relationship(back_populates="estimates")
    customer: Mapped[Customer] = relationship(back_populates="estimates")
    vehicle: Mapped[Vehicle] = relationship(back_populates="estimates")
    revisions: Mapped[list[EstimateRevision]] = relationship(
        back_populates="estimate",
        cascade="all, delete-orphan",
        order_by="EstimateRevision.revision_number",
    )
    approval_requests: Mapped[list[EstimateApprovalRequest]] = relationship(
        back_populates="estimate",
        cascade="all, delete-orphan",
    )
    approval_events: Mapped[list[EstimateApprovalEvent]] = relationship(
        back_populates="estimate",
        cascade="all, delete-orphan",
    )
    work_orders: Mapped[list[WorkOrder]] = relationship(
        back_populates="estimate",
        cascade="all, delete-orphan",
    )
    invoices: Mapped[list[Invoice]] = relationship(
        back_populates="estimate",
        cascade="all, delete-orphan",
    )


class EstimateRevision(Base):
    __tablename__ = "estimate_revisions"
    __table_args__ = (
        UniqueConstraint(
            "estimate_id",
            "revision_number",
            name="uq_estimate_revisions_estimate_revision",
        ),
        Index(
            "ix_estimate_revisions_owner_estimate_revision",
            "owner_user_id",
            "estimate_id",
            "revision_number",
        ),
        Index("ix_estimate_revisions_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    estimate_id: Mapped[int] = mapped_column(
        ForeignKey("estimates.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    revision_number: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    customer_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    vehicle_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    estimate_request_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    estimate_response_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    terms_text: Mapped[str] = mapped_column(Text, nullable=False)
    payment_options_payload: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    approval_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    estimate: Mapped[Estimate] = relationship(back_populates="revisions")
    work_orders: Mapped[list[WorkOrder]] = relationship(back_populates="revision")
    invoices: Mapped[list[Invoice]] = relationship(back_populates="revision")


class EstimateApprovalRequest(Base):
    __tablename__ = "estimate_approval_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'used', 'expired', 'revoked')",
            name="ck_estimate_approval_requests_status",
        ),
        UniqueConstraint("token_hash", name="uq_estimate_approval_requests_token_hash"),
        Index(
            "ix_estimate_approval_requests_estimate_status",
            "estimate_id",
            "status",
            "expires_at",
        ),
        Index("ix_estimate_approval_requests_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    estimate_id: Mapped[int] = mapped_column(
        ForeignKey("estimates.id", ondelete="CASCADE"),
        nullable=False,
    )
    estimate_revision_id: Mapped[int] = mapped_column(
        ForeignKey("estimate_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_by_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    estimate: Mapped[Estimate] = relationship(back_populates="approval_requests")
    revision: Mapped[EstimateRevision] = relationship()


class EstimateApprovalEvent(Base):
    __tablename__ = "estimate_approval_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ("
            "'sent', 'approved', 'declined', 'expired', 'superseded', 'archived', "
            "'internal_recorded', 'revoked'"
            ")",
            name="ck_estimate_approval_events_type",
        ),
        Index(
            "ix_estimate_approval_events_estimate_created",
            "estimate_id",
            "created_at",
        ),
        Index("ix_estimate_approval_events_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    estimate_id: Mapped[int] = mapped_column(
        ForeignKey("estimates.id", ondelete="CASCADE"),
        nullable=False,
    )
    estimate_revision_id: Mapped[int] = mapped_column(
        ForeignKey("estimate_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    approval_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("estimate_approval_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_name: Mapped[str | None] = mapped_column(String(160))
    approval_method: Mapped[str | None] = mapped_column(String(80))
    approval_evidence: Mapped[str | None] = mapped_column(Text)
    accepted_terms: Mapped[bool | None] = mapped_column(Boolean)
    payment_option: Mapped[str | None] = mapped_column(String(40))
    payment_plan_acknowledged: Mapped[bool | None] = mapped_column(Boolean)
    decline_reason: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    estimate: Mapped[Estimate] = relationship(back_populates="approval_events")
    revision: Mapped[EstimateRevision] = relationship()


class Technician(Base):
    __tablename__ = "technicians"
    __table_args__ = (
        Index(
            "ix_technicians_owner_archived_updated", "owner_user_id", "is_archived", "updated_at"
        ),
        Index("ix_technicians_owner_name", "owner_user_id", "last_name", "first_name"),
        UniqueConstraint("user_account_id", name="uq_technicians_user_account_id"),
        Index("ix_technicians_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    user_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    first_name: Mapped[str | None] = mapped_column(String(120))
    last_name: Mapped[str | None] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40))
    phone_normalized: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(180))
    email_normalized: Mapped[str | None] = mapped_column(String(180))
    employment_status: Mapped[str | None] = mapped_column(String(40))
    job_title: Mapped[str | None] = mapped_column(String(120))
    hire_date: Mapped[date | None] = mapped_column(Date)
    hourly_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    certifications: Mapped[str | None] = mapped_column(Text)
    certification_expiration: Mapped[date | None] = mapped_column(Date)
    specialties: Mapped[str | None] = mapped_column(Text)
    driver_license_valid: Mapped[bool | None] = mapped_column(Boolean)
    insurance_verified: Mapped[bool | None] = mapped_column(Boolean)
    normal_availability: Mapped[str | None] = mapped_column(Text)
    safety_notes: Mapped[str | None] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    time_entries: Mapped[list[TechnicianTimeEntry]] = relationship(
        back_populates="technician",
        cascade="all, delete-orphan",
        order_by="TechnicianTimeEntry.clock_in_at.desc()",
    )


class TechnicianTimeEntry(Base):
    __tablename__ = "technician_time_entries"
    __table_args__ = (
        Index(
            "ix_technician_time_entries_technician_created",
            "technician_id",
            "created_at",
        ),
        Index(
            "ux_technician_time_entries_one_open_per_technician",
            "technician_id",
            unique=True,
            postgresql_where=text("clock_out_at IS NULL"),
            sqlite_where=text("clock_out_at IS NULL"),
        ),
        Index("ix_technician_time_entries_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    technician_id: Mapped[int] = mapped_column(
        ForeignKey("technicians.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    clock_in_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    clock_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    technician: Mapped[Technician] = relationship(back_populates="time_entries")


class WorkOrder(Base):
    __tablename__ = "work_orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ("
            "'pending_requirements', 'ready_to_schedule', 'scheduled', 'in_progress', "
            "'waiting_for_parts', 'waiting_for_approval', 'completed', 'cancelled'"
            ")",
            name="ck_work_orders_status",
        ),
        Index("ix_work_orders_owner_status_updated", "owner_user_id", "status", "updated_at"),
        Index(
            "ix_work_orders_owner_customer_updated",
            "owner_user_id",
            "customer_id",
            "updated_at",
        ),
        Index(
            "ix_work_orders_owner_vehicle_updated",
            "owner_user_id",
            "vehicle_id",
            "updated_at",
        ),
        Index("ix_work_orders_assigned_technician", "assigned_technician_id"),
        UniqueConstraint(
            "estimate_id",
            "estimate_revision_id",
            name="uq_work_orders_estimate_revision",
        ),
        Index("ix_work_orders_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    estimate_id: Mapped[int] = mapped_column(
        ForeignKey("estimates.id", ondelete="CASCADE"),
        nullable=False,
    )
    estimate_revision_id: Mapped[int] = mapped_column(
        ForeignKey("estimate_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    estimate_number: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    complaint: Mapped[str] = mapped_column(Text, nullable=False)
    diagnosis: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    estimate_total: Mapped[float | None] = mapped_column(nullable=True)
    labor_hours_estimate: Mapped[float | None] = mapped_column(nullable=True)
    payment_option_selected: Mapped[str | None] = mapped_column(String(40))
    deposit_received: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    authorization_confirmed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_technician_id: Mapped[int | None] = mapped_column(
        ForeignKey("technicians.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_comeback: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    owner: Mapped[UserAccount] = relationship(back_populates="work_orders")
    assigned_technician: Mapped[Technician | None] = relationship()
    estimate: Mapped[Estimate] = relationship(back_populates="work_orders")
    revision: Mapped[EstimateRevision] = relationship(back_populates="work_orders")
    customer: Mapped[Customer] = relationship()
    vehicle: Mapped[Vehicle] = relationship()
    status_events: Mapped[list[WorkOrderStatusEvent]] = relationship(
        back_populates="work_order",
        cascade="all, delete-orphan",
        order_by="WorkOrderStatusEvent.created_at",
    )
    notes: Mapped[list[WorkOrderNote]] = relationship(
        back_populates="work_order",
        cascade="all, delete-orphan",
        order_by="WorkOrderNote.created_at",
    )
    invoice: Mapped[Invoice | None] = relationship(
        back_populates="work_order",
        cascade="all, delete-orphan",
        uselist=False,
    )


class WorkOrderStatusEvent(Base):
    __tablename__ = "work_order_status_events"
    __table_args__ = (
        CheckConstraint(
            "from_status IS NULL OR from_status IN ("
            "'pending_requirements', 'ready_to_schedule', 'scheduled', 'in_progress', "
            "'waiting_for_parts', 'waiting_for_approval', 'completed', 'cancelled'"
            ")",
            name="ck_work_order_status_events_from_status",
        ),
        CheckConstraint(
            "to_status IN ("
            "'pending_requirements', 'ready_to_schedule', 'scheduled', 'in_progress', "
            "'waiting_for_parts', 'waiting_for_approval', 'completed', 'cancelled'"
            ")",
            name="ck_work_order_status_events_to_status",
        ),
        Index(
            "ix_work_order_status_events_work_order_created",
            "work_order_id",
            "created_at",
        ),
        Index("ix_work_order_status_events_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    work_order_id: Mapped[int] = mapped_column(
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(40))
    to_status: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    work_order: Mapped[WorkOrder] = relationship(back_populates="status_events")


class WorkOrderNote(Base):
    __tablename__ = "work_order_notes"
    __table_args__ = (
        CheckConstraint(
            "visibility IN ('internal', 'customer')",
            name="ck_work_order_notes_visibility",
        ),
        Index("ix_work_order_notes_work_order_created", "work_order_id", "created_at"),
        Index("ix_work_order_notes_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    work_order_id: Mapped[int] = mapped_column(
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    work_order: Mapped[WorkOrder] = relationship(back_populates="notes")


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'issued', 'partially_paid', 'paid', 'overdue', 'void')",
            name="ck_invoices_status",
        ),
        Index("ix_invoices_owner_status_updated", "owner_user_id", "status", "updated_at"),
        Index("ix_invoices_owner_work_order", "owner_user_id", "work_order_id"),
        UniqueConstraint("work_order_id", name="uq_invoices_work_order"),
        UniqueConstraint("invoice_number", name="uq_invoices_invoice_number"),
        Index("uq_invoices_square_invoice_id", "square_invoice_id", unique=True),
        Index("ix_invoices_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    work_order_id: Mapped[int] = mapped_column(
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        nullable=False,
    )
    estimate_id: Mapped[int] = mapped_column(
        ForeignKey("estimates.id", ondelete="CASCADE"),
        nullable=False,
    )
    estimate_revision_id: Mapped[int] = mapped_column(
        ForeignKey("estimate_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=False,
    )
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"),
        nullable=False,
    )
    invoice_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    complaint: Mapped[str] = mapped_column(Text, nullable=False)
    payment_option_selected: Mapped[str | None] = mapped_column(String(40))
    customer_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    vehicle_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    labor_total: Mapped[float] = mapped_column(nullable=False)
    parts_total: Mapped[float] = mapped_column(nullable=False)
    fees_total: Mapped[float] = mapped_column(nullable=False)
    invoice_total: Mapped[float] = mapped_column(nullable=False)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    square_invoice_id: Mapped[str | None] = mapped_column(String(64))
    square_status: Mapped[str | None] = mapped_column(String(40))
    square_payment_url: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    owner: Mapped[UserAccount] = relationship(back_populates="invoices")
    work_order: Mapped[WorkOrder] = relationship(back_populates="invoice")
    estimate: Mapped[Estimate] = relationship(back_populates="invoices")
    revision: Mapped[EstimateRevision] = relationship(back_populates="invoices")
    line_items: Mapped[list[InvoiceLineItem]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="InvoiceLineItem.sort_order",
    )
    payments: Mapped[list[InvoicePayment]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="InvoicePayment.recorded_at",
    )
    schedule: Mapped[list[PaymentSchedule]] = relationship(
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="PaymentSchedule.sort_order",
    )


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('labor', 'part', 'fee')",
            name="ck_invoice_line_items_kind",
        ),
        Index("ix_invoice_line_items_invoice_sort", "invoice_id", "sort_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[float] = mapped_column(nullable=False)
    unit_amount: Mapped[float] = mapped_column(nullable=False)
    line_total: Mapped[float] = mapped_column(nullable=False)

    invoice: Mapped[Invoice] = relationship(back_populates="line_items")


class InvoicePayment(Base):
    """A single append-only payment (or reversal) event on an invoice.

    Payments are never updated or deleted after insert. Voiding a payment inserts
    a new row with a negative ``amount`` and ``reversal_of_payment_id`` pointing
    back at the original row; the balance is always ``SUM(amount)`` over every
    row for the invoice, so the reversal cancels the original arithmetically
    without mutating it.
    """

    __tablename__ = "invoice_payments"
    __table_args__ = (
        CheckConstraint(
            "applies_to IN ('deposit', 'installment', 'balance', 'full', 'other')",
            name="ck_invoice_payments_applies_to",
        ),
        CheckConstraint(
            "(reversal_of_payment_id IS NULL AND amount > 0) "
            "OR (reversal_of_payment_id IS NOT NULL AND amount < 0)",
            name="ck_invoice_payments_amount_sign",
        ),
        UniqueConstraint(
            "reversal_of_payment_id",
            name="uq_invoice_payments_reversal_of",
        ),
        Index(
            "ix_invoice_payments_owner_invoice_recorded",
            "owner_user_id",
            "invoice_id",
            "recorded_at",
        ),
        Index("ix_invoice_payments_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    applies_to: Mapped[str] = mapped_column(String(20), nullable=False)
    method_label: Mapped[str] = mapped_column(String(60), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reversal_of_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoice_payments.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    invoice: Mapped[Invoice] = relationship(back_populates="payments")


class PaymentSchedule(Base):
    """A single informational, read-only payment-schedule row for an invoice.

    Generated once at issue time from a placeholder even-split default (see
    ``app/invoice_store.py``). Purely informational display data -- balance,
    status, and overdue logic never read this table.
    """

    __tablename__ = "payment_schedules"
    __table_args__ = (
        UniqueConstraint(
            "invoice_id",
            "sort_order",
            name="uq_payment_schedules_invoice_sort",
        ),
        Index(
            "ix_payment_schedules_owner_invoice_sort",
            "owner_user_id",
            "invoice_id",
            "sort_order",
        ),
        Index("ix_payment_schedules_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    invoice: Mapped[Invoice] = relationship(back_populates="schedule")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('estimate', 'work_order', 'invoice')",
            name="ck_notifications_entity_type",
        ),
        CheckConstraint(
            "event IN ("
            "'estimate_sent', 'estimate_approved', 'estimate_declined', "
            "'work_order_status_changed', 'invoice_issued', 'payment_recorded', "
            "'payment_voided'"
            ")",
            name="ck_notifications_event",
        ),
        Index("ix_notifications_owner_read_created", "owner_user_id", "read_at", "created_at"),
        Index("ix_notifications_owner_created", "owner_user_id", "created_at"),
        Index("ix_notifications_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    # Polymorphic pointer; deliberately no FK so notifications outlive their
    # entity type's lifecycle rules and never block entity deletion.
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_id: Mapped[int] = mapped_column(nullable=False)
    event: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    # The one deliberately mutable column: null = unread. UI state, not
    # business data -- everything else on this table is append-only.
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class Vendor(Base):
    __tablename__ = "vendors"
    __table_args__ = (
        Index("ix_vendors_owner_archived_updated", "owner_user_id", "is_archived", "updated_at"),
        Index("ix_vendors_owner_name", "owner_user_id", "name"),
        Index("ix_vendors_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(180))
    phone: Mapped[str | None] = mapped_column(String(40))
    phone_normalized: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(180))
    email_normalized: Mapped[str | None] = mapped_column(String(180))
    address_line_1: Mapped[str | None] = mapped_column(String(180))
    address_line_2: Mapped[str | None] = mapped_column(String(180))
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(80))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    parts: Mapped[list[Part]] = relationship(back_populates="vendor")


class Part(Base):
    __tablename__ = "parts"
    __table_args__ = (
        Index("ix_parts_owner_archived_updated", "owner_user_id", "is_archived", "updated_at"),
        Index("ix_parts_owner_part_number", "owner_user_id", "part_number"),
        Index("ix_parts_vendor", "vendor_id"),
        CheckConstraint("quantity_on_hand >= 0", name="ck_parts_quantity_non_negative"),
        Index("ix_parts_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    vendor_id: Mapped[int | None] = mapped_column(
        ForeignKey("vendors.id", ondelete="SET NULL"),
        nullable=True,
    )
    part_number: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(300), nullable=False)
    category: Mapped[str | None] = mapped_column(String(120))
    quantity_on_hand: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    reorder_threshold: Mapped[int | None] = mapped_column()
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    location: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    vendor: Mapped[Vendor | None] = relationship(back_populates="parts")


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'submitted', 'partially_received', 'received', 'cancelled')",
            name="ck_purchase_orders_status",
        ),
        UniqueConstraint("po_number", name="uq_purchase_orders_po_number"),
        Index(
            "ix_purchase_orders_owner_status_updated",
            "owner_user_id",
            "status",
            "updated_at",
        ),
        Index("ix_purchase_orders_owner_vendor", "owner_user_id", "vendor_id"),
        Index("ix_purchase_orders_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    vendor_id: Mapped[int] = mapped_column(
        ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=False
    )
    po_number: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    vendor: Mapped[Vendor] = relationship()
    line_items: Mapped[list[PurchaseOrderLineItem]] = relationship(
        back_populates="purchase_order",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderLineItem.id",
    )


class PurchaseOrderLineItem(Base):
    __tablename__ = "purchase_order_line_items"
    __table_args__ = (
        CheckConstraint("quantity_ordered > 0", name="ck_po_line_items_quantity_ordered"),
        CheckConstraint(
            "quantity_received >= 0", name="ck_po_line_items_quantity_received_non_negative"
        ),
        CheckConstraint(
            "quantity_received <= quantity_ordered",
            name="ck_po_line_items_quantity_received_le_ordered",
        ),
        Index("ix_po_line_items_purchase_order", "purchase_order_id"),
        Index("ix_po_line_items_part", "part_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False
    )
    part_id: Mapped[int] = mapped_column(
        ForeignKey("parts.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_ordered: Mapped[int] = mapped_column(nullable=False)
    quantity_received: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="line_items")
    part: Mapped[Part] = relationship()


class PurchaseOrderReceipt(Base):
    __tablename__ = "purchase_order_receipts"
    __table_args__ = (
        CheckConstraint("quantity_received > 0", name="ck_po_receipts_quantity_positive"),
        Index("ix_po_receipts_purchase_order_created", "purchase_order_id", "created_at"),
        Index("ix_purchase_order_receipts_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False
    )
    line_item_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_order_line_items.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    quantity_received: Mapped[int] = mapped_column(nullable=False)
    received_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )
    received_by_name: Mapped[str | None] = mapped_column(String(160))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PartAllocation(Base):
    __tablename__ = "part_allocations"
    __table_args__ = (
        CheckConstraint("quantity_required > 0", name="ck_part_allocations_required_positive"),
        CheckConstraint(
            "quantity_allocated >= 0", name="ck_part_allocations_allocated_non_negative"
        ),
        CheckConstraint("quantity_used >= 0", name="ck_part_allocations_used_non_negative"),
        CheckConstraint("quantity_returned >= 0", name="ck_part_allocations_returned_non_negative"),
        CheckConstraint(
            "quantity_used <= quantity_allocated", name="ck_part_allocations_used_le_allocated"
        ),
        CheckConstraint(
            "quantity_returned <= quantity_used", name="ck_part_allocations_returned_le_used"
        ),
        Index("ix_part_allocations_owner_work_order", "owner_user_id", "work_order_id"),
        Index("ix_part_allocations_part", "part_id"),
        Index("ix_part_allocations_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    work_order_id: Mapped[int] = mapped_column(
        ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False
    )
    part_id: Mapped[int] = mapped_column(
        ForeignKey("parts.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_required: Mapped[int] = mapped_column(nullable=False)
    quantity_allocated: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    quantity_used: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    quantity_returned: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")
    unit_cost_snapshot: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    part: Mapped[Part] = relationship()


class PartAllocationEvent(Base):
    __tablename__ = "part_allocation_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('allocated', 'used', 'returned')",
            name="ck_part_allocation_events_type",
        ),
        CheckConstraint(
            "actor_type IN ('owner', 'technician')",
            name="ck_part_allocation_events_actor_type",
        ),
        Index("ix_part_allocation_events_allocation_created", "allocation_id", "created_at"),
        Index("ix_part_allocation_events_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    allocation_id: Mapped[int] = mapped_column(
        ForeignKey("part_allocations.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity_delta: Mapped[int] = mapped_column(nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )
    actor_name: Mapped[str | None] = mapped_column(String(160))
    inventory_override: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    override_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IntakeRequest(Base):
    __tablename__ = "intake_requests"
    __table_args__ = (
        Index(
            "ix_intake_requests_owner_status_updated",
            "owner_user_id",
            "status",
            "updated_at",
        ),
        Index("ix_intake_requests_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(40))
    phone_normalized: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(180))
    email_normalized: Mapped[str | None] = mapped_column(String(180))
    vehicle_description: Mapped[str | None] = mapped_column(String(300))
    # Structured, VIN-decodable vehicle draft fields (/goal Priority 2): let an
    # intake request hold identified vehicle data before any customer or
    # canonical `vehicles` row exists, so a shop can decode a VIN at intake and
    # carry the result through to atomic conversion. All nullable -- a draft may
    # have only a free-text `vehicle_description`, only a VIN, or nothing yet.
    vehicle_vin: Mapped[str | None] = mapped_column(String(17))
    vehicle_year: Mapped[int | None] = mapped_column()
    vehicle_make: Mapped[str | None] = mapped_column(String(100))
    vehicle_model: Mapped[str | None] = mapped_column(String(100))
    vehicle_trim: Mapped[str | None] = mapped_column(String(120))
    vehicle_engine: Mapped[str | None] = mapped_column(String(120))
    vehicle_drivetrain: Mapped[str | None] = mapped_column(String(80))
    complaint: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="phone")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="new")
    notes: Mapped[str | None] = mapped_column(Text)
    converted_customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
    )
    converted_vehicle_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DiagnosticFinding(Base):
    __tablename__ = "diagnostic_findings"
    __table_args__ = (
        Index(
            "ix_diagnostic_findings_owner_vehicle_updated",
            "owner_user_id",
            "vehicle_id",
            "updated_at",
        ),
        Index("ix_diagnostic_findings_work_order", "work_order_id"),
        Index(
            "ix_diagnostic_findings_owner_archived_updated",
            "owner_user_id",
            "is_archived",
            "updated_at",
        ),
        Index("ix_diagnostic_findings_shop_id", "shop_id"),
        CheckConstraint(
            "confidence IS NULL OR confidence IN ('theory', 'probable', 'confirmed')",
            name="ck_diagnostic_findings_confidence",
        ),
        CheckConstraint(
            "severity IS NULL OR severity IN "
            "('informational', 'advisory', 'service_soon', 'unsafe')",
            name="ck_diagnostic_findings_severity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    work_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_orders.id", ondelete="SET NULL"), nullable=True
    )
    technician_id: Mapped[int | None] = mapped_column(
        ForeignKey("technicians.id", ondelete="SET NULL"), nullable=True
    )
    codes: Mapped[str | None] = mapped_column(Text)
    complaint: Mapped[str | None] = mapped_column(Text)
    symptoms: Mapped[str] = mapped_column(Text, nullable=False)
    tests_performed: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[str | None] = mapped_column(String(20))
    severity: Mapped[str | None] = mapped_column(String(20))
    recommended_next_test: Mapped[str | None] = mapped_column(Text)
    conclusion: Mapped[str | None] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )
    archived_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class DiagnosticFindingEvent(Base):
    __tablename__ = "diagnostic_finding_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created', 'updated', 'archived')",
            name="ck_diagnostic_finding_events_type",
        ),
        CheckConstraint(
            "actor_type IN ('owner', 'technician')",
            name="ck_diagnostic_finding_events_actor_type",
        ),
        Index("ix_diagnostic_finding_events_finding_created", "finding_id", "created_at"),
        Index("ix_diagnostic_finding_events_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    finding_id: Mapped[int] = mapped_column(
        ForeignKey("diagnostic_findings.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )
    actor_name: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class JobCompilation(Base):
    """A deterministic compilation of an approved diagnostic finding into a
    priced draft job: labor lines, aggregated part needs (customer pricing
    only), work-order task descriptors, and reconciled totals. Produced by
    ``app/job_compiler.py`` with no OpenAI/paid call. Always an internal draft
    (``released`` defaults False); the compiler never sends, approves, orders
    parts, or takes payment. Recompiling is idempotent by ``content_hash``;
    changed inputs supersede the prior draft and create the next revision."""

    __tablename__ = "job_compilations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'superseded')",
            name="ck_job_compilations_status",
        ),
        Index("ix_job_compilations_shop_id", "shop_id"),
        Index("ix_job_compilations_finding_status", "finding_id", "status"),
        Index("ix_job_compilations_owner_status_updated", "owner_user_id", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    finding_id: Mapped[int] = mapped_column(
        ForeignKey("diagnostic_findings.id", ondelete="CASCADE"), nullable=False
    )
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    revision_number: Mapped[int] = mapped_column(nullable=False, default=1)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    released: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    source_severity: Mapped[str | None] = mapped_column(String(20))
    source_confidence: Mapped[str | None] = mapped_column(String(20))
    source_conclusion: Mapped[str | None] = mapped_column(Text)
    source_diagnosis_unverified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    labor_rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    labor_lines: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    part_lines: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    tasks: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    totals: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    superseded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_compilations.id", ondelete="SET NULL"), nullable=True
    )
    # Canonical release bridge (/goal): the estimate this compilation was
    # released into, if any. `released` (already present) flips true on release;
    # the FK provides idempotency + traceability. SET NULL so deleting the
    # estimate never cascades away the compilation/audit history.
    released_estimate_id: Mapped[int | None] = mapped_column(
        ForeignKey("estimates.id", ondelete="SET NULL"), nullable=True
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class JobCompilationEvent(Base):
    __tablename__ = "job_compilation_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('compiled', 'recompiled', 'superseded', 'released')",
            name="ck_job_compilation_events_type",
        ),
        CheckConstraint(
            "actor_type IN ('owner', 'manager')",
            name="ck_job_compilation_events_actor_type",
        ),
        Index("ix_job_compilation_events_compilation_created", "compilation_id", "created_at"),
        Index("ix_job_compilation_events_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    compilation_id: Mapped[int] = mapped_column(
        ForeignKey("job_compilations.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    revision_number: Mapped[int] = mapped_column(nullable=False, default=1)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )
    actor_name: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Inspection(Base):
    __tablename__ = "inspections"
    __table_args__ = (
        Index("ix_inspections_owner_vehicle_updated", "owner_user_id", "vehicle_id", "updated_at"),
        Index("ix_inspections_work_order", "work_order_id"),
        Index(
            "ix_inspections_owner_archived_updated",
            "owner_user_id",
            "is_archived",
            "updated_at",
        ),
        Index("ix_inspections_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False
    )
    work_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_orders.id", ondelete="SET NULL"), nullable=True
    )
    technician_id: Mapped[int | None] = mapped_column(
        ForeignKey("technicians.id", ondelete="SET NULL"), nullable=True
    )
    inspection_type: Mapped[str | None] = mapped_column(String(120))
    items: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False, default=list)
    overall_notes: Mapped[str | None] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )
    archived_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class InspectionEvent(Base):
    __tablename__ = "inspection_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created', 'updated', 'archived')",
            name="ck_inspection_events_type",
        ),
        CheckConstraint(
            "actor_type IN ('owner', 'technician')",
            name="ck_inspection_events_actor_type",
        ),
        Index("ix_inspection_events_inspection_created", "inspection_id", "created_at"),
        Index("ix_inspection_events_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    inspection_id: Mapped[int] = mapped_column(
        ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True
    )
    actor_name: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Bay(Base):
    __tablename__ = "bays"
    __table_args__ = (
        Index("ix_bays_owner_archived_name", "owner_user_id", "is_archived", "name"),
        Index("ix_bays_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class WorkingHours(Base):
    __tablename__ = "working_hours"
    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="ck_working_hours_day_of_week"),
        CheckConstraint(
            "start_minute >= 0 AND start_minute < 1440", name="ck_working_hours_start_minute"
        ),
        CheckConstraint(
            "end_minute > 0 AND end_minute <= 1440", name="ck_working_hours_end_minute"
        ),
        CheckConstraint("end_minute > start_minute", name="ck_working_hours_end_after_start"),
        Index(
            "ix_working_hours_owner_technician_day",
            "owner_user_id",
            "technician_id",
            "day_of_week",
        ),
        Index("ix_working_hours_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    technician_id: Mapped[int] = mapped_column(
        ForeignKey("technicians.id", ondelete="CASCADE"), nullable=False
    )
    # Day of week and minute-of-day are in the shop's local time
    # (America/Chicago) since working hours recur weekly regardless of DST --
    # see app/scheduling_store.py's local/UTC conversion helpers.
    day_of_week: Mapped[int] = mapped_column(nullable=False)
    start_minute: Mapped[int] = mapped_column(nullable=False)
    end_minute: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ScheduleBlock(Base):
    __tablename__ = "schedule_blocks"
    __table_args__ = (
        CheckConstraint("end_time > start_time", name="ck_schedule_blocks_end_after_start"),
        Index(
            "ix_schedule_blocks_owner_technician_time",
            "owner_user_id",
            "technician_id",
            "start_time",
            "end_time",
        ),
        Index(
            "ix_schedule_blocks_owner_bay_time",
            "owner_user_id",
            "bay_id",
            "start_time",
            "end_time",
        ),
        Index("ix_schedule_blocks_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    # Both null = shop-wide block (holiday/closure). Technician-only or
    # bay-only blocks apply regardless of the other dimension -- see
    # app/scheduling_store.py's _schedule_block_applies for exact semantics.
    technician_id: Mapped[int | None] = mapped_column(
        ForeignKey("technicians.id", ondelete="CASCADE"), nullable=True
    )
    bay_id: Mapped[int | None] = mapped_column(
        ForeignKey("bays.id", ondelete="CASCADE"), nullable=True
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('tentative','confirmed','in_progress','completed','canceled','no_show')",
            name="ck_appointments_status",
        ),
        CheckConstraint(
            "service_location IN ('shop','mobile')", name="ck_appointments_service_location"
        ),
        CheckConstraint("end_time > start_time", name="ck_appointments_end_after_start"),
        CheckConstraint("travel_buffer_minutes >= 0", name="ck_appointments_travel_buffer_nonneg"),
        Index(
            "ix_appointments_owner_technician_time",
            "owner_user_id",
            "technician_id",
            "start_time",
            "end_time",
        ),
        Index(
            "ix_appointments_owner_bay_time", "owner_user_id", "bay_id", "start_time", "end_time"
        ),
        Index("ix_appointments_owner_status_start", "owner_user_id", "status", "start_time"),
        Index("ix_appointments_owner_customer", "owner_user_id", "customer_id"),
        Index("ix_appointments_owner_vehicle", "owner_user_id", "vehicle_id"),
        Index("ix_appointments_work_order", "work_order_id"),
        Index("ix_appointments_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False
    )
    work_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_orders.id", ondelete="SET NULL"), nullable=True
    )
    technician_id: Mapped[int] = mapped_column(
        ForeignKey("technicians.id", ondelete="RESTRICT"), nullable=False
    )
    bay_id: Mapped[int | None] = mapped_column(
        ForeignKey("bays.id", ondelete="SET NULL"), nullable=True
    )
    service_type: Mapped[str] = mapped_column(String(160), nullable=False)
    service_location: Mapped[str] = mapped_column(
        String(20), nullable=False, default="shop", server_default="shop"
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    travel_buffer_minutes: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="tentative", server_default="tentative"
    )
    customer_notes: Mapped[str | None] = mapped_column(Text)
    internal_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)


class Shop(Base):
    """The tenant boundary (/goal Phase 3). Business tables will migrate to
    `shop_id` in a later, separate slice -- this table's own creation and
    the initial Landon Motor Works row/membership backfill is deliberately
    scoped on its own first, per the staged migration plan in
    docs/context/PLANS.md, so this diff stays small and reviewable rather
    than touching every business table at once.

    Identity fields only here; operational configuration (tax, labor rate,
    terms, hours, etc.) lives in the separate 1:1 `ShopSettings` table,
    since those change far more often than a shop's identity and the
    /goal spec explicitly asks for both as distinct models.
    """

    __tablename__ = "shops"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pilot', 'active', 'suspended', 'cancelled')",
            name="ck_shops_status",
        ),
        CheckConstraint(
            "operating_mode IN ('solo', 'mobile_field', 'shop')",
            name="ck_shops_operating_mode",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Deliberately nullable -- a shop's formal legal entity name is real
    # business information this codebase must not fabricate (see
    # docs/context/DATA_RETENTION.md's established pattern of leaving
    # unknown fields unset rather than guessing). `display_name` is the
    # one identity field always required, since every shop needs *some*
    # name to display in the product regardless of legal-entity detail.
    legal_business_name: Mapped[str | None] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    address_line_1: Mapped[str | None] = mapped_column(String(200))
    address_line_2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(80))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(80))
    phone: Mapped[str | None] = mapped_column(String(40))
    email: Mapped[str | None] = mapped_column(String(180))
    # "America/Chicago" is not a fabricated default -- it is the exact
    # timezone app/scheduling_store.py::SHOP_TIMEZONE already hardcodes
    # for the one shop this app has ever served, so it is a real known
    # value being carried into this table, not invented for it.
    timezone: Mapped[str] = mapped_column(
        String(80), nullable=False, default="America/Chicago", server_default="America/Chicago"
    )
    # This app is explicitly scoped to US-based shops today (see
    # docs/context/DATA_RETENTION.md's "Scope and jurisdiction" section) --
    # USD is a defensible default for that scope, not a guess about a
    # specific shop's real currency.
    currency: Mapped[str] = mapped_column(
        String(10), nullable=False, default="USD", server_default="USD"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pilot", server_default="pilot"
    )
    # ADR-022: operating mode shapes workflow (Solo/Mobile Field/Shop) and is
    # deliberately a separate column from `ShopSubscription.tier`, which
    # grants commercial entitlements -- the two must never be inferred from
    # each other. "shop" is the safe default for both new rows and the
    # migration 034 backfill of every pre-existing shop, since every shop in
    # this codebase today already uses bays/technicians/shop-based
    # scheduling (see docs/context/GOAL_EVIDENCE_MATRIX.md Part A) -- the
    # same backward-compatible-default reasoning migration 031 already used
    # for grandfathering existing shops onto the unlimited subscription tier.
    # This column is additive only: no route or store function reads it yet.
    operating_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="shop", server_default="shop"
    )
    # ADR-022 post-signup onboarding: NULL means the shop's owner has not yet
    # deliberately confirmed an operating mode, so a newly created shop is
    # "unconfirmed" and its owner sees the one-time first-run mode picker.
    # Deliberately nullable with no default -- migration 035 backfills every
    # pre-existing shop to the migration timestamp (established shops must not
    # be interrupted), while new shops created after it stay NULL until their
    # owner confirms. Confirmation never blocks signup or any other route.
    operating_mode_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    settings: Mapped[ShopSettings | None] = relationship(
        back_populates="shop", cascade="all, delete-orphan", uselist=False
    )
    memberships: Mapped[list[ShopMembership]] = relationship(
        back_populates="shop", cascade="all, delete-orphan"
    )
    invitations: Mapped[list[ShopInvitation]] = relationship(
        back_populates="shop", cascade="all, delete-orphan"
    )
    events: Mapped[list[ShopEvent]] = relationship(
        back_populates="shop", cascade="all, delete-orphan"
    )
    workflow_gaps: Mapped[list[WorkflowGap]] = relationship(
        back_populates="shop", cascade="all, delete-orphan"
    )
    subscription: Mapped[ShopSubscription | None] = relationship(
        back_populates="shop", cascade="all, delete-orphan", uselist=False
    )


class ShopSettings(Base):
    """Operational configuration, separate from `Shop`'s identity fields.
    One row per shop. Every field the /goal spec asks for that this
    codebase does not yet have a real, known value for (operating hours,
    service area, estimate/invoice terms text, payment-plan settings,
    branding reference) is left nullable and unset here rather than
    fabricated -- see each field's comment for where its value, if any,
    is sourced from."""

    __tablename__ = "shop_settings"

    shop_id: Mapped[int] = mapped_column(
        ForeignKey("shops.id", ondelete="CASCADE"), primary_key=True
    )
    # The four fields below have real, already-configured values in
    # app/config.py::Settings (business_name/labor_rate/mobile_service_fee/
    # parts_tax_rate/shop_supplies_percent) -- the migration backfill copies
    # those real values in, it does not invent them.
    labor_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    mobile_service_fee: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    shop_supplies_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    parts_tax_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    # Unknown/unset for the migrated shop -- no real value exists anywhere
    # in this codebase for any of these today.
    operating_hours: Mapped[dict | None] = mapped_column(JSON)
    service_area: Mapped[dict | None] = mapped_column(JSON)
    estimate_terms_text: Mapped[str | None] = mapped_column(Text)
    invoice_terms_text: Mapped[str | None] = mapped_column(Text)
    payment_plan_settings: Mapped[dict | None] = mapped_column(JSON)
    branding_reference: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    shop: Mapped[Shop] = relationship(back_populates="settings")


class ShopMembership(Base):
    """Links a `UserAccount` to a `Shop` with a role. This is the real
    membership model the /goal spec calls for -- it does not yet replace
    `UserAccount.shop_owner_id` as the tenant-scoping mechanism used by
    business-data queries (that migration is a later, separate slice per
    the staged plan), but it is the source of truth this app will migrate
    those queries onto."""

    __tablename__ = "shop_memberships"
    __table_args__ = (
        UniqueConstraint("shop_id", "user_account_id", name="uq_shop_memberships_shop_user"),
        CheckConstraint(
            "role IN ('owner', 'manager', 'technician')", name="ck_shop_memberships_role"
        ),
        Index("ix_shop_memberships_shop_id", "shop_id"),
        Index("ix_shop_memberships_user_account_id", "user_account_id"),
        # A session currently represents one shop and has no shop-switching
        # selector, so every account must resolve to exactly one active
        # membership regardless of role.
        Index(
            "uq_shop_memberships_one_active_per_user",
            "user_account_id",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active = true"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    user_account_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    shop: Mapped[Shop] = relationship(back_populates="memberships")
    user: Mapped[UserAccount] = relationship()


class ShopInvitation(Base):
    """Owner/manager-initiated invitation for a new user to join a shop
    with a given role. Token requirements (/goal Phase 5): random, hashed
    at rest, expiring, single use, revocable, audited -- this table stores
    only `token_hash`, never a raw token; the raw token is generated and
    shown to the inviter exactly once by the store layer that will be
    built in the Phase 5 slice, matching the existing
    `EstimateApprovalRequest` token pattern already proven in this
    codebase."""

    __tablename__ = "shop_invitations"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'manager', 'technician')", name="ck_shop_invitations_role"
        ),
        Index("ix_shop_invitations_shop_id", "shop_id"),
        Index("ix_shop_invitations_token_hash", "token_hash", unique=True),
        Index("ix_shop_invitations_email_normalized", "email_normalized"),
        Index(
            "uq_shop_invitations_pending_email",
            "shop_id",
            "email_normalized",
            unique=True,
            sqlite_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    email: Mapped[str] = mapped_column(String(180), nullable=False)
    email_normalized: Mapped[str] = mapped_column(String(180), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    invited_by_user_account_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    shop: Mapped[Shop] = relationship(back_populates="invitations")


class ShopEvent(Base):
    """Append-only audit trail for shop-level administrative actions
    (membership changes, status changes, settings changes, invitations) --
    the "supporting audit-event models" the /goal spec calls for,
    mirroring the existing append-only event-log pattern already used by
    `WorkOrderStatusEvent`/`DiagnosticFindingEvent`/`InspectionEvent`."""

    __tablename__ = "shop_events"
    __table_args__ = (Index("ix_shop_events_shop_id_created_at", "shop_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    actor_user_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    actor_name: Mapped[str | None] = mapped_column(String(200))
    event_metadata: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    shop: Mapped[Shop] = relationship(back_populates="events")


class WorkflowGap(Base):
    __tablename__ = "workflow_gaps"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name="ck_workflow_gaps_severity",
        ),
        CheckConstraint(
            "status IN ('open', 'investigating', 'planned', 'resolved', 'wont_fix')",
            name="ck_workflow_gaps_status",
        ),
        CheckConstraint("occurrence_count > 0", name="ck_workflow_gaps_occurrence_count"),
        Index("ix_workflow_gaps_shop_status_updated", "shop_id", "status", "updated_at"),
        Index("ix_workflow_gaps_shop_severity", "shop_id", "severity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    created_by_user_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    updated_by_user_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    workflow_area: Mapped[str] = mapped_column(String(80), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    workaround: Mapped[str | None] = mapped_column(Text)
    occurrence_count: Mapped[int] = mapped_column(nullable=False, default=1)
    first_reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_reported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    shop: Mapped[Shop] = relationship(back_populates="workflow_gaps")
    events: Mapped[list[WorkflowGapEvent]] = relationship(
        back_populates="workflow_gap", cascade="all, delete-orphan"
    )


class WorkflowGapEvent(Base):
    __tablename__ = "workflow_gap_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('created', 'updated', 'status_changed', 'occurrence_recorded')",
            name="ck_workflow_gap_events_type",
        ),
        Index("ix_workflow_gap_events_gap_created", "workflow_gap_id", "created_at"),
        Index("ix_workflow_gap_events_shop_id", "shop_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_gap_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_gaps.id", ondelete="CASCADE"), nullable=False
    )
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    actor_user_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL")
    )
    actor_name: Mapped[str | None] = mapped_column(String(200))
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str | None] = mapped_column(String(20))
    event_metadata: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    workflow_gap: Mapped[WorkflowGap] = relationship(back_populates="events")


class ShopSubscription(Base):
    """/goal Phase 7: one row per Shop tracking the shop's own platform
    subscription (billing OptimusOS itself -- unrelated to `Square`'s
    customer-facing invoice integration in `square_store.py`, which bills
    the shop's *customers*, not the shop).

    `billing_status` is a cached, informational snapshot of what Square
    last reported; the real access decision (`app/auth.py`'s
    `require_shop_access_active`) is always recomputed from the
    timestamps below at request time, matching this codebase's existing
    derived-field convention for invoice status/balance. `Shop.status`
    (pilot/active/suspended/cancelled) is the actual access-gate cache,
    updated whenever that recomputation changes it.

    `seat_limit` is a snapshot taken when the tier was selected, not a
    live lookup against `SUBSCRIPTION_TIERS` -- so a future price/limit
    change to the tier table never silently changes what an existing
    subscriber already agreed to.
    """

    __tablename__ = "shop_subscriptions"
    __table_args__ = (
        UniqueConstraint("shop_id", name="uq_shop_subscriptions_shop_id"),
        CheckConstraint(
            "tier IN ('solo', 'team', 'shop')",
            name="ck_shop_subscriptions_tier",
        ),
        CheckConstraint(
            "billing_status IN ('trialing', 'active', 'past_due', 'canceled')",
            name="ck_shop_subscriptions_billing_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id", ondelete="CASCADE"), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    billing_status: Mapped[str] = mapped_column(String(20), nullable=False)
    seat_limit: Mapped[int | None] = mapped_column()
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    grace_period_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    square_customer_id: Mapped[str | None] = mapped_column(String(120))
    square_card_id: Mapped[str | None] = mapped_column(String(120))
    square_subscription_id: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    shop: Mapped[Shop] = relationship(back_populates="subscription")
