from __future__ import annotations

from typing import TypedDict, Unpack

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

import app.main as main
from app.models import PartCreate, PartUpdate, VendorCreate, VendorUpdate
from tests.test_api import request_for
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response

pytestmark = pytest.mark.anyio


class VendorPayload(TypedDict, total=False):
    name: str
    contact_name: str | None
    phone: str | None
    email: str | None


def vendor_payload(**overrides: Unpack[VendorPayload]) -> VendorCreate:
    base: VendorPayload = {
        "name": "AutoZone Commercial",
        "contact_name": "Pat Rivera",
        "phone": "(555) 222-3344",
        "email": "Pat.Rivera@example.com",
    }
    base.update(overrides)
    return VendorCreate(**base)


class PartPayload(TypedDict, total=False):
    part_number: str
    description: str
    quantity_on_hand: int
    reorder_threshold: int | None
    unit_cost: float | None
    unit_price: float | None
    vendor_id: int | None


def part_payload(**overrides: Unpack[PartPayload]) -> PartCreate:
    base: PartPayload = {
        "part_number": "BP-4471",
        "description": "Front brake pad set",
        "quantity_on_hand": 4,
        "reorder_threshold": 2,
        "unit_cost": 22.50,
        "unit_price": 48.00,
    }
    base.update(overrides)
    return PartCreate(**base)


async def test_vendors_require_authenticated_session(settings, db_session: Session) -> None:
    with pytest.raises(HTTPException) as excinfo:
        main.get_current_auth_context(request_for("/api/vendors"), db_session, settings)
    assert excinfo.value.status_code == 401


async def test_create_update_and_archive_vendor(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    created = await main.create_vendor_record(vendor_payload(), db_session, auth)
    assert created.name == "AutoZone Commercial"
    assert created.email == "pat.rivera@example.com"
    assert created.part_count == 0

    updated = await main.update_vendor_record(
        created.id, VendorUpdate(contact_name="Jamie Cole"), db_session, auth
    )
    assert updated.contact_name == "Jamie Cole"
    assert updated.name == "AutoZone Commercial"

    archived = await main.archive_vendor_record(created.id, db_session, auth)
    assert archived.vendor.is_archived is True

    active_list = await main.list_vendor_records(
        db_session, settings, auth, page=1, page_size=20, search=None, archived=False
    )
    assert active_list.items == []


async def test_vendor_cross_owner_isolation(settings, db_session: Session) -> None:
    create_user(db_session, username="other-owner", password="other-password-123")
    _, owner_response = await login_as(settings, db_session)
    _, other_response = await login_as(
        settings, db_session, username="other-owner", password="other-password-123"
    )
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    created = await main.create_vendor_record(vendor_payload(), db_session, owner_auth)

    other_list = await main.list_vendor_records(
        db_session, settings, other_auth, page=1, page_size=20, search=None, archived=False
    )
    assert other_list.items == []

    with pytest.raises(HTTPException) as excinfo:
        await main.get_vendor_record(created.id, db_session, other_auth)
    assert excinfo.value.status_code == 404


async def test_create_part_with_vendor_and_reorder_flag(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    vendor = await main.create_vendor_record(vendor_payload(), db_session, auth)

    created = await main.create_part_record(
        part_payload(vendor_id=vendor.id, quantity_on_hand=1, reorder_threshold=2),
        db_session,
        auth,
    )
    assert created.vendor_id == vendor.id
    assert created.vendor_name == "AutoZone Commercial"
    assert created.is_below_reorder_threshold is True

    vendor_after = await main.get_vendor_record(vendor.id, db_session, auth)
    assert vendor_after.part_count == 1

    updated = await main.update_part_record(
        created.id, PartUpdate(quantity_on_hand=10), db_session, auth
    )
    assert updated.is_below_reorder_threshold is False


async def test_part_rejects_unknown_vendor(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    with pytest.raises(HTTPException) as excinfo:
        await main.create_part_record(part_payload(vendor_id=999999), db_session, auth)
    assert excinfo.value.status_code == 422


async def test_part_cross_owner_isolation(settings, db_session: Session) -> None:
    create_user(db_session, username="other-owner", password="other-password-123")
    _, owner_response = await login_as(settings, db_session)
    _, other_response = await login_as(
        settings, db_session, username="other-owner", password="other-password-123"
    )
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    created = await main.create_part_record(part_payload(), db_session, owner_auth)

    other_list = await main.list_part_records(
        db_session,
        settings,
        other_auth,
        page=1,
        page_size=20,
        search=None,
        archived=False,
        vendor_id=None,
        below_reorder_threshold_only=False,
    )
    assert other_list.items == []

    with pytest.raises(HTTPException) as excinfo:
        await main.get_part_record(created.id, db_session, other_auth)
    assert excinfo.value.status_code == 404


async def test_part_list_pagination_and_search(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    first = await main.create_part_record(
        part_payload(part_number="OF-1001", description="Oil filter"), db_session, auth
    )
    second = await main.create_part_record(
        part_payload(part_number="BP-4471", description="Front brake pad set"),
        db_session,
        auth,
    )

    page_one = await main.list_part_records(
        db_session,
        settings,
        auth,
        page=1,
        page_size=1,
        search=None,
        archived=False,
        vendor_id=None,
        below_reorder_threshold_only=False,
    )
    assert [item.id for item in page_one.items] == [second.id]
    assert page_one.has_more is True

    search = await main.list_part_records(
        db_session,
        settings,
        auth,
        page=1,
        page_size=20,
        search="oil",
        archived=False,
        vendor_id=None,
        below_reorder_threshold_only=False,
    )
    assert [item.id for item in search.items] == [first.id]
