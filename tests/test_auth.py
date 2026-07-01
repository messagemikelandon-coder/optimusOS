from __future__ import annotations

from fastapi import Response
from sqlalchemy import select

from app.auth import bootstrap_owner_account, hash_session_token
from app.db import Base, build_engine, build_session_factory
from app.db_models import AuthSession, UserAccount
from app.main import login
from app.models import AuthLoginRequest
from tests.test_api import request_for


def test_bootstrap_owner_is_idempotent(settings) -> None:  # type: ignore[no-untyped-def]
    engine = build_engine(settings.database_url)
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = build_session_factory(settings.database_url)()
    try:
        assert bootstrap_owner_account(settings=settings, db=session) == 0
        assert bootstrap_owner_account(settings=settings, db=session) == 0
        owners = session.scalars(select(UserAccount)).all()
        assert len(owners) == 1
        assert owners[0].username == "owner"
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


async def test_session_hash_matches_database_record(settings, db_session) -> None:  # type: ignore[no-untyped-def]
    response = Response()
    payload = await login(
        AuthLoginRequest(username="owner", password="owner-password-123"),
        request_for("/api/auth/login", method="POST"),
        response,
        db_session,
        settings,
    )
    assert payload.user.username == "owner"
    raw_token = response.headers["set-cookie"].split("optimus_session=", 1)[1].split(";", 1)[0]
    assert raw_token

    stored_session = db_session.scalar(select(AuthSession))
    assert stored_session is not None
    assert stored_session.token_hash == hash_session_token(raw_token)
    assert stored_session.token_hash != raw_token
