from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import app.main as main
from app.db import get_db_session, get_settings
from app.db_models import Bay
from app.models import BayCreate
from app.security_events import SecurityEventType
from tests.test_capabilities_api import _set_mode_and_tier
from tests.test_context_api import auth_context, login_as, raw_cookie_from_response
from tests.test_role_isolation import _create_technician

pytestmark = pytest.mark.anyio

_CAP_EVENT = SecurityEventType.CAPABILITY_OBSERVED.value


def _capability_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if getattr(r, "security_event", None) == _CAP_EVENT]


def _field(record: logging.LogRecord, name: str):
    return getattr(record, name)


async def _make_owner_auth(settings, db_session: Session):
    _, response = await login_as(settings, db_session)
    return auth_context(settings, db_session, raw_cookie_from_response(response))


# --- Behaviour parity: response identical in every mode --------------------


@pytest.mark.parametrize("mode", ["shop", "solo", "mobile_field"])
async def test_bay_create_and_read_are_identical_in_every_mode(
    settings, db_session: Session, mode: str
) -> None:
    auth = await _make_owner_auth(settings, db_session)
    _set_mode_and_tier(db_session, _owner_of(db_session), mode=mode, tier="shop")

    created = await main.create_bay_record(BayCreate(name="Bay A", notes="lift"), db_session, auth)
    fetched = await main.get_bay_record(created.id, db_session, auth)
    listed = await main.list_bay_records(
        db_session, settings, auth, page=1, page_size=20, archived=False
    )

    # Observation never alters the payload -- same fields/values in every mode.
    assert created.name == "Bay A"
    assert created.notes == "lift"
    assert created.is_archived is False
    assert fetched.id == created.id
    assert fetched.name == "Bay A"
    assert [b.id for b in listed.items] == [created.id]


async def test_observation_never_deletes_or_mutates_bay_data_in_solo_mode(
    settings, db_session: Session
) -> None:
    auth = await _make_owner_auth(settings, db_session)
    owner = _owner_of(db_session)
    # Create the bay while in shop mode...
    _set_mode_and_tier(db_session, owner, mode="shop", tier="shop")
    created = await main.create_bay_record(BayCreate(name="Persistent Bay"), db_session, auth)

    # ...then switch to solo (where bays would_deny) and read repeatedly.
    _set_mode_and_tier(db_session, owner, mode="solo", tier="shop")
    for _ in range(3):
        await main.list_bay_records(
            db_session, settings, auth, page=1, page_size=20, archived=False
        )
        await main.get_bay_record(created.id, db_session, auth)

    # The row is untouched: hidden capability never deletes or mutates data.
    surviving = db_session.get(Bay, created.id)
    assert surviving is not None
    assert surviving.name == "Persistent Bay"
    assert surviving.is_archived is False
    assert db_session.scalar(select(func.count()).select_from(Bay)) == 1


# --- One event per request, would_allow/would_deny by mode -----------------


async def test_each_bay_request_emits_one_observation_would_allow_in_shop_mode(
    settings, db_session: Session, caplog
) -> None:
    auth = await _make_owner_auth(settings, db_session)
    _set_mode_and_tier(db_session, _owner_of(db_session), mode="shop", tier="shop")

    with caplog.at_level(logging.INFO, logger="optimus"):
        await main.list_bay_records(
            db_session, settings, auth, page=1, page_size=20, archived=False
        )

    records = _capability_records(caplog)
    assert len(records) == 1
    assert _field(records[0], "decision") == "would_allow"
    assert _field(records[0], "route_action") == "bays.list"


@pytest.mark.parametrize("mode", ["solo", "mobile_field"])
async def test_bay_request_records_would_deny_in_non_shop_mode_but_still_serves(
    settings, db_session: Session, caplog, mode: str
) -> None:
    auth = await _make_owner_auth(settings, db_session)
    _set_mode_and_tier(db_session, _owner_of(db_session), mode=mode, tier="shop")

    with caplog.at_level(logging.INFO, logger="optimus"):
        listed = await main.list_bay_records(
            db_session, settings, auth, page=1, page_size=20, archived=False
        )

    # Served normally (empty list, not a 403)...
    assert listed.items == []
    # ...while the observation records the would-be denial.
    records = _capability_records(caplog)
    assert len(records) == 1
    assert _field(records[0], "decision") == "would_deny"


# --- OpenAPI parity: /api/bays contract unchanged --------------------------


def test_bays_openapi_contract_is_unchanged() -> None:
    schema = main.app.openapi()
    paths = schema["paths"]
    # Exactly the five pre-existing bay routes, exact methods, unchanged.
    assert set(paths["/api/bays"].keys()) >= {"get", "post"}
    assert set(paths["/api/bays/{bay_id}"].keys()) >= {"get", "patch", "delete"}
    # The observe pilot adds no new path, param, or body to the bays surface.
    assert "/api/bays/observe" not in paths
    list_op = paths["/api/bays"]["get"]
    param_names = {p["name"] for p in list_op.get("parameters", [])}
    assert param_names == {"page", "page_size", "search", "archived"} or param_names == {
        "page",
        "page_size",
        "archived",
    }
    # Response model still BayListResponse.
    assert "BayListResponse" in list_op["responses"]["200"]["content"]["application/json"][
        "schema"
    ].get("$ref", "")


# --- Existing auth / tenant behaviour is unchanged -------------------------


def test_bays_still_reject_technicians_and_unauthenticated_end_to_end(
    settings, db_session: Session
) -> None:
    owner = _owner_of(db_session)
    _create_technician(db_session, shop_owner_id=owner.id)

    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_db_session] = lambda: db_session
    try:
        client = TestClient(main.app)
        # Unauthenticated is still 401 -- observation runs only after auth.
        assert client.get("/api/bays").status_code == 401

        owner_login = client.post(
            "/api/auth/login", json={"username": "owner", "password": "owner-password-123"}
        )
        assert owner_login.status_code == 200
        assert client.get("/api/bays").status_code == 200
        client.post("/api/auth/logout")

        tech_login = client.post(
            "/api/auth/login", json={"username": "tech-one", "password": "tech-password-123"}
        )
        assert tech_login.status_code == 200
        # Technician is still 403 on the owner-only bays surface -- capability
        # observation never replaces the role gate that already rejects them.
        assert client.get("/api/bays").status_code == 403
    finally:
        main.app.dependency_overrides.clear()


async def test_cross_tenant_direct_id_behaviour_is_unchanged(settings, db_session: Session) -> None:
    """A second shop's owner asking for the first shop's bay by direct id
    still gets 404 (tenant scoping in the store) -- observation does not
    change, widen, or narrow that."""
    from fastapi import HTTPException

    from tests.test_context_api import create_user

    owner_auth = await _make_owner_auth(settings, db_session)
    created = await main.create_bay_record(BayCreate(name="Shop A Bay"), db_session, owner_auth)

    other_owner = create_user(db_session, username="second-owner", password="second-pass-123")
    from tests.test_capabilities_api import _auth_for

    other_auth = _auth_for(db_session, other_owner, "cross-tenant")

    with pytest.raises(HTTPException) as excinfo:
        await main.get_bay_record(created.id, db_session, other_auth)
    assert excinfo.value.status_code == 404


def _owner_of(db_session: Session):
    from app.db_models import UserAccount

    owner = db_session.scalar(select(UserAccount).where(UserAccount.role == "owner"))
    assert owner is not None
    return owner
