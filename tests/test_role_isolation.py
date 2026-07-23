from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.main as main
from app.auth import (
    get_current_auth_context,
    hash_password,
    require_billing_context,
    require_owner_context,
    require_owner_only_context,
    require_owner_or_technician_context,
    require_support_context,
)
from app.db import get_db_session, get_settings
from app.db_models import ShopMembership, UserAccount

pytestmark = pytest.mark.anyio

# Routes that stay authenticated but reachable by any role: login is public,
# logout/me/context/chat/location are per-session or non-shop-scoped rather
# than shop-business-data, and the estimate-approval trio authenticate via a
# mailed token, not a session cookie at all.
_NOT_ROLE_GATED_ROUTES = {
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    # Self-service shop signup (/goal Phase 4) is, by definition, reachable
    # before any session/role exists at all -- own rate limiter
    # (enforce_signup_rate_limit) is the equivalent guard.
    ("POST", "/api/signup"),
    # Email verification (/goal Phase 5): the raw token is the credential,
    # same category as the estimate-approval trio below -- there is no
    # session at all when a fresh signup's link is first opened.
    ("POST", "/api/auth/verify-email"),
    # A pending authenticated account must be able to resend its own token
    # before the normal verified-account/role gates become available.
    ("POST", "/api/auth/verify-email/resend"),
    # Password recovery and invitation acceptance are public token flows;
    # the raw single-use token is the credential and each route has its own
    # public rate limit.
    ("POST", "/api/auth/password/reset-request"),
    ("POST", "/api/auth/password/reset-confirm"),
    ("POST", "/api/invitations/accept"),
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
    ("POST", "/api/test-support/concurrency-probe/reset"),
    ("GET", "/api/test-support/concurrency-probe"),
}

_AUTHENTICATED_SELF_SERVICE_ROUTES = {
    ("POST", "/api/auth/password/change"),
    ("GET", "/api/auth/sessions"),
    ("POST", "/api/auth/sessions/revoke-others"),
    ("POST", "/api/auth/sessions/{session_id}/revoke"),
    ("GET", "/api/auth/login-history"),
    ("GET", "/api/auth/security"),
    # /goal Phase 8: reachable by whichever role is currently being
    # impersonated (always "owner" by this design) -- gated by checking
    # `AuthSession.impersonated_by_user_account_id` inside the handler
    # itself, not by a role dependency, since the caller's role at this
    # point is the impersonated owner's, not "support".
    ("POST", "/api/support/end-impersonation"),
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

# /goal Phase 7: the billing surface deliberately does NOT gate on
# `require_shop_access_active` (unlike every other owner/manager route via
# `require_owner_context`) -- a suspended shop must still be able to view
# its billing status and add a payment method to restore access, or
# suspension would be permanent. Owner/manager role-gating still applies.
_BILLING_ROUTES = {
    ("GET", "/api/billing/subscription"),
    ("GET", "/api/billing/events"),
    ("POST", "/api/billing/payment-method"),
    ("POST", "/api/billing/subscribe"),
    ("POST", "/api/billing/tier"),
    ("POST", "/api/billing/cancel"),
    ("POST", "/api/billing/refresh"),
}

# /goal Phase 8: the read-only platform support directory is gated by its
# own dependency (support role only), not owner/owner-or-technician -- it
# deliberately reads across every shop, the one disclosed exception to the
# rest of this app's effective_shop_id-scoping rule.
_SUPPORT_ROUTES = {
    ("GET", "/api/support/shops"),
    ("POST", "/api/support/shops/{shop_id}/impersonate"),
    # Phase 2A: read-only host-disk / Docker-storage observability is
    # platform-infrastructure telemetry, so it is gated support-only (not
    # owner/manager/technician). It reads no shop data -- host/Docker
    # aggregates only.
    ("GET", "/api/operations/storage"),
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
            if key in _AUTHENTICATED_SELF_SERVICE_ROUTES:
                if not _dependant_uses(dependant, get_current_auth_context):
                    wrong.append(("expected authenticated self-service gate, missing", key))
                continue
            uses_owner_or_technician = _dependant_uses(
                dependant, require_owner_or_technician_context
            )
            # `require_owner_only_context` (owner-exclusive, no managers) is a
            # *stricter* owner gate than `require_owner_context` -- it still
            # satisfies the "owner-gated, never open to technicians" contract
            # this audit enforces (e.g. post-signup onboarding).
            uses_owner_only = _dependant_uses(dependant, require_owner_context) or _dependant_uses(
                dependant, require_owner_only_context
            )
            uses_billing = _dependant_uses(dependant, require_billing_context)
            uses_support = _dependant_uses(dependant, require_support_context)
            if key in _BILLING_ROUTES:
                if not uses_billing:
                    wrong.append(("expected billing gate, missing", key))
                continue
            if key in _SUPPORT_ROUTES:
                if not uses_support:
                    wrong.append(("expected support gate, missing", key))
                continue
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
    shop_id = db_session.scalar(
        select(ShopMembership.shop_id).where(
            ShopMembership.user_account_id == shop_owner_id,
            ShopMembership.role == "owner",
            ShopMembership.is_active.is_(True),
        )
    )
    assert shop_id is not None
    db_session.add(ShopMembership(shop_id=shop_id, user_account_id=user.id, role="technician"))
    db_session.commit()
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
