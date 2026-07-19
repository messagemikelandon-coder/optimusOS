from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings

# Pinned so Square-side API evolution cannot silently change request/response
# semantics between deploys.
SQUARE_API_VERSION = "2025-05-21"

_BASE_URLS = {
    "sandbox": "https://connect.squareupsandbox.com",
    "production": "https://connect.squareup.com",
}


class SquareApiError(RuntimeError):
    """Sanitized Square failure: carries HTTP status and Square error codes,
    never the access token or raw request headers."""

    def __init__(self, *, status_code: int, codes: list[str]) -> None:
        self.status_code = status_code
        self.codes = codes
        super().__init__(f"Square API call failed ({status_code}): {', '.join(codes) or 'unknown'}")


class _SquareClient:
    """Shared connection/request plumbing for every Square REST client in
    this codebase. Mirrors OptimusChatService's injectable-client shape:
    tests pass a stub `client`, production builds a real httpx.Client
    lazily."""

    def __init__(self, settings: Settings, client: httpx.Client | Any | None = None) -> None:
        if not settings.square_configured and client is None:
            raise RuntimeError("Square is not configured.")
        self._settings = settings
        # Only close what we created; injected test stubs stay caller-owned.
        self._owns_client = client is None
        if client is not None:
            self._client = client
        else:
            self._client = httpx.Client(
                base_url=_BASE_URLS[settings.square_environment],
                timeout=httpx.Timeout(settings.square_timeout_seconds),
                trust_env=False,
                headers={
                    "Authorization": f"Bearer {settings.square_access_token}",
                    "Square-Version": SQUARE_API_VERSION,
                    "Content-Type": "application/json",
                },
            )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = self._client.request(method, path, json=payload)
        body: dict[str, Any]
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400:
            codes = [
                str(error.get("code", "unknown"))
                for error in body.get("errors", [])
                if isinstance(error, dict)
            ]
            raise SquareApiError(status_code=response.status_code, codes=codes)
        return body


class SquareInvoiceClient(_SquareClient):
    """Thin dict-in/dict-out client for the six Square REST calls this phase
    needs."""

    def search_customer_by_email(self, email: str) -> dict[str, Any] | None:
        body = self._request(
            "POST",
            "/v2/customers/search",
            {"query": {"filter": {"email_address": {"exact": email}}}},
        )
        customers = body.get("customers") or []
        return customers[0] if customers else None

    def create_customer(
        self,
        *,
        idempotency_key: str,
        given_name: str,
        email: str,
        phone: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "idempotency_key": idempotency_key,
            "given_name": given_name,
            "email_address": email,
        }
        if phone:
            payload["phone_number"] = phone
        return self._request("POST", "/v2/customers", payload)["customer"]

    def create_order(
        self,
        *,
        idempotency_key: str,
        location_id: str,
        reference_id: str,
        line_name: str,
        amount_cents: int,
        currency: str = "USD",
    ) -> dict[str, Any]:
        payload = {
            "idempotency_key": idempotency_key,
            "order": {
                "location_id": location_id,
                "reference_id": reference_id,
                # One aggregate line item so the Square total always equals our
                # Decimal invoice total exactly -- no per-line rounding drift.
                "line_items": [
                    {
                        "name": line_name,
                        "quantity": "1",
                        "base_price_money": {"amount": amount_cents, "currency": currency},
                    }
                ],
            },
        }
        return self._request("POST", "/v2/orders", payload)["order"]

    def create_invoice(
        self,
        *,
        idempotency_key: str,
        location_id: str,
        order_id: str,
        customer_id: str,
        title: str,
        description: str,
        payment_requests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = {
            "idempotency_key": idempotency_key,
            "invoice": {
                "location_id": location_id,
                "order_id": order_id,
                "primary_recipient": {"customer_id": customer_id},
                "title": title[:255],
                "description": description[:65535],
                "delivery_method": "EMAIL",
                "accepted_payment_methods": {"card": True},
                "payment_requests": payment_requests,
            },
        }
        return self._request("POST", "/v2/invoices", payload)["invoice"]

    def publish_invoice(
        self, *, square_invoice_id: str, version: int, idempotency_key: str
    ) -> dict[str, Any]:
        payload = {"version": version, "idempotency_key": idempotency_key}
        return self._request("POST", f"/v2/invoices/{square_invoice_id}/publish", payload)[
            "invoice"
        ]

    def get_invoice(self, square_invoice_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v2/invoices/{square_invoice_id}")["invoice"]


class SquareSubscriptionClient(_SquareClient):
    """Square Subscriptions REST calls for billing a *shop's* own OptimusOS
    subscription (distinct from `SquareInvoiceClient`, which bills a shop's
    customers). Reuses `search_customer_by_email`/`create_customer`'s exact
    request shape rather than duplicating a second customer-creation path --
    a Square Customer created here is a real record of the shop owner, not
    a customer of the shop."""

    def search_customer_by_email(self, email: str) -> dict[str, Any] | None:
        body = self._request(
            "POST",
            "/v2/customers/search",
            {"query": {"filter": {"email_address": {"exact": email}}}},
        )
        customers = body.get("customers") or []
        return customers[0] if customers else None

    def create_customer(
        self, *, idempotency_key: str, given_name: str, email: str
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v2/customers",
            {
                "idempotency_key": idempotency_key,
                "given_name": given_name,
                "email_address": email,
            },
        )["customer"]

    def create_card(
        self, *, idempotency_key: str, source_id: str, customer_id: str
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v2/cards",
            {
                "idempotency_key": idempotency_key,
                "source_id": source_id,
                "card": {"customer_id": customer_id},
            },
        )["card"]

    def create_subscription(
        self,
        *,
        idempotency_key: str,
        location_id: str,
        customer_id: str,
        card_id: str,
        plan_variation_id: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v2/subscriptions",
            {
                "idempotency_key": idempotency_key,
                "location_id": location_id,
                "customer_id": customer_id,
                "card_id": card_id,
                "plan_variation_id": plan_variation_id,
            },
        )["subscription"]

    def cancel_subscription(self, square_subscription_id: str) -> dict[str, Any]:
        return self._request("POST", f"/v2/subscriptions/{square_subscription_id}/cancel", {})[
            "subscription"
        ]

    def get_subscription(self, square_subscription_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v2/subscriptions/{square_subscription_id}")["subscription"]
