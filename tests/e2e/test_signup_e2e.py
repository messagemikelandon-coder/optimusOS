from __future__ import annotations

import httpx

from tests.e2e.conftest import LiveServer


def test_signup_creates_a_real_shop_and_logs_in_via_the_real_api(live_server: LiveServer) -> None:
    """Real HTTP request against the real app + real Postgres (no browser
    UI involved -- /goal Phase 4 ships the backend signup route first; a
    frontend form is a follow-up). Proves the full chain works end to
    end: a brand-new shop/owner is created, a real session cookie is
    issued, and that cookie authenticates a real subsequent request."""
    client = httpx.Client(base_url=live_server.base_url, timeout=10)
    response = client.post(
        "/api/signup",
        json={
            "business_name": "Rivera Auto Repair",
            "owner_display_name": "Alex Rivera",
            "username": f"alex.rivera.{id(client)}",
            "email": f"alex.rivera.{id(client)}@example.com",
            "password": "a-real-password-123",
        },
    )
    response.raise_for_status()
    body = response.json()
    assert body["user"]["role"] == "owner"
    assert "optimus_session" in response.cookies

    me_response = client.get("/api/auth/me")
    me_response.raise_for_status()
    assert me_response.json()["user"]["id"] == body["user"]["id"]

    customer_response = client.post(
        "/api/customers", json={"first_name": "Real", "last_name": "Customer"}
    )
    customer_response.raise_for_status()
    assert customer_response.json()["first_name"] == "Real"
