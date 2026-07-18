from __future__ import annotations

import httpx
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.db import build_engine
from tests.e2e.conftest import LiveServer, SyntheticCredentials


def _login_client(live_server: LiveServer, creds: SyntheticCredentials) -> httpx.Client:
    client = httpx.Client(base_url=live_server.base_url, timeout=10)
    response = client.post(
        "/api/auth/login", json={"username": creds.username, "password": creds.password}
    )
    response.raise_for_status()
    return client


def test_creating_a_customer_through_the_real_api_populates_shop_id(
    live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    """Closes the loop this /goal Phase 3 slice actually exists for: not
    just that the migrations and models are correct, but that a real
    authenticated request through the real HTTP API, against the real app
    (not a direct store-function call), results in a business-table row
    with `shop_id` genuinely set -- including for a *synthetic* owner,
    which required its own fix in this slice
    (`app/test_support_store.py::provision_synthetic_owner` now also
    calls `create_shop_for_new_owner`, since without it every synthetic
    owner would have no `ShopMembership` at all and every row they create
    would silently stay `shop_id = NULL`, unlike a bootstrapped or
    migrated real owner).
    """
    client = _login_client(live_server, synthetic_owner)
    response = client.post("/api/customers", json={"first_name": "Jane", "last_name": "Doe"})
    response.raise_for_status()
    customer_id = response.json()["id"]

    engine = build_engine(live_server.database_url)
    session = sessionmaker(bind=engine)()
    try:
        row = session.execute(
            text(
                "SELECT c.shop_id, sm.shop_id AS expected_shop_id "
                "FROM customers c "
                "JOIN user_accounts u ON u.id = c.owner_user_id "
                "JOIN shop_memberships sm ON sm.user_account_id = u.id AND sm.role = 'owner' "
                "WHERE c.id = :customer_id"
            ),
            {"customer_id": customer_id},
        ).one()
        assert row.shop_id is not None
        assert row.shop_id == row.expected_shop_id
    finally:
        session.close()
        engine.dispose()
