from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings, get_settings


class Base(DeclarativeBase):
    pass


def _sqlite_engine_kwargs(database_url: str) -> dict[str, object]:
    if not database_url.startswith("sqlite"):
        return {}
    kwargs: dict[str, object] = {"connect_args": {"check_same_thread": False}}
    if database_url.endswith(":memory:"):
        kwargs["poolclass"] = StaticPool
    return kwargs


@lru_cache(maxsize=8)
def build_engine(database_url: str) -> Engine:
    return create_engine(
        database_url,
        pool_pre_ping=True,
        future=True,
        **_sqlite_engine_kwargs(database_url),
    )


@lru_cache(maxsize=8)
def build_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(
        bind=build_engine(database_url),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        class_=Session,
    )


def get_engine(settings: Settings | None = None) -> Engine:
    resolved = settings or get_settings()
    return build_engine(resolved.database_url)


def get_db_session(
    settings: Annotated[Settings, Depends(get_settings)],
) -> Generator[Session, None, None]:
    session = build_session_factory(settings.database_url)()
    try:
        yield session
    finally:
        session.close()
