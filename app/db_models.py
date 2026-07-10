from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
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
    __table_args__ = (UniqueConstraint("username", name="uq_user_accounts_username"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(120), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="owner")
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
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

    user: Mapped[UserAccount] = relationship(back_populates="sessions")
    context_entries: Mapped[list[ContextEntry]] = relationship(back_populates="auth_session")


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
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
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
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
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
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
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
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
            "'sent', 'approved', 'declined', 'expired', 'superseded', 'archived', 'internal_recorded'"
            ")",
            name="ck_estimate_approval_events_type",
        ),
        Index(
            "ix_estimate_approval_events_estimate_created",
            "estimate_id",
            "created_at",
        ),
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
        UniqueConstraint(
            "estimate_id",
            "estimate_revision_id",
            name="uq_work_orders_estimate_revision",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
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
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
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
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
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
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
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
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
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
