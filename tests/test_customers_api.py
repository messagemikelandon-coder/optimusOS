from __future__ import annotations

import logging
from typing import TypedDict, Unpack

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import app.main as main
from app.models import CustomerCreate, CustomerUpdate
from tests.test_api import request_for
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response


class CustomerPayload(TypedDict, total=False):
    first_name: str | None
    last_name: str | None
    company_name: str | None
    email: str | None
    phone: str | None
    secondary_phone: str | None
    address_line_1: str | None
    address_line_2: str | None
    city: str | None
    state: str | None
    postal_code: str | None
    preferred_contact_method: str | None
    internal_notes: str | None


def customer_payload(**overrides: Unpack[CustomerPayload]) -> CustomerCreate:
    base: CustomerPayload = {
        "first_name": "Casey",
        "last_name": "Jones",
        "company_name": None,
        "email": "Casey.Jones@example.com",
        "phone": "(555) 123-4567",
        "secondary_phone": None,
        "address_line_1": "123 Main St",
        "address_line_2": None,
        "city": "Rocklin",
        "state": "CA",
        "postal_code": "95677",
        "preferred_contact_method": "Phone",
        "internal_notes": "Prefers afternoon appointments.",
    }
    base.update(overrides)
    return CustomerCreate(**base)


@pytest.mark.anyio
async def test_customers_require_authenticated_session(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(HTTPException) as excinfo:
        main.get_current_auth_context(request_for("/api/customers"), db_session, settings)
    assert excinfo.value.status_code == 401


@pytest.mark.anyio
async def test_create_and_retrieve_customer(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    created = await main.create_customer_record(customer_payload(), db_session, auth)
    assert created.display_name == "Casey Jones"
    assert created.email == "casey.jones@example.com"
    assert created.phone == "555-123-4567"

    fetched = await main.get_customer_record(created.id, db_session, auth)
    assert fetched.id == created.id
    assert fetched.city == "Rocklin"


@pytest.mark.anyio
async def test_update_customer(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    created = await main.create_customer_record(customer_payload(), db_session, auth)

    updated = await main.update_customer_record(
        created.id,
        CustomerUpdate(
            company_name="Landon Fleet",
            email="SERVICE@EXAMPLE.COM",
            phone="1 (916) 555-1200",
            preferred_contact_method="Email",
        ),
        db_session,
        auth,
    )
    assert updated.company_name == "Landon Fleet"
    assert updated.email == "service@example.com"
    assert updated.phone == "+1 916-555-1200"
    assert updated.preferred_contact_method == "email"


@pytest.mark.anyio
async def test_archive_customer(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    created = await main.create_customer_record(customer_payload(), db_session, auth)

    archived = await main.archive_customer_record(created.id, db_session, auth)
    assert archived.customer.is_archived is True

    active_list = await main.list_customer_records(
        db_session,
        settings,
        auth,
        page=1,
        page_size=20,
        search=None,
        archived=False,
    )
    assert active_list.items == []

    archived_list = await main.list_customer_records(
        db_session,
        settings,
        auth,
        page=1,
        page_size=20,
        search=None,
        archived=True,
    )
    assert [item.id for item in archived_list.items] == [created.id]


@pytest.mark.anyio
async def test_list_search_and_pagination(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    first = await main.create_customer_record(
        customer_payload(first_name="Avery", last_name="Stone", email="avery@example.com"),
        db_session,
        auth,
    )
    second = await main.create_customer_record(
        customer_payload(first_name="Blake", last_name="Turner", phone="9165552222"),
        db_session,
        auth,
    )
    third = await main.create_customer_record(
        customer_payload(
            first_name=None,
            last_name=None,
            company_name="Turner Logistics",
            email="dispatch@turner.test",
        ),
        db_session,
        auth,
    )

    page_one = await main.list_customer_records(
        db_session,
        settings,
        auth,
        page=1,
        page_size=2,
        search=None,
        archived=False,
    )
    page_two = await main.list_customer_records(
        db_session,
        settings,
        auth,
        page=2,
        page_size=2,
        search=None,
        archived=False,
    )
    assert [item.id for item in page_one.items] == [third.id, second.id]
    assert [item.id for item in page_two.items] == [first.id]
    assert page_one.has_more is True
    assert page_two.has_more is False

    search_name = await main.list_customer_records(
        db_session,
        settings,
        auth,
        page=1,
        page_size=20,
        search="turner",
        archived=False,
    )
    assert [item.id for item in search_name.items] == [third.id, second.id]

    search_email = await main.list_customer_records(
        db_session,
        settings,
        auth,
        page=1,
        page_size=20,
        search="DISPATCH@TURNER.TEST",
        archived=False,
    )
    assert [item.id for item in search_email.items] == [third.id]

    search_phone = await main.list_customer_records(
        db_session,
        settings,
        auth,
        page=1,
        page_size=20,
        search="9165552222",
        archived=False,
    )
    assert [item.id for item in search_phone.items] == [second.id]


def test_customer_invalid_input_is_rejected() -> None:
    with pytest.raises(ValidationError):
        customer_payload(first_name=None, last_name=None, company_name=None)


@pytest.mark.anyio
async def test_customer_endpoint_rejects_invalid_email(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    with pytest.raises(HTTPException) as excinfo:
        await main.create_customer_record(
            customer_payload(email="not-an-email"),
            db_session,
            auth,
        )
    assert excinfo.value.status_code == 422


@pytest.mark.anyio
async def test_customer_duplicate_create_is_allowed(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    first = await main.create_customer_record(customer_payload(), db_session, auth)
    second = await main.create_customer_record(customer_payload(), db_session, auth)
    assert first.id != second.id

    listed = await main.list_customer_records(
        db_session,
        settings,
        auth,
        page=1,
        page_size=20,
        search="casey",
        archived=False,
    )
    assert listed.total == 2


@pytest.mark.anyio
async def test_customer_cross_user_isolation(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    create_user(db_session, username="other", password="other-password-123")
    _, owner_response = await login_as(settings, db_session)
    _, other_response = await login_as(
        settings,
        db_session,
        username="other",
        password="other-password-123",
    )
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    created = await main.create_customer_record(customer_payload(), db_session, owner_auth)

    other_list = await main.list_customer_records(
        db_session,
        settings,
        other_auth,
        page=1,
        page_size=20,
        search=None,
        archived=False,
    )
    assert other_list.items == []

    with pytest.raises(HTTPException) as get_exc:
        await main.get_customer_record(created.id, db_session, other_auth)
    assert get_exc.value.status_code == 404

    with pytest.raises(HTTPException) as update_exc:
        await main.update_customer_record(
            created.id,
            CustomerUpdate(city="Elsewhere"),
            db_session,
            other_auth,
        )
    assert update_exc.value.status_code == 404

    with pytest.raises(HTTPException) as archive_exc:
        await main.archive_customer_record(created.id, db_session, other_auth)
    assert archive_exc.value.status_code == 404


@pytest.mark.anyio
async def test_customer_page_size_limit_is_enforced(settings, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    with pytest.raises(HTTPException) as excinfo:
        await main.list_customer_records(
            db_session,
            settings,
            auth,
            page=1,
            page_size=settings.customers_max_page_size + 1,
            search=None,
            archived=False,
        )
    assert excinfo.value.status_code == 422


@pytest.mark.anyio
async def test_customer_storage_failures_are_sanitized(
    monkeypatch, settings, db_session: Session, caplog
) -> None:  # type: ignore[no-untyped-def]
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    leaked_fragment = "customer-storage-secret-789"

    def fail_create(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        raise SQLAlchemyError(leaked_fragment)

    monkeypatch.setattr(main, "create_customer", fail_create)

    with (
        caplog.at_level(logging.WARNING, logger="optimus"),
        pytest.raises(HTTPException) as excinfo,
    ):
        await main.create_customer_record(customer_payload(), db_session, auth)
    assert excinfo.value.status_code == 503
    assert excinfo.value.detail == "Customer storage is unavailable."
    assert leaked_fragment not in caplog.text
