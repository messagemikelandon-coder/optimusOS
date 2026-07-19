from __future__ import annotations

from typing import TypedDict, Unpack

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

import app.main as main
from app.auth import AuthContext, hash_password
from app.db_models import UserAccount
from app.models import (
    EstimatePaymentOptionCode,
    TechnicianCreate,
    TechnicianProvisionLoginRequest,
    TechnicianUpdate,
    WorkOrderAssignTechnicianRequest,
    WorkOrderStatus,
    WorkOrderStatusUpdate,
)
from app.technician_store import TechnicianStoreError, provision_login
from tests.test_api import request_for
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
from tests.test_work_orders_api import create_approved_estimate_for_auth

pytestmark = pytest.mark.anyio


class TechnicianPayload(TypedDict, total=False):
    first_name: str | None
    last_name: str | None
    phone: str | None
    email: str | None
    employment_status: str | None
    job_title: str | None
    hourly_cost: float | None


def technician_payload(**overrides: Unpack[TechnicianPayload]) -> TechnicianCreate:
    base: TechnicianPayload = {
        "first_name": "Jordan",
        "last_name": "Reyes",
        "phone": "(555) 987-6543",
        "email": "Jordan.Reyes@example.com",
        "employment_status": "Full-time",
        "job_title": "Master Technician",
        "hourly_cost": 28.5,
    }
    base.update(overrides)
    return TechnicianCreate(**base)


async def test_technicians_require_authenticated_session(settings, db_session: Session) -> None:
    with pytest.raises(HTTPException) as excinfo:
        main.get_current_auth_context(request_for("/api/technicians"), db_session, settings)
    assert excinfo.value.status_code == 401


async def test_create_and_retrieve_technician(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    created = await main.create_technician_record(technician_payload(), db_session, auth)
    assert created.display_name == "Jordan Reyes"
    assert created.email == "jordan.reyes@example.com"
    assert created.phone == "555-987-6543"
    assert created.has_login is False
    assert created.is_clocked_in is False
    assert created.comeback_count == 0

    fetched = await main.get_technician_record(created.id, db_session, auth)
    assert fetched.id == created.id
    assert fetched.job_title == "Master Technician"


async def test_update_technician(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    created = await main.create_technician_record(technician_payload(), db_session, auth)

    updated = await main.update_technician_record(
        created.id,
        TechnicianUpdate(job_title="Shop Foreman", hourly_cost=32.0),
        db_session,
        auth,
    )
    assert updated.job_title == "Shop Foreman"
    assert updated.hourly_cost == 32.0
    assert updated.first_name == "Jordan"


async def test_archive_technician(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    created = await main.create_technician_record(technician_payload(), db_session, auth)

    archived = await main.archive_technician_record(created.id, db_session, auth)
    assert archived.technician.is_archived is True

    active_list = await main.list_technician_records(
        db_session, settings, auth, page=1, page_size=20, search=None, archived=False
    )
    assert active_list.items == []

    archived_list = await main.list_technician_records(
        db_session, settings, auth, page=1, page_size=20, search=None, archived=True
    )
    assert [item.id for item in archived_list.items] == [created.id]


async def test_list_search_and_pagination(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    first = await main.create_technician_record(
        technician_payload(first_name="Avery", last_name="Stone", email="avery@example.com"),
        db_session,
        auth,
    )
    second = await main.create_technician_record(
        technician_payload(first_name="Blake", last_name="Turner", job_title="Apprentice"),
        db_session,
        auth,
    )

    page_one = await main.list_technician_records(
        db_session, settings, auth, page=1, page_size=1, search=None, archived=False
    )
    assert [item.id for item in page_one.items] == [second.id]
    assert page_one.has_more is True

    search = await main.list_technician_records(
        db_session, settings, auth, page=1, page_size=20, search="apprentice", archived=False
    )
    assert [item.id for item in search.items] == [second.id]

    search_email = await main.list_technician_records(
        db_session, settings, auth, page=1, page_size=20, search="AVERY@EXAMPLE.COM", archived=False
    )
    assert [item.id for item in search_email.items] == [first.id]


def test_technician_invalid_input_is_rejected() -> None:
    with pytest.raises(ValidationError):
        technician_payload(first_name=None, last_name=None)


async def test_technician_cross_owner_isolation(settings, db_session: Session) -> None:
    create_user(db_session, username="other-owner", password="other-password-123")
    _, owner_response = await login_as(settings, db_session)
    _, other_response = await login_as(
        settings, db_session, username="other-owner", password="other-password-123"
    )
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    created = await main.create_technician_record(technician_payload(), db_session, owner_auth)

    other_list = await main.list_technician_records(
        db_session, settings, other_auth, page=1, page_size=20, search=None, archived=False
    )
    assert other_list.items == []

    with pytest.raises(HTTPException) as get_exc:
        await main.get_technician_record(created.id, db_session, other_auth)
    assert get_exc.value.status_code == 404


async def test_technician_page_size_limit_is_enforced(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    with pytest.raises(HTTPException) as excinfo:
        await main.list_technician_records(
            db_session,
            settings,
            auth,
            page=1,
            page_size=settings.customers_max_page_size + 1,
            search=None,
            archived=False,
        )
    assert excinfo.value.status_code == 422


async def _provision_and_login(
    settings, db_session: Session, auth: AuthContext, technician_id: int, *, username: str
) -> AuthContext:
    await main.provision_technician_login_record(
        technician_id,
        TechnicianProvisionLoginRequest(username=username, password="tech-login-pass-123"),
        db_session,
        auth,
    )
    _, response = await login_as(
        settings, db_session, username=username, password="tech-login-pass-123"
    )
    return auth_context(settings, db_session, raw_cookie_from_response(response))


async def test_provision_login_success_and_technician_can_log_in(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    created = await main.create_technician_record(technician_payload(), db_session, owner_auth)

    tech_auth = await _provision_and_login(
        settings, db_session, owner_auth, created.id, username="jordan.reyes"
    )
    assert tech_auth.user.role == "technician"

    refreshed = await main.get_technician_record(created.id, db_session, owner_auth)
    assert refreshed.has_login is True

    me = await main.get_my_technician_record(db_session, tech_auth)
    assert me.technician.id == created.id
    assert me.recent_time_entries == []
    assert me.assigned_work_order_ids == []
    assert "hourly_cost" not in type(me.technician).model_fields, (
        "hourly_cost is an owner-visible wage/cost field and must never appear on the"
        " technician's own self-service view"
    )


async def test_provision_login_rejects_double_provisioning(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    created = await main.create_technician_record(technician_payload(), db_session, owner_auth)
    await _provision_and_login(
        settings, db_session, owner_auth, created.id, username="jordan.reyes"
    )

    with pytest.raises(HTTPException) as excinfo:
        await main.provision_technician_login_record(
            created.id,
            TechnicianProvisionLoginRequest(username="jordan-again", password="another-pass-123"),
            db_session,
            owner_auth,
        )
    assert excinfo.value.status_code == 409


async def test_provision_login_rejects_duplicate_username(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    first = await main.create_technician_record(
        technician_payload(first_name="Alex"), db_session, owner_auth
    )
    second = await main.create_technician_record(
        technician_payload(first_name="Sam", last_name="Reyes"), db_session, owner_auth
    )
    await _provision_and_login(settings, db_session, owner_auth, first.id, username="shared-name")

    with pytest.raises(HTTPException) as excinfo:
        await main.provision_technician_login_record(
            second.id,
            TechnicianProvisionLoginRequest(username="shared-name", password="another-pass-123"),
            db_session,
            owner_auth,
        )
    assert excinfo.value.status_code == 409


def test_provision_login_rejects_a_password_shorter_than_eight_characters() -> None:
    """Regression test (found while building /goal Phase 4's signup
    endpoint): `NonBlank = Field(min_length=8, ...)` never actually
    enforced 8 characters here -- see the identical regression test on
    `AuthLoginRequest` in `tests/test_auth.py` for the full root-cause
    explanation. Fixed by the same `Password` type. This must keep
    failing."""
    with pytest.raises(ValidationError):
        TechnicianProvisionLoginRequest(username="jordan.reyes", password="short")


async def test_provision_login_rejects_chained_non_owner_shop_owner_id(
    settings, db_session: Session
) -> None:
    """Sub-phase 1's security review finding, exercised directly: even if a
    technician `AuthContext` somehow reached `provision_login` (impossible
    via the real route today, since it's owner-gated), the function itself
    must refuse to provision under a `shop_owner_id` that doesn't resolve to
    a real owner row -- proving the defense-in-depth check actually works,
    not just that the route gate happens to prevent the scenario today."""
    _, response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    owner = db_session.get(UserAccount, owner_auth.user.id)
    assert owner is not None

    # A technician chained to another technician instead of a real owner --
    # the exact scenario the security review flagged as needing a guard.
    chained_technician_user = UserAccount(
        username="chained-technician",
        display_name="Chained Technician",
        role="technician",
        shop_owner_id=None,
        password_hash=hash_password("irrelevant-pass-123"),
        is_active=True,
    )
    db_session.add(chained_technician_user)
    db_session.commit()
    db_session.refresh(chained_technician_user)

    fake_auth = AuthContext(user=chained_technician_user, session=owner_auth.session)
    # Simulate the chain: this technician's shop_owner_id points at another
    # technician, not the real owner.
    another_technician_user = UserAccount(
        username="another-technician",
        display_name="Another Technician",
        role="technician",
        shop_owner_id=owner.id,
        password_hash=hash_password("irrelevant-pass-123"),
        is_active=True,
    )
    db_session.add(another_technician_user)
    db_session.commit()
    db_session.refresh(another_technician_user)
    chained_technician_user.shop_owner_id = another_technician_user.id
    db_session.add(chained_technician_user)
    db_session.commit()

    target = await main.create_technician_record(technician_payload(), db_session, owner_auth)

    with pytest.raises(TechnicianStoreError):
        provision_login(
            db=db_session,
            auth=fake_auth,
            technician_id=target.id,
            payload=TechnicianProvisionLoginRequest(
                username="should-not-provision", password="whatever-pass-123"
            ),
        )


async def test_clock_in_and_clock_out_flow(settings, db_session: Session) -> None:
    _, response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(response))
    created = await main.create_technician_record(technician_payload(), db_session, owner_auth)
    tech_auth = await _provision_and_login(
        settings, db_session, owner_auth, created.id, username="jordan.reyes"
    )

    clocked_in = await main.clock_in_record(db_session, tech_auth)
    assert clocked_in.is_clocked_in is True
    assert clocked_in.entry.clock_out_at is None

    with pytest.raises(HTTPException) as double_in:
        await main.clock_in_record(db_session, tech_auth)
    assert double_in.value.status_code == 409

    clocked_out = await main.clock_out_record(db_session, tech_auth)
    assert clocked_out.is_clocked_in is False
    assert clocked_out.entry.duration_minutes is not None

    with pytest.raises(HTTPException) as double_out:
        await main.clock_out_record(db_session, tech_auth)
    assert double_out.value.status_code == 409

    me = await main.get_my_technician_record(db_session, tech_auth)
    assert me.technician.is_clocked_in is False
    assert len(me.recent_time_entries) == 1


async def test_technician_sees_only_own_assigned_work_order(
    monkeypatch, settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    _, assigned_estimate = await create_approved_estimate_for_auth(
        monkeypatch,
        settings,
        db_session,
        owner_auth,
        payment_option=EstimatePaymentOptionCode.PAY_IN_FULL,
    )
    assigned_work_order = await main.create_work_order_record(
        assigned_estimate.id, db_session, owner_auth
    )
    _, other_estimate = await create_approved_estimate_for_auth(
        monkeypatch,
        settings,
        db_session,
        owner_auth,
        payment_option=EstimatePaymentOptionCode.PAY_IN_FULL,
        vin="2HGFC2F59JH500011",
    )
    other_work_order = await main.create_work_order_record(
        other_estimate.id, db_session, owner_auth
    )

    technician = await main.create_technician_record(technician_payload(), db_session, owner_auth)
    tech_auth = await _provision_and_login(
        settings, db_session, owner_auth, technician.id, username="jordan.reyes"
    )
    await main.assign_work_order_technician_record(
        assigned_work_order.id,
        WorkOrderAssignTechnicianRequest(technician_id=technician.id),
        db_session,
        owner_auth,
    )

    listed = await main.list_work_order_records(
        db_session,
        settings,
        tech_auth,
        page=1,
        page_size=20,
        status_filter=None,
        search=None,
        customer_id=None,
        vehicle_id=None,
    )
    assert [item.id for item in listed.items] == [assigned_work_order.id]

    fetched = await main.get_work_order_record(assigned_work_order.id, db_session, tech_auth)
    assert fetched.id == assigned_work_order.id
    assert fetched.assigned_technician_id == technician.id

    with pytest.raises(HTTPException) as excinfo:
        await main.get_work_order_record(other_work_order.id, db_session, tech_auth)
    assert excinfo.value.status_code == 404

    updated = await main.update_work_order_status_record(
        assigned_work_order.id,
        WorkOrderStatusUpdate(status=WorkOrderStatus.SCHEDULED),
        db_session,
        tech_auth,
    )
    assert updated.status is WorkOrderStatus.SCHEDULED
    # PATCH (general edit) stays owner-only even for a technician's own
    # assigned work order -- proven at the routing layer by
    # tests/test_role_isolation.py's static dependency-graph audit, not
    # re-tested here.


async def test_assign_technician_validates_same_owner(
    monkeypatch, settings, db_session: Session
) -> None:
    create_user(db_session, username="other-owner", password="other-password-123")
    _, owner_response = await login_as(settings, db_session)
    _, other_response = await login_as(
        settings, db_session, username="other-owner", password="other-password-123"
    )
    owner_auth = auth_context(settings, db_session, raw_cookie_from_response(owner_response))
    other_auth = auth_context(settings, db_session, raw_cookie_from_response(other_response))

    _, estimate = await create_approved_estimate_for_auth(
        monkeypatch, settings, db_session, owner_auth
    )
    work_order = await main.create_work_order_record(estimate.id, db_session, owner_auth)
    other_technician = await main.create_technician_record(
        technician_payload(), db_session, other_auth
    )

    with pytest.raises(HTTPException) as excinfo:
        await main.assign_work_order_technician_record(
            work_order.id,
            WorkOrderAssignTechnicianRequest(technician_id=other_technician.id),
            db_session,
            owner_auth,
        )
    assert excinfo.value.status_code == 422
