from __future__ import annotations

import logging
from typing import TypedDict, Unpack

import pytest
from fastapi import HTTPException, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main as main
from app.db_models import Shop, ShopMembership, UserAccount
from app.models import CustomerCreate, ShopSignupRequest
from tests.test_api import request_for
from tests.test_context_api import auth_context, raw_cookie_from_response

pytestmark = pytest.mark.anyio


class SignupPayload(TypedDict, total=False):
    business_name: str
    owner_display_name: str
    username: str
    email: str
    password: str


def signup_payload(**overrides: Unpack[SignupPayload]) -> ShopSignupRequest:
    base: SignupPayload = {
        "business_name": "Rivera Auto Repair",
        "owner_display_name": "Alex Rivera",
        "username": "alex.rivera",
        "email": "alex.rivera@example.com",
        "password": "a-real-password-123",
    }
    base.update(overrides)
    return ShopSignupRequest(**base)


async def signup(
    settings, db_session: Session, **overrides: Unpack[SignupPayload]
) -> tuple[dict, Response]:
    response = Response()
    payload = await main.signup(
        signup_payload(**overrides),
        request_for("/api/signup", method="POST"),
        response,
        db_session,
        settings,
    )
    return payload.model_dump(mode="json"), response


async def test_signup_creates_shop_owner_and_logs_in(settings, db_session: Session) -> None:
    payload, response = await signup(settings, db_session)
    assert payload["user"]["role"] == "owner"
    assert payload["user"]["username"] == "alex.rivera"

    owner = db_session.scalar(select(UserAccount).where(UserAccount.username == "alex.rivera"))
    assert owner is not None
    assert owner.email == "alex.rivera@example.com"
    assert owner.email_normalized == "alex.rivera@example.com"

    membership = db_session.scalar(
        select(ShopMembership).where(ShopMembership.user_account_id == owner.id)
    )
    assert membership is not None
    assert membership.role == "owner"
    shop = db_session.get(Shop, membership.shop_id)
    assert shop is not None
    assert shop.display_name == "Rivera Auto Repair"

    # The session cookie from signup works for a real subsequent request,
    # exactly like a normal login would.
    raw_cookie = raw_cookie_from_response(response)
    auth = auth_context(settings, db_session, raw_cookie)
    assert auth.user.id == owner.id


async def test_signup_email_is_normalized_case_insensitively(settings, db_session: Session) -> None:
    await signup(settings, db_session, email="Alex.Rivera@Example.COM")
    owner = db_session.scalar(select(UserAccount).where(UserAccount.username == "alex.rivera"))
    assert owner is not None
    assert owner.email == "Alex.Rivera@Example.COM"
    assert owner.email_normalized == "alex.rivera@example.com"


async def test_signup_rejects_duplicate_username(settings, db_session: Session) -> None:
    await signup(settings, db_session)
    with pytest.raises(HTTPException) as excinfo:
        await signup(settings, db_session, email="someone.else@example.com")
    assert excinfo.value.status_code == 409


async def test_signup_rejects_duplicate_email_case_insensitively(
    settings, db_session: Session
) -> None:
    await signup(settings, db_session)
    with pytest.raises(HTTPException) as excinfo:
        await signup(
            settings,
            db_session,
            username="someone.else",
            email="ALEX.RIVERA@EXAMPLE.COM",
        )
    assert excinfo.value.status_code == 409


async def test_signup_rejects_invalid_email_format(settings, db_session: Session) -> None:
    with pytest.raises(HTTPException) as excinfo:
        await signup(settings, db_session, email="not-an-email")
    assert excinfo.value.status_code == 422


async def test_signup_rejects_weak_password() -> None:
    with pytest.raises(ValidationError):
        signup_payload(password="short")


async def test_signup_rate_limit_returns_429_after_threshold(
    settings, db_session: Session, caplog
) -> None:
    limited_settings = settings.model_copy(update={"max_signup_attempts_per_minute": 2})
    for index in range(2):
        await signup(
            limited_settings, db_session, username=f"owner{index}", email=f"o{index}@example.com"
        )

    with (
        caplog.at_level(logging.WARNING, logger="optimus"),
        pytest.raises(HTTPException) as excinfo,
    ):
        await signup(
            limited_settings, db_session, username="owner-blocked", email="blocked@example.com"
        )
    assert excinfo.value.status_code == 429
    assert "security event: rate_limit.exceeded" in caplog.text


async def test_two_signed_up_shops_are_fully_isolated_from_each_other(
    settings, db_session: Session
) -> None:
    _first_payload, first_response = await signup(
        settings, db_session, username="first.owner", email="first@example.com"
    )
    first_auth = auth_context(settings, db_session, raw_cookie_from_response(first_response))

    _second_payload, second_response = await signup(
        settings,
        db_session,
        business_name="Second Shop",
        owner_display_name="Second Owner",
        username="second.owner",
        email="second@example.com",
    )
    second_auth = auth_context(settings, db_session, raw_cookie_from_response(second_response))

    first_customer = await main.create_customer_record(
        CustomerCreate(first_name="First", last_name="Customer"), db_session, first_auth
    )
    second_customer = await main.create_customer_record(
        CustomerCreate(first_name="Second", last_name="Customer"), db_session, second_auth
    )

    first_list = await main.list_customer_records(
        db_session, settings, first_auth, page=1, page_size=20, search=None, archived=False
    )
    second_list = await main.list_customer_records(
        db_session, settings, second_auth, page=1, page_size=20, search=None, archived=False
    )
    assert [item.id for item in first_list.items] == [first_customer.id]
    assert [item.id for item in second_list.items] == [second_customer.id]

    with pytest.raises(HTTPException) as excinfo:
        await main.get_customer_record(second_customer.id, db_session, first_auth)
    assert excinfo.value.status_code == 404

    first_owner = db_session.scalar(
        select(UserAccount).where(UserAccount.username == "first.owner")
    )
    second_owner = db_session.scalar(
        select(UserAccount).where(UserAccount.username == "second.owner")
    )
    assert first_owner is not None
    assert second_owner is not None
    first_membership = db_session.scalar(
        select(ShopMembership).where(ShopMembership.user_account_id == first_owner.id)
    )
    second_membership = db_session.scalar(
        select(ShopMembership).where(ShopMembership.user_account_id == second_owner.id)
    )
    assert first_membership is not None
    assert second_membership is not None
    assert first_membership.shop_id != second_membership.shop_id
