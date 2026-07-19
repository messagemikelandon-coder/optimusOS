from __future__ import annotations

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from app.account_security_store import (
    InvitationConflictError,
    PasswordResetTokenError,
    accept_invitation,
    confirm_password_reset,
    request_password_reset,
)
from app.auth import AuthContext
from app.config import Settings
from app.db import build_session_factory
from app.db_models import (
    AuthSession,
    PasswordResetToken,
    ShopInvitation,
    ShopMembership,
    Technician,
    UserAccount,
)
from app.models import ShopInvitationAccept, TechnicianProvisionLoginRequest
from app.services.email import EmailMessage
from app.technician_store import TechnicianConflictError, provision_login
from tests.e2e.conftest import LiveServer, SyntheticCredentials


class NoopEmailAdapter:
    def send(self, message: EmailMessage) -> None:
        del message


def test_successful_login_bounds_session_metadata_on_postgres(
    live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    with httpx.Client(base_url=live_server.base_url, timeout=10) as client:
        response = client.post(
            "/api/auth/login",
            json={
                "username": synthetic_owner.username,
                "password": synthetic_owner.password,
            },
            headers={"user-agent": "x" * 2000},
        )
    assert response.status_code == 200

    with build_session_factory(live_server.database_url)() as db:
        auth_session = db.scalar(
            select(AuthSession)
            .where(AuthSession.user_id == synthetic_owner.user_id)
            .order_by(AuthSession.id.desc())
            .limit(1)
        )
        assert auth_session is not None
        assert auth_session.user_agent == "x" * 512


def test_reset_request_and_confirmation_use_consistent_lock_order(
    live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    """Real PostgreSQL concurrency proof for the user->token lock order.

    Request and confirmation may race to revoke/use the same token, so either
    semantic outcome is valid; both workers must complete without deadlock or
    a raw database exception.
    """
    session_factory = build_session_factory(live_server.database_url)
    raw_token = "account-lifecycle-concurrent-reset-token"
    with session_factory() as db:
        owner = db.get(UserAccount, synthetic_owner.user_id)
        assert owner is not None
        owner.email = f"concurrent.{owner.id}@example.com"
        owner.email_normalized = owner.email
        owner.email_verified_at = datetime.now(UTC)
        db.add(owner)
        db.add(
            PasswordResetToken(
                user_account_id=owner.id,
                token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
                status="active",
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
            )
        )
        db.commit()

    barrier = threading.Barrier(2)

    def request_worker() -> str:
        with session_factory() as db:
            barrier.wait(timeout=5)
            request_password_reset(
                db,
                Settings(password_reset_token_ttl_minutes=30),
                f"concurrent.{synthetic_owner.user_id}@example.com",
                NoopEmailAdapter(),
            )
            return "requested"

    def confirm_worker() -> str:
        with session_factory() as db:
            barrier.wait(timeout=5)
            try:
                confirm_password_reset(db, raw_token, "concurrent-new-password-123")
            except PasswordResetTokenError:
                return "revoked-before-confirm"
            return "confirmed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        request_future = executor.submit(request_worker)
        confirm_future = executor.submit(confirm_worker)
        assert request_future.result(timeout=10) == "requested"
        assert confirm_future.result(timeout=10) in {"confirmed", "revoked-before-confirm"}


def test_invitation_acceptance_and_direct_provision_lock_technician_profile(
    live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    session_factory = build_session_factory(live_server.database_url)
    raw_token = "concurrent-technician-invitation-token"
    email = f"concurrent-tech-{synthetic_owner.user_id}@example.com"
    with session_factory() as db:
        owner = db.get(UserAccount, synthetic_owner.user_id)
        assert owner is not None
        membership = db.scalar(
            select(ShopMembership).where(ShopMembership.user_account_id == owner.id)
        )
        assert membership is not None
        owner_session = AuthSession(
            user_id=owner.id,
            token_hash=f"concurrent-provision-{owner.id}",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            last_seen_at=datetime.now(UTC),
        )
        profile = Technician(
            owner_user_id=owner.id,
            shop_id=membership.shop_id,
            first_name="Concurrent",
            last_name="Technician",
            email=email,
            email_normalized=email,
        )
        invitation = ShopInvitation(
            shop_id=membership.shop_id,
            email=email,
            email_normalized=email,
            role="technician",
            invited_by_user_account_id=owner.id,
            token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db.add_all((owner_session, profile, invitation))
        db.commit()
        owner_session_id = owner_session.id
        profile_id = profile.id

    barrier = threading.Barrier(2)

    def accept_worker() -> str:
        with session_factory() as db:
            barrier.wait(timeout=5)
            try:
                accept_invitation(
                    db,
                    ShopInvitationAccept(
                        token=raw_token,
                        display_name="Concurrent Invited Technician",
                        username="concurrent-invited-technician",
                        password="concurrent-invited-password-123",
                    ),
                )
            except InvitationConflictError:
                return "accept-conflict"
            return "accepted"

    def provision_worker() -> str:
        with session_factory() as db:
            owner = db.get(UserAccount, synthetic_owner.user_id)
            owner_session = db.get(AuthSession, owner_session_id)
            assert owner is not None and owner_session is not None
            barrier.wait(timeout=5)
            try:
                provision_login(
                    db=db,
                    auth=AuthContext(user=owner, session=owner_session),
                    technician_id=profile_id,
                    payload=TechnicianProvisionLoginRequest(
                        username="concurrent-provisioned-technician",
                        password="concurrent-provisioned-password-123",
                    ),
                )
            except TechnicianConflictError:
                return "provision-conflict"
            return "provisioned"

    with ThreadPoolExecutor(max_workers=2) as executor:
        accept_future = executor.submit(accept_worker)
        provision_future = executor.submit(provision_worker)
        results = {
            accept_future.result(timeout=10),
            provision_future.result(timeout=10),
        }

    assert results in (
        {"accepted", "provision-conflict"},
        {"accept-conflict", "provisioned"},
    )
    with session_factory() as db:
        profile = db.get(Technician, profile_id)
        assert profile is not None and profile.user_account_id is not None
        users = db.scalars(
            select(UserAccount).where(
                UserAccount.username.in_(
                    ("concurrent-invited-technician", "concurrent-provisioned-technician")
                )
            )
        ).all()
        assert [user.id for user in users] == [profile.user_account_id]
