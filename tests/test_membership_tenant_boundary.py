from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.main as main
from app.auth import AuthContext, effective_shop_id, hash_password, require_owner_context
from app.config import Settings
from app.context_store import list_entries, upsert_entry
from app.customer_store import create_customer, list_customers
from app.db import get_db_session, get_settings
from app.db_models import AuthSession, ContextEntry, Customer, Shop, ShopMembership, UserAccount
from app.models import ContextScope, CustomerCreate
from app.shop_store import create_shop_for_new_owner


def _auth_for(db: Session, user: UserAccount) -> AuthContext:
    session = AuthSession(
        user_id=user.id,
        token_hash=f"membership-boundary-{user.id}",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return AuthContext(user=user, session=session)


def test_manager_uses_membership_shop_even_when_legacy_owner_pointer_is_wrong(
    settings: Settings, db_session: Session
) -> None:
    first_owner = db_session.scalar(select(UserAccount).where(UserAccount.role == "owner"))
    assert first_owner is not None
    first_membership = db_session.scalar(
        select(ShopMembership).where(ShopMembership.user_account_id == first_owner.id)
    )
    assert first_membership is not None

    other_owner = UserAccount(
        username="other-owner",
        display_name="Other Owner",
        role="owner",
        password_hash=hash_password("other-owner-password-123"),
        is_active=True,
    )
    db_session.add(other_owner)
    db_session.flush()
    create_shop_for_new_owner(
        db_session,
        settings,
        other_owner,
        display_name="Other Shop",
        created_via="tenant-boundary-test",
    )
    db_session.commit()

    manager = UserAccount(
        username="shop-manager",
        display_name="Shop Manager",
        role="manager",
        # Deliberately corrupt compatibility data. Authorization must ignore it.
        shop_owner_id=other_owner.id,
        password_hash=hash_password("manager-password-123"),
        is_active=True,
    )
    db_session.add(manager)
    db_session.flush()
    db_session.add(
        ShopMembership(
            shop_id=first_membership.shop_id,
            user_account_id=manager.id,
            role="manager",
        )
    )
    db_session.commit()

    auth = _auth_for(db_session, manager)
    assert effective_shop_id(db_session, auth) == first_membership.shop_id
    assert require_owner_context(auth) is auth

    created = create_customer(
        db=db_session,
        auth=auth,
        payload=CustomerCreate(first_name="Membership", last_name="Scoped"),
    )
    listed = list_customers(
        db=db_session,
        auth=auth,
        settings=settings,
        page=1,
        page_size=20,
        archived=False,
        search=None,
    )
    assert [customer.id for customer in listed.items] == [created.id]
    stored = db_session.get(Customer, created.id)
    assert stored is not None
    assert stored.shop_id == first_membership.shop_id
    assert stored.owner_user_id == first_owner.id

    context = upsert_entry(
        db=db_session,
        auth=auth,
        settings=settings,
        project_key="tenant-boundary",
        scope=ContextScope.PROJECT,
        context_key="shop-note",
        value="belongs to the membership shop",
        expected_revision=None,
    )
    stored_context = db_session.get(ContextEntry, context.id)
    assert stored_context is not None
    assert stored_context.user_id == first_owner.id
    other_auth = _auth_for(db_session, other_owner)
    other_context = list_entries(
        db=db_session,
        auth=other_auth,
        settings=settings,
        project_key="tenant-boundary",
        scope=ContextScope.PROJECT,
    )
    assert other_context.entries == []

    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_db_session] = lambda: db_session
    try:
        client = TestClient(main.app)
        login = client.post(
            "/api/auth/login",
            json={"username": "shop-manager", "password": "manager-password-123"},
        )
        assert login.status_code == 200
        assert login.json()["user"]["role"] == "manager"
        response = client.get("/api/customers")
        assert response.status_code == 200
        assert [customer["id"] for customer in response.json()["items"]] == [created.id]
        assert client.get("/api/work-orders").status_code == 200
    finally:
        main.app.dependency_overrides.clear()


def test_database_allows_only_one_active_membership_per_account(db_session: Session) -> None:
    owner = db_session.scalar(select(UserAccount).where(UserAccount.role == "owner"))
    assert owner is not None
    membership = db_session.scalar(
        select(ShopMembership).where(ShopMembership.user_account_id == owner.id)
    )
    assert membership is not None

    other_shop = Shop(display_name="Second Membership Target", status="active")
    db_session.add(other_shop)
    db_session.flush()

    db_session.add(
        ShopMembership(
            shop_id=other_shop.id,
            user_account_id=owner.id,
            role="manager",
            is_active=True,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_store_authorization_queries_do_not_compare_legacy_owner_user_id() -> None:
    violations: list[str] = []
    for path in sorted(Path("app").glob("*_store.py")):
        if path.name == "test_support_store.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "effective_owner_id"
            ):
                violations.append(f"{path}:{node.lineno}: {ast.unparse(node)}")
            if not isinstance(node, ast.Compare):
                continue
            if any(
                isinstance(candidate, ast.Attribute) and candidate.attr == "owner_user_id"
                for candidate in ast.walk(node)
            ):
                violations.append(f"{path}:{node.lineno}: {ast.unparse(node)}")
    assert violations == []


def test_inactive_membership_cannot_mint_a_dormant_session(
    settings: Settings, db_session: Session
) -> None:
    owner = db_session.scalar(select(UserAccount).where(UserAccount.role == "owner"))
    assert owner is not None
    membership = db_session.scalar(
        select(ShopMembership).where(ShopMembership.user_account_id == owner.id)
    )
    assert membership is not None
    membership.is_active = False
    db_session.commit()
    session_count_before = len(owner.sessions)

    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_db_session] = lambda: db_session
    try:
        client = TestClient(main.app)
        response = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "owner-password-123"},
        )
        assert response.status_code == 403
        db_session.refresh(owner)
        assert len(owner.sessions) == session_count_before
    finally:
        main.app.dependency_overrides.clear()
