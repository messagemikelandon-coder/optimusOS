from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.main as main
from app.config import Settings
from app.db_models import Invoice, InvoicePayment
from app.services.square import SquareApiError
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
from tests.test_payments_api import create_completed_work_order_with_invoice, issue


class StubSquareClient:
    """Offline stand-in recording every call; canned Square-shaped payloads."""

    def __init__(
        self,
        *,
        existing_customer: bool = False,
        fail_at: str | None = None,
        invoice_status: str = "UNPAID",
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.existing_customer = existing_customer
        self.fail_at = fail_at
        self.invoice_status = invoice_status
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def _maybe_fail(self, step: str) -> None:
        if self.fail_at == step:
            raise SquareApiError(status_code=400, codes=["INVALID_REQUEST_ERROR"])

    def search_customer_by_email(self, email: str) -> dict[str, Any] | None:
        self.calls.append(("search_customer", {"email": email}))
        self._maybe_fail("search_customer")
        if self.existing_customer:
            return {"id": "SQ-CUST-EXISTING"}
        return None

    def create_customer(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_customer", kwargs))
        self._maybe_fail("create_customer")
        return {"id": "SQ-CUST-NEW"}

    def create_order(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_order", kwargs))
        self._maybe_fail("create_order")
        return {"id": "SQ-ORDER-1"}

    def create_invoice(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_invoice", kwargs))
        self._maybe_fail("create_invoice")
        return {"id": "SQ-INV-1", "version": 0, "status": "DRAFT"}

    def publish_invoice(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("publish_invoice", kwargs))
        self._maybe_fail("publish_invoice")
        return {
            "id": "SQ-INV-1",
            "status": self.invoice_status,
            "public_url": "https://squareupsandbox.com/pay/SQ-INV-1",
        }

    def get_invoice(self, square_invoice_id: str) -> dict[str, Any]:
        self.calls.append(("get_invoice", {"square_invoice_id": square_invoice_id}))
        self._maybe_fail("get_invoice")
        return {
            "id": square_invoice_id,
            "status": self.invoice_status,
            "public_url": "https://squareupsandbox.com/pay/SQ-INV-1",
        }


def configure_square(settings: Settings) -> None:
    settings.square_access_token = "sandbox-test-token"
    settings.square_location_id = "L123"
    settings.square_environment = "sandbox"


def install_stub(monkeypatch, stub: StubSquareClient) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(main, "SquareInvoiceClient", lambda settings: stub)


async def issued_invoice_for(monkeypatch, settings, db_session, auth, **vehicle_overrides):  # type: ignore[no-untyped-def]
    _, invoice = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth, **vehicle_overrides
    )
    return await issue(invoice.id, db_session, settings, auth)


def set_snapshot_email(db_session: Session, invoice_id: int, email: str | None) -> None:
    invoice = db_session.get(Invoice, invoice_id)
    assert invoice is not None
    snapshot = dict(invoice.customer_snapshot)
    if email is None:
        snapshot.pop("email", None)
    else:
        snapshot["email"] = email
    invoice.customer_snapshot = snapshot
    db_session.add(invoice)
    db_session.commit()


@pytest.mark.anyio
async def test_square_push_rejected_when_unconfigured(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    assert settings.square_configured is False
    with pytest.raises(HTTPException) as excinfo:
        await main.push_invoice_to_square_record(1, db_session, settings, auth)
    assert excinfo.value.status_code == 503


@pytest.mark.anyio
async def test_square_production_environment_is_structurally_disabled(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    configure_square(settings)
    settings.square_environment = "production"
    assert settings.square_configured is False
    with pytest.raises(HTTPException) as excinfo:
        await main.push_invoice_to_square_record(1, db_session, settings, auth)
    assert excinfo.value.status_code == 503


@pytest.mark.anyio
async def test_square_push_happy_path_with_new_customer(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    issued = await issued_invoice_for(monkeypatch, settings, db_session, auth)
    set_snapshot_email(db_session, issued.id, "casey@example.com")
    configure_square(settings)
    stub = StubSquareClient(existing_customer=False)
    install_stub(monkeypatch, stub)

    result = await main.push_invoice_to_square_record(issued.id, db_session, settings, auth)

    assert result.square_invoice_id == "SQ-INV-1"
    assert result.square_status == "UNPAID"
    assert result.square_payment_url == "https://squareupsandbox.com/pay/SQ-INV-1"
    steps = [name for name, _ in stub.calls]
    assert steps == [
        "search_customer",
        "create_customer",
        "create_order",
        "create_invoice",
        "publish_invoice",
    ]
    order_kwargs = dict(stub.calls[2][1])
    expected_cents = int((Decimal(str(issued.invoice_total)) * 100).to_integral_value())
    assert order_kwargs["amount_cents"] == expected_cents
    assert order_kwargs["location_id"] == "L123"
    # Persisted, not just serialized.
    row = db_session.get(Invoice, issued.id)
    assert row is not None and row.square_invoice_id == "SQ-INV-1"
    # The route must release the client even on success (leak regression guard).
    assert stub.closed is True


@pytest.mark.anyio
async def test_square_push_reuses_existing_customer(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    issued = await issued_invoice_for(monkeypatch, settings, db_session, auth)
    set_snapshot_email(db_session, issued.id, "casey@example.com")
    configure_square(settings)
    stub = StubSquareClient(existing_customer=True)
    install_stub(monkeypatch, stub)

    await main.push_invoice_to_square_record(issued.id, db_session, settings, auth)

    steps = [name for name, _ in stub.calls]
    assert "create_customer" not in steps
    invoice_kwargs = dict(stub.calls[-2][1])
    assert invoice_kwargs["customer_id"] == "SQ-CUST-EXISTING"


@pytest.mark.anyio
async def test_square_push_rejects_draft_invoice(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    _, draft = await create_completed_work_order_with_invoice(
        monkeypatch, settings, db_session, auth
    )
    set_snapshot_email(db_session, draft.id, "casey@example.com")
    configure_square(settings)
    install_stub(monkeypatch, StubSquareClient())

    with pytest.raises(HTTPException) as excinfo:
        await main.push_invoice_to_square_record(draft.id, db_session, settings, auth)
    assert excinfo.value.status_code == 422


@pytest.mark.anyio
async def test_square_push_requires_customer_email(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    issued = await issued_invoice_for(monkeypatch, settings, db_session, auth)
    set_snapshot_email(db_session, issued.id, None)
    configure_square(settings)
    stub = StubSquareClient()
    install_stub(monkeypatch, stub)

    with pytest.raises(HTTPException) as excinfo:
        await main.push_invoice_to_square_record(issued.id, db_session, settings, auth)
    assert excinfo.value.status_code == 422
    assert stub.calls == []


@pytest.mark.anyio
async def test_square_second_push_conflicts(monkeypatch, settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    issued = await issued_invoice_for(monkeypatch, settings, db_session, auth)
    set_snapshot_email(db_session, issued.id, "casey@example.com")
    configure_square(settings)
    install_stub(monkeypatch, StubSquareClient())

    await main.push_invoice_to_square_record(issued.id, db_session, settings, auth)
    with pytest.raises(HTTPException) as excinfo:
        await main.push_invoice_to_square_record(issued.id, db_session, settings, auth)
    assert excinfo.value.status_code == 409


@pytest.mark.anyio
async def test_square_publish_failure_persists_nothing(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    issued = await issued_invoice_for(monkeypatch, settings, db_session, auth)
    set_snapshot_email(db_session, issued.id, "casey@example.com")
    configure_square(settings)
    install_stub(monkeypatch, StubSquareClient(fail_at="publish_invoice"))

    with pytest.raises(HTTPException) as excinfo:
        await main.push_invoice_to_square_record(issued.id, db_session, settings, auth)
    assert excinfo.value.status_code == 502
    row = db_session.get(Invoice, issued.id)
    assert row is not None
    assert row.square_invoice_id is None
    assert row.square_status is None
    assert row.square_payment_url is None


@pytest.mark.anyio
async def test_square_refresh_updates_status(monkeypatch, settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    issued = await issued_invoice_for(monkeypatch, settings, db_session, auth)
    set_snapshot_email(db_session, issued.id, "casey@example.com")
    configure_square(settings)
    stub = StubSquareClient()
    install_stub(monkeypatch, stub)
    await main.push_invoice_to_square_record(issued.id, db_session, settings, auth)

    stub.invoice_status = "PAID"
    refreshed = await main.refresh_square_invoice_record(issued.id, db_session, settings, auth)
    assert refreshed.square_status == "PAID"

    # Refresh before push is a 422, not a Square call.
    other = await issued_invoice_for(
        monkeypatch, settings, db_session, auth, vin="5YJ3E1EA7KF400001"
    )
    with pytest.raises(HTTPException) as excinfo:
        await main.refresh_square_invoice_record(other.id, db_session, settings, auth)
    assert excinfo.value.status_code == 422


@pytest.mark.anyio
async def test_square_never_touches_local_payment_ledger(
    monkeypatch, settings, db_session: Session
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    issued = await issued_invoice_for(monkeypatch, settings, db_session, auth)
    set_snapshot_email(db_session, issued.id, "casey@example.com")
    configure_square(settings)
    stub = StubSquareClient(invoice_status="PAID")
    install_stub(monkeypatch, stub)

    await main.push_invoice_to_square_record(issued.id, db_session, settings, auth)
    await main.refresh_square_invoice_record(issued.id, db_session, settings, auth)

    payment_rows = db_session.scalar(
        select(func.count())
        .select_from(InvoicePayment)
        .where(InvoicePayment.invoice_id == issued.id)
    )
    assert payment_rows == 0
    # Local status derivation ignores Square: still unpaid locally.
    detail = await main.get_invoice_record(issued.id, db_session, auth)
    assert detail.total_paid == 0.0
    assert detail.square_status == "PAID"


@pytest.mark.anyio
async def test_square_cross_user_isolation(monkeypatch, settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    issued = await issued_invoice_for(monkeypatch, settings, db_session, auth)
    set_snapshot_email(db_session, issued.id, "casey@example.com")
    configure_square(settings)
    install_stub(monkeypatch, StubSquareClient())

    create_user(db_session, username="square-other", password="other-password-123")
    _, other_response = await login_as(
        settings, db_session, username="square-other", password="other-password-123"
    )
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    with pytest.raises(HTTPException) as push_excinfo:
        await main.push_invoice_to_square_record(issued.id, db_session, settings, other_auth)
    assert push_excinfo.value.status_code == 404
    with pytest.raises(HTTPException) as refresh_excinfo:
        await main.refresh_square_invoice_record(issued.id, db_session, settings, other_auth)
    assert refresh_excinfo.value.status_code == 404


def test_settings_repr_never_contains_square_token() -> None:
    settings = Settings(
        openai_api_key="k",
        optimus_owner_username="owner",
        optimus_owner_password="pw",
        square_access_token="super-secret-square-token",
        square_location_id="L123",
    )
    assert "super-secret-square-token" not in repr(settings)
    assert "super-secret-square-token" not in str(settings)
