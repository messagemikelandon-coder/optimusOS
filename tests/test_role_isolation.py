from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.main as main
from app.auth import hash_password, require_owner_context
from app.db import get_db_session, get_settings
from app.db_models import UserAccount

pytestmark = pytest.mark.anyio

# Routes that stay authenticated-but-not-owner-gated in sub-phase 1: login is
# public, logout/me/context/chat/location are per-session or non-shop-scoped
# rather than shop-business-data, and the estimate-approval trio authenticate
# via a mailed token, not a session cookie at all.
_NOT_OWNER_GATED_ROUTES = {
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("GET", "/api/auth/me"),
    ("GET", "/api/context/{project_key}"),
    ("PUT", "/api/context/{project_key}/{context_key}"),
    ("DELETE", "/api/context/{project_key}/{context_key}"),
    ("POST", "/api/location/resolve"),
    ("POST", "/api/chat"),
    ("POST", "/api/estimate-approval/view"),
    ("POST", "/api/estimate-approval/approve"),
    ("POST", "/api/estimate-approval/decline"),
}


def _dependant_uses_require_owner_context(dependant, seen: set[int] | None = None) -> bool:  # type: ignore[no-untyped-def]
    if seen is None:
        seen = set()
    if id(dependant) in seen:
        return False
    seen.add(id(dependant))
    if dependant.call is require_owner_context:
        return True
    return any(_dependant_uses_require_owner_context(sub, seen) for sub in dependant.dependencies)


def test_every_business_route_is_owner_gated() -> None:
    """Static audit over the live FastAPI route table: a route that forgets
    `OwnerAuthContextDep` would silently hand a technician full shop access
    the moment technician logins exist (Phase 5.6 sub-phase 2). This catches
    that at the routing layer instead of relying on remembering to gate every
    future route by hand -- it inspects the real dependency graph FastAPI
    built, not a hand-maintained list of route names."""
    unchecked = []
    for route in main.app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        dependant = getattr(route, "dependant", None)
        if not path or not methods or not path.startswith("/api/") or dependant is None:
            continue
        for method in methods:
            if method == "HEAD":
                continue
            key = (method, path)
            if key in _NOT_OWNER_GATED_ROUTES:
                continue
            if not _dependant_uses_require_owner_context(dependant):
                unchecked.append(key)
    assert unchecked == []


def _create_technician(db_session: Session, *, shop_owner_id: int) -> UserAccount:
    user = UserAccount(
        username="tech-one",
        display_name="Tech One",
        role="technician",
        shop_owner_id=shop_owner_id,
        password_hash=hash_password("tech-password-123"),
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_technician_session_is_rejected_on_owner_only_routes_end_to_end(
    settings, db_session: Session
) -> None:
    """Real HTTP requests through the actual FastAPI dependency graph (not
    direct handler calls, which would bypass `Depends()` entirely and prove
    nothing) confirming a technician session is turned away with 403 on a
    representative route from every gated area, while an owner session on the
    same routes still works. No technician-provisioning endpoint exists yet
    (that's sub-phase 2), so the technician row is inserted directly."""
    owner = db_session.scalar(select(UserAccount).where(UserAccount.role == "owner"))
    assert owner is not None
    _create_technician(db_session, shop_owner_id=owner.id)

    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_db_session] = lambda: db_session
    try:
        client = TestClient(main.app)
        sample_routes = [
            "/api/customers",
            "/api/vehicles",
            "/api/estimates",
            "/api/work-orders",
            "/api/invoices",
            "/api/notifications",
            "/api/dashboard/summary",
        ]

        owner_login = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "owner-password-123"},
        )
        assert owner_login.status_code == 200
        assert owner_login.json()["user"]["role"] == "owner"
        for path in sample_routes:
            response = client.get(path)
            assert response.status_code == 200, (
                f"GET {path} as owner returned {response.status_code}"
            )
        client.post("/api/auth/logout")

        tech_login = client.post(
            "/api/auth/login",
            json={"username": "tech-one", "password": "tech-password-123"},
        )
        assert tech_login.status_code == 200
        assert tech_login.json()["user"]["role"] == "technician"

        me = client.get("/api/auth/me")
        assert me.status_code == 200
        assert me.json()["user"]["role"] == "technician"

        for path in sample_routes:
            response = client.get(path)
            assert response.status_code == 403, (
                f"GET {path} as technician returned {response.status_code}"
            )
    finally:
        main.app.dependency_overrides.clear()


def test_role_column_rejects_unknown_values_at_the_database_level(db_session: Session) -> None:
    """Defense in depth below the application layer: even a bug that skips
    every Python-side role check can't insert a role outside the two known
    values, on SQLite (tests) or Postgres (real deployments) alike."""
    bogus = UserAccount(
        username="bogus-role",
        display_name="Bogus",
        role="service_advisor",
        password_hash=hash_password("whatever-password-123"),
        is_active=True,
    )
    db_session.add(bogus)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_effective_owner_id_rejects_technician_with_no_shop_owner() -> None:
    """A technician row inserted without `shop_owner_id` (a data-integrity
    slip, since no provisioning endpoint exists yet to enforce it) must fail
    closed with 403, not silently scope to nobody or raise an unhandled
    AttributeError deep inside a store module."""
    from fastapi import HTTPException

    from app.auth import AuthContext, effective_owner_id

    orphan = UserAccount(
        id=999,
        username="orphan-tech",
        display_name="Orphan Tech",
        role="technician",
        shop_owner_id=None,
        password_hash="unused",
        is_active=True,
    )

    class _FakeSession:
        id = 1

    with pytest.raises(HTTPException) as excinfo:
        effective_owner_id(AuthContext(user=orphan, session=_FakeSession()))  # type: ignore[arg-type]
    assert excinfo.value.status_code == 403
