from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.main as main
from app.auth import hash_password, require_owner_context, require_owner_or_technician_context
from app.db import get_db_session, get_settings
from app.db_models import UserAccount

pytestmark = pytest.mark.anyio

# Routes that stay authenticated but reachable by any role: login is public,
# logout/me/context/chat/location are per-session or non-shop-scoped rather
# than shop-business-data, and the estimate-approval trio authenticate via a
# mailed token, not a session cookie at all.
_NOT_ROLE_GATED_ROUTES = {
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
    # Synthetic test-account provisioning (Phase 6 Part B) must work before
    # any session exists at all, so it cannot sit behind a session-based auth
    # dependency. It has its own equally strict guard instead: every route
    # 404s unless OPTIMUS_TEST_ACCOUNT_PROVISIONING is true AND app_env is
    # not "production" (see app/test_support_store.py::provisioning_enabled),
    # off by default in every real deployment including local dev and CI.
    ("POST", "/api/test-support/synthetic-owner"),
    ("POST", "/api/test-support/synthetic-technician"),
    ("DELETE", "/api/test-support/synthetic-accounts/{user_id}"),
    ("DELETE", "/api/test-support/synthetic-accounts"),
}

# Routes deliberately opened to BOTH owner and technician (Phase 5.6
# sub-phase 2) -- store-level scoping (work_order_store._work_order_query)
# still restricts a technician to only their own assigned work order rows.
# Every other business route in the app must stay strictly owner-only.
_OWNER_OR_TECHNICIAN_ROUTES = {
    ("GET", "/api/work-orders"),
    ("GET", "/api/work-orders/{work_order_id}"),
    ("POST", "/api/work-orders/{work_order_id}/status"),
    ("POST", "/api/work-orders/{work_order_id}/notes"),
    ("GET", "/api/technicians/me"),
    ("POST", "/api/technicians/me/clock-in"),
    ("POST", "/api/technicians/me/clock-out"),
    # Phase 6 Part E: a technician can create/list/view/update diagnostic
    # findings and inspections tied to their own assigned work orders
    # (store-level scoping in diagnostics_store.py/inspection_store.py, same
    # pattern as work_order_store._work_order_query). Archiving and the
    # audit-event history stay owner-only, matching assign-technician above.
    ("POST", "/api/diagnostic-findings"),
    ("GET", "/api/diagnostic-findings"),
    ("GET", "/api/diagnostic-findings/{finding_id}"),
    ("PATCH", "/api/diagnostic-findings/{finding_id}"),
    ("POST", "/api/inspections"),
    ("GET", "/api/inspections"),
    ("GET", "/api/inspections/{inspection_id}"),
    ("PATCH", "/api/inspections/{inspection_id}"),
    # Phase 6 Part F, Part Allocation slice: a technician can create/list/view
    # part allocations and record allocate/use/return actions tied to their
    # own assigned work orders (store-level scoping in
    # part_allocation_store.py, same pattern as work_order_store's). The
    # audit-event history stays owner-only, matching every other module's
    # archive/audit-history-stays-owner-only precedent above.
    ("POST", "/api/work-orders/{work_order_id}/part-allocations"),
    ("GET", "/api/work-orders/{work_order_id}/part-allocations"),
    ("GET", "/api/part-allocations/{allocation_id}"),
    ("POST", "/api/part-allocations/{allocation_id}/allocate"),
    ("POST", "/api/part-allocations/{allocation_id}/use"),
    ("POST", "/api/part-allocations/{allocation_id}/return"),
}


def _dependant_uses(dependant, target, seen: set[int] | None = None) -> bool:  # type: ignore[no-untyped-def]
    if seen is None:
        seen = set()
    if id(dependant) in seen:
        return False
    seen.add(id(dependant))
    if dependant.call is target:
        return True
    return any(_dependant_uses(sub, target, seen) for sub in dependant.dependencies)


def test_every_business_route_is_role_gated_as_expected() -> None:
    """Static audit over the live FastAPI route table: a route that forgets
    its role gate (or is wrongly opened to technicians) would silently widen
    or shrink shop-data access the moment technician logins exist. This
    catches that at the routing layer instead of relying on remembering to
    gate every future route by hand -- it inspects the real dependency graph
    FastAPI built, not a hand-maintained list of route names. Every `/api/*`
    route must be exactly one of: explicitly role-open (chat/context/etc,
    listed above), explicitly owner-or-technician (listed above), or
    strictly owner-only (the default expectation for everything else)."""
    wrong = []
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
            if key in _NOT_ROLE_GATED_ROUTES:
                continue
            uses_owner_or_technician = _dependant_uses(
                dependant, require_owner_or_technician_context
            )
            uses_owner_only = _dependant_uses(dependant, require_owner_context)
            if key in _OWNER_OR_TECHNICIAN_ROUTES:
                if not uses_owner_or_technician:
                    wrong.append(("expected owner-or-technician gate, missing", key))
            else:
                if not uses_owner_only:
                    wrong.append(("expected owner-only gate, missing", key))
                if uses_owner_or_technician:
                    wrong.append(("unexpectedly opened to technicians", key))
    assert wrong == []


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
    representative route from every strictly-owner-only gated area, gets a
    real (but empty, since nothing is assigned to them) 200 on the one area
    deliberately opened to technicians, while an owner session on the same
    routes still works. No technician-provisioning endpoint exists yet at
    this layer of the test (that's exercised separately in
    tests/test_technicians_api.py), so the technician row is inserted
    directly."""
    owner = db_session.scalar(select(UserAccount).where(UserAccount.role == "owner"))
    assert owner is not None
    _create_technician(db_session, shop_owner_id=owner.id)

    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_db_session] = lambda: db_session
    try:
        client = TestClient(main.app)
        owner_only_routes = [
            "/api/customers",
            "/api/vehicles",
            "/api/estimates",
            "/api/invoices",
            "/api/notifications",
            "/api/dashboard/summary",
            "/api/technicians",
        ]

        owner_login = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "owner-password-123"},
        )
        assert owner_login.status_code == 200
        assert owner_login.json()["user"]["role"] == "owner"
        for path in [*owner_only_routes, "/api/work-orders"]:
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

        for path in owner_only_routes:
            response = client.get(path)
            assert response.status_code == 403, (
                f"GET {path} as technician returned {response.status_code}"
            )

        # Opened to technicians, but store-scoped: this technician has no
        # assigned work orders (and no linked Technician profile at all,
        # since it was inserted directly), so the list must come back empty,
        # not error and not leak the owner's full work-order list.
        work_orders_response = client.get("/api/work-orders")
        assert work_orders_response.status_code == 200
        assert work_orders_response.json()["items"] == []
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
