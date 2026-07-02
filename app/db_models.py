from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
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
