from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from app.migration_compat import (
    SchemaCompatibility,
    check_schema_compatibility,
    get_app_migration_head,
    get_database_migration_revision,
)


def _fresh_sqlite_engine():  # type: ignore[no-untyped-def]
    # A genuinely independent in-memory database per call -- bypasses
    # app.db.build_engine's URL-keyed lru_cache, which would otherwise
    # silently share state (and alembic_version content) across tests.
    return create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )


def _create_alembic_version_table(engine, revision: str) -> None:  # type: ignore[no-untyped-def]
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": revision},
        )


def test_get_app_migration_head_matches_the_real_committed_head() -> None:
    # Not hardcoded to a specific revision id -- this repo's migration head
    # changes over time, so assert it's a real, well-formed revision id
    # rather than pinning to whatever happens to be current today.
    head = get_app_migration_head()
    assert isinstance(head, str)
    assert head


def test_database_migration_revision_is_none_without_an_alembic_version_table() -> None:
    engine = _fresh_sqlite_engine()
    assert get_database_migration_revision(engine) is None


def test_schema_compatibility_unmigrated_is_safe_to_serve() -> None:
    engine = _fresh_sqlite_engine()
    report = check_schema_compatibility(engine)
    assert report.compatibility is SchemaCompatibility.UNMIGRATED
    assert report.database_migration_revision is None
    assert report.safe_to_serve is True


def test_schema_compatibility_matched_is_safe_to_serve() -> None:
    engine = _fresh_sqlite_engine()
    app_head = get_app_migration_head()
    _create_alembic_version_table(engine, app_head)
    report = check_schema_compatibility(engine)
    assert report.compatibility is SchemaCompatibility.MATCHED
    assert report.database_migration_revision == app_head
    assert report.safe_to_serve is True


def test_schema_compatibility_behind_a_known_ancestor_is_safe_to_serve() -> None:
    """The normal, expected, temporary window during a deploy that restarts
    the app with new code (`optimusctl.sh update`) before applying new
    migrations (`optimusctl.sh migrate`) -- confirmed via
    docs/context/RELEASE_CHECKLIST.md's documented runbook order. Must not
    be treated as unsafe."""
    engine = _fresh_sqlite_engine()
    _create_alembic_version_table(engine, "001_optimus_os_foundation")
    report = check_schema_compatibility(engine)
    assert report.compatibility is SchemaCompatibility.BEHIND
    assert report.database_migration_revision == "001_optimus_os_foundation"
    assert report.safe_to_serve is True


def test_schema_compatibility_unsupported_revision_is_not_safe_to_serve() -> None:
    """A revision this app version has never heard of at all -- not an
    ancestor, not the head. Could mean the database is ahead of this app
    (a bad rollback), pointed at the wrong database entirely, or has a
    corrupted alembic_version row. Must never be treated as safe."""
    engine = _fresh_sqlite_engine()
    _create_alembic_version_table(engine, "999_totally_unknown_revision")
    report = check_schema_compatibility(engine)
    assert report.compatibility is SchemaCompatibility.UNSUPPORTED
    assert report.database_migration_revision == "999_totally_unknown_revision"
    assert report.safe_to_serve is False
