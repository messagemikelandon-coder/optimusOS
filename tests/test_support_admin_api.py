from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

import app.main as main
from app.auth import (
    AuthContext,
    bootstrap_support_account,
    hash_password,
    require_support_context,
)
from app.config import Settings
from app.db import get_db_session, get_settings
from app.db_models import AuthSession, Shop, ShopEvent, ShopMembership, UserAccount
from app.support_store import (
    SupportNotFoundError,
    end_shop_impersonation,
    impersonate_shop_owner,
    list_shops_for_support,
)
from tests.test_api import request_for
from tests.test_context_api import create_user

pytestmark = pytest.mark.anyio


def _support_user(db: Session) -> UserAccount:
    user = UserAccount(
        username="support-one",
        display_name="Support One",
        role="support",
        password_hash=hash_password("support-password-123"),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth_for(db: Session, user: UserAccount, suffix: str = "support") -> AuthContext:
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=f"support-{suffix}-{user.id}",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        last_seen_at=datetime.now(UTC),
    )
    db.add(auth_session)
    db.commit()
    db.refresh(auth_session)
    return AuthContext(user=user, session=auth_session)


def test_bootstrap_support_account_skipped_without_credentials(db_session: Session) -> None:
    settings = Settings(optimus_support_username="", optimus_support_password="")
    result = bootstrap_support_account(settings=settings, db=db_session)
    assert result == 1
    assert db_session.scalar(select(UserAccount).where(UserAccount.role == "support")) is None


def test_bootstrap_support_account_creates_a_shopless_support_user(db_session: Session) -> None:
    settings = Settings(
        optimus_support_username="support-bootstrap",
        optimus_support_password="a-real-support-password-123",
    )
    result = bootstrap_support_account(settings=settings, db=db_session)
    assert result == 0
    user = db_session.scalar(select(UserAccount).where(UserAccount.role == "support"))
    assert user is not None
    assert user.username == "support-bootstrap"
    assert user.is_active is True
    # Deliberately no Shop/ShopMembership -- a support account is not scoped
    # to any single shop.
    membership = db_session.scalar(
        select(ShopMembership).where(ShopMembership.user_account_id == user.id)
    )
    assert membership is None


def test_bootstrap_support_account_is_idempotent(db_session: Session) -> None:
    settings = Settings(
        optimus_support_username="support-bootstrap",
        optimus_support_password="a-real-support-password-123",
    )
    assert bootstrap_support_account(settings=settings, db=db_session) == 0
    assert bootstrap_support_account(settings=settings, db=db_session) == 0
    all_support = db_session.scalars(select(UserAccount).where(UserAccount.role == "support")).all()
    assert len(all_support) == 1


def test_require_support_context_rejects_other_roles(db_session: Session) -> None:
    owner = db_session.scalar(select(UserAccount).where(UserAccount.role == "owner"))
    assert owner is not None
    owner_auth = _auth_for(db_session, owner, "owner")
    with pytest.raises(Exception):  # noqa: B017 -- HTTPException from require_role
        require_support_context(db_session, owner_auth)

    support_user = _support_user(db_session)
    support_auth = _auth_for(db_session, support_user, "support")
    assert require_support_context(db_session, support_auth) is support_auth


def test_support_session_has_no_shop_membership_and_lists_every_shop(
    settings, db_session: Session
) -> None:
    """The whole point of the support role: it sees across every Shop, not
    just one -- the opposite of every other role in this codebase, which is
    always confined to its own Shop via effective_shop_id."""
    support_user = _support_user(db_session)
    create_user(
        db_session,
        username="second-shop-owner",
        password="second-owner-password-123",
        settings=settings,
    )

    # A support account is deliberately not scoped to any single shop.
    assert (
        db_session.scalar(
            select(ShopMembership).where(ShopMembership.user_account_id == support_user.id)
        )
        is None
    )

    directory = list_shops_for_support(db_session)
    assert len(directory.items) >= 2
    owner_names = {item.owner_display_name for item in directory.items}
    assert "Owner" in owner_names
    assert "Second-Shop-Owner" in owner_names
    for item in directory.items:
        assert item.seats_used >= 0
        assert item.subscription_tier in {"solo", "team", "shop"}


def test_support_route_end_to_end_via_real_http(settings, db_session: Session) -> None:
    support_user = _support_user(db_session)

    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_db_session] = lambda: db_session
    try:
        client = TestClient(main.app)

        owner_login = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "owner-password-123"},
        )
        assert owner_login.status_code == 200
        assert client.get("/api/support/shops").status_code == 403
        client.post("/api/auth/logout")

        support_login = client.post(
            "/api/auth/login",
            json={"username": support_user.username, "password": "support-password-123"},
        )
        assert support_login.status_code == 200
        assert support_login.json()["user"]["role"] == "support"

        me = client.get("/api/auth/me")
        assert me.status_code == 200

        directory_response = client.get("/api/support/shops")
        assert directory_response.status_code == 200
        body = directory_response.json()
        assert any(item["display_name"] for item in body["items"])

        # A support session must still 403 on every ordinary business route.
        assert client.get("/api/customers").status_code == 403
        assert client.get("/api/work-orders").status_code == 403
    finally:
        main.app.dependency_overrides.clear()


def test_directory_never_writes_even_when_a_shops_cached_status_has_drifted(
    db_session: Session,
) -> None:
    """Independent-review finding: the directory previously called
    sync_shop_access_status (which corrects Shop.status and commits a
    ShopEvent as a side effect) once per shop -- meaning a support session
    merely loading the page could write to every shop on the platform.
    list_shops_for_support must derive the same correct answer without
    writing anything."""
    _support_user(db_session)
    shop = db_session.scalar(select(Shop))
    assert shop is not None
    subscription = shop.subscription
    assert subscription is not None
    subscription.billing_status = "trialing"
    subscription.trial_ends_at = datetime.now(UTC) - timedelta(days=1)
    db_session.add(subscription)
    db_session.commit()
    assert shop.status == "active"  # stale cache: never corrected pre-read

    directory = list_shops_for_support(db_session)
    entry = next(item for item in directory.items if item.shop_id == shop.id)
    assert entry.is_access_suspended is True

    db_session.refresh(shop)
    assert shop.status == "active", "the directory must never write to Shop.status"
    assert (
        db_session.scalar(
            select(ShopEvent).where(
                ShopEvent.shop_id == shop.id,
                ShopEvent.event_type.in_(("shop_suspended", "shop_reactivated")),
            )
        )
        is None
    ), "the directory must never insert a ShopEvent as a side effect of a read"


def test_impersonate_shop_owner_mints_a_real_owner_session(
    settings: Settings, db_session: Session
) -> None:
    support_user = _support_user(db_session)
    support_auth = _auth_for(db_session, support_user, "impersonate")
    owner = db_session.scalar(select(UserAccount).where(UserAccount.role == "owner"))
    assert owner is not None
    shop = db_session.scalar(select(Shop))
    assert shop is not None

    token, auth_session, returned_owner = impersonate_shop_owner(
        db_session,
        support_auth,
        settings=settings,
        shop_id=shop.id,
        request=request_for("/api/support/shops/1/impersonate", method="POST"),
    )
    assert token
    assert returned_owner.id == owner.id
    assert auth_session.user_id == owner.id
    assert auth_session.impersonated_by_user_account_id == support_user.id
    event = db_session.scalar(
        select(ShopEvent).where(
            ShopEvent.shop_id == shop.id,
            ShopEvent.event_type == "support_impersonation_started",
        )
    )
    assert event is not None
    assert event.actor_user_account_id == support_user.id


def test_impersonate_shop_owner_rejects_a_shop_with_no_active_owner(
    settings: Settings, db_session: Session
) -> None:
    support_user = _support_user(db_session)
    support_auth = _auth_for(db_session, support_user, "impersonate-no-owner")
    shop = db_session.scalar(select(Shop))
    assert shop is not None
    db_session.execute(
        update(ShopMembership)
        .where(ShopMembership.shop_id == shop.id, ShopMembership.role == "owner")
        .values(is_active=False)
    )
    db_session.commit()

    with pytest.raises(SupportNotFoundError):
        impersonate_shop_owner(
            db_session,
            support_auth,
            settings=settings,
            shop_id=shop.id,
            request=request_for(f"/api/support/shops/{shop.id}/impersonate", method="POST"),
        )


def test_impersonate_shop_owner_ignores_a_deactivated_owner_account(
    settings: Settings, db_session: Session
) -> None:
    """Independent-review finding: _owner_for must fail closed the same way
    effective_shop_owner_id does when the membership row says "owner" but
    the underlying UserAccount is no longer a valid active owner."""
    support_user = _support_user(db_session)
    support_auth = _auth_for(db_session, support_user, "impersonate-deactivated-owner")
    owner = db_session.scalar(select(UserAccount).where(UserAccount.role == "owner"))
    assert owner is not None
    shop = db_session.scalar(select(Shop))
    assert shop is not None
    owner.is_active = False
    db_session.add(owner)
    db_session.commit()

    with pytest.raises(SupportNotFoundError):
        impersonate_shop_owner(
            db_session,
            support_auth,
            settings=settings,
            shop_id=shop.id,
            request=request_for(f"/api/support/shops/{shop.id}/impersonate", method="POST"),
        )


def test_impersonate_shop_owner_rejects_an_unknown_shop(
    settings: Settings, db_session: Session
) -> None:
    support_user = _support_user(db_session)
    support_auth = _auth_for(db_session, support_user, "impersonate-missing")
    with pytest.raises(SupportNotFoundError):
        impersonate_shop_owner(
            db_session,
            support_auth,
            settings=settings,
            shop_id=999_999,
            request=request_for("/api/support/shops/999999/impersonate", method="POST"),
        )


def test_end_impersonation_reverts_to_the_support_account(
    settings: Settings, db_session: Session
) -> None:
    support_user = _support_user(db_session)
    support_auth = _auth_for(db_session, support_user, "impersonate-end")
    owner = db_session.scalar(select(UserAccount).where(UserAccount.role == "owner"))
    assert owner is not None
    shop = db_session.scalar(select(Shop))
    assert shop is not None

    _token, impersonated_session, _owner = impersonate_shop_owner(
        db_session,
        support_auth,
        settings=settings,
        shop_id=shop.id,
        request=request_for("/api/support/shops/1/impersonate", method="POST"),
    )
    impersonated_auth = AuthContext(user=owner, session=impersonated_session)

    new_token, new_session, returned_support_user = end_shop_impersonation(
        db_session,
        impersonated_auth,
        settings=settings,
        request=request_for("/api/support/end-impersonation", method="POST"),
    )
    assert new_token
    assert returned_support_user.id == support_user.id
    assert new_session.user_id == support_user.id
    assert new_session.impersonated_by_user_account_id is None

    db_session.refresh(impersonated_session)
    assert impersonated_session.revoked_at is not None

    end_event = db_session.scalar(
        select(ShopEvent).where(
            ShopEvent.shop_id == shop.id,
            ShopEvent.event_type == "support_impersonation_ended",
        )
    )
    assert end_event is not None
    assert end_event.actor_user_account_id == support_user.id


def test_ending_impersonation_on_a_normal_session_is_rejected(
    settings: Settings, db_session: Session
) -> None:
    owner = db_session.scalar(select(UserAccount).where(UserAccount.role == "owner"))
    assert owner is not None
    owner_auth = _auth_for(db_session, owner, "not-impersonating")
    with pytest.raises(HTTPException) as excinfo:
        end_shop_impersonation(
            db_session,
            owner_auth,
            settings=settings,
            request=request_for("/api/support/end-impersonation", method="POST"),
        )
    assert excinfo.value.status_code == 422


def test_impersonate_route_rejects_a_non_support_role_via_real_http(
    settings: Settings, db_session: Session
) -> None:
    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_db_session] = lambda: db_session
    try:
        client = TestClient(main.app)
        owner_login = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "owner-password-123"},
        )
        assert owner_login.status_code == 200
        shop = db_session.scalar(select(Shop))
        assert shop is not None
        response = client.post(f"/api/support/shops/{shop.id}/impersonate")
        assert response.status_code == 403
    finally:
        main.app.dependency_overrides.clear()


def test_abandoned_impersonation_session_is_reconciled_on_next_support_request(
    settings: Settings, db_session: Session
) -> None:
    """Independent-review Finding 1: an impersonation session that merely
    expires (rather than being explicitly ended) must still leave an
    auditable end-of-access trail once the support account is next active."""
    support_user = _support_user(db_session)
    support_auth = _auth_for(db_session, support_user, "reconcile")
    shop = db_session.scalar(select(Shop))
    assert shop is not None

    token, impersonated_session, _owner = impersonate_shop_owner(
        db_session,
        support_auth,
        settings=settings,
        shop_id=shop.id,
        request=request_for(f"/api/support/shops/{shop.id}/impersonate", method="POST"),
    )
    assert token
    impersonated_session.expires_at = datetime.now(UTC) - timedelta(minutes=5)
    db_session.add(impersonated_session)
    db_session.commit()

    from app.auth import reconcile_abandoned_impersonation_sessions

    reconcile_abandoned_impersonation_sessions(db_session, support_user.id)

    db_session.refresh(impersonated_session)
    assert impersonated_session.revoked_at is not None
    expired_event = db_session.scalar(
        select(ShopEvent).where(
            ShopEvent.shop_id == shop.id,
            ShopEvent.event_type == "support_impersonation_expired",
        )
    )
    assert expired_event is not None
    assert expired_event.actor_user_account_id == support_user.id


def test_impersonation_full_cycle_via_real_http(settings: Settings, db_session: Session) -> None:
    support_user = _support_user(db_session)

    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_db_session] = lambda: db_session
    try:
        client = TestClient(main.app)

        login = client.post(
            "/api/auth/login",
            json={"username": support_user.username, "password": "support-password-123"},
        )
        assert login.status_code == 200
        assert client.get("/api/customers").status_code == 403

        shop = db_session.scalar(select(Shop))
        assert shop is not None
        impersonate = client.post(f"/api/support/shops/{shop.id}/impersonate")
        assert impersonate.status_code == 200
        assert impersonate.json()["user"]["role"] == "owner"
        assert impersonate.json()["user"]["is_impersonated"] is True
        assert impersonate.json()["user"]["impersonated_by_username"] == support_user.username

        # The minted session behaves exactly like a real owner login.
        assert client.get("/api/customers").status_code == 200

        end = client.post("/api/support/end-impersonation")
        assert end.status_code == 200
        assert end.json()["user"]["role"] == "support"
        assert end.json()["user"]["is_impersonated"] is False

        # Back to support: business routes 403 again, directory reachable.
        assert client.get("/api/customers").status_code == 403
        assert client.get("/api/support/shops").status_code == 200
    finally:
        main.app.dependency_overrides.clear()
