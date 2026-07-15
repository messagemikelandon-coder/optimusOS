from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger("optimus")

_ALEMBIC_INI_PATH = Path(__file__).resolve().parent.parent / "alembic.ini"


class SchemaCompatibility(StrEnum):
    """How the real database's current Alembic revision compares to the
    revision this running application version actually expects.

    MATCHED: database is exactly on the head this app version expects.
    BEHIND: database is on a known ancestor of the app's head -- the
        normal, expected, temporary window during a deploy that runs
        `update` (restart with new code) before `migrate` (apply new
        migrations), per this repo's own documented runbook order. Not a
        defect; tolerated, not blocked.
    UNMIGRATED: no `alembic_version` table exists at all yet (a genuinely
        fresh database that has never been migrated). Tolerated the same
        way as BEHIND -- it's the starting case of the same window.
    UNSUPPORTED: the database's current revision is not anywhere in this
        app version's known migration chain at all -- it's ahead of what
        this app understands (e.g. a bad rollback: old app code started
        against a newer schema), or it's a completely different/wrong
        database, or `alembic_version` is corrupted. This is the case the
        app must never quietly serve real traffic against.
    UNREACHABLE: the database could not be reached to determine its
        revision at all (distinct from the normal Postgres-down case
        already reported separately by /ready -- this specifically means
        "we don't know, so don't claim compatibility").
    """

    MATCHED = "matched"
    BEHIND = "behind"
    UNMIGRATED = "unmigrated"
    UNSUPPORTED = "unsupported"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True, slots=True)
class SchemaCompatibilityReport:
    app_migration_head: str
    database_migration_revision: str | None
    compatibility: SchemaCompatibility

    @property
    def safe_to_serve(self) -> bool:
        """Whether this instance should be considered ready to serve real
        traffic. BEHIND/UNMIGRATED are tolerated (the app's own routes
        already fail with sanitized errors against genuinely missing
        tables, same as any other Postgres-down-shaped failure) --
        UNSUPPORTED and UNREACHABLE are not, since serving traffic against
        an unrecognized or unverifiable schema risks silent data
        corruption rather than a clean, visible failure."""
        return self.compatibility in (
            SchemaCompatibility.MATCHED,
            SchemaCompatibility.BEHIND,
            SchemaCompatibility.UNMIGRATED,
        )


def get_app_migration_head() -> str:
    config = Config(str(_ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(_ALEMBIC_INI_PATH.parent / "alembic"))
    script = ScriptDirectory.from_config(config)
    head = script.get_current_head()
    if head is None:  # pragma: no cover - only possible with zero migrations
        raise RuntimeError(
            "No Alembic migrations found; cannot determine the app's migration head."
        )
    return head


def _known_revisions() -> set[str]:
    config = Config(str(_ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(_ALEMBIC_INI_PATH.parent / "alembic"))
    script = ScriptDirectory.from_config(config)
    return {revision.revision for revision in script.walk_revisions()}


def get_database_migration_revision(engine: Engine) -> str | None:
    # Dialect-agnostic (inspect().has_table rather than a Postgres-specific
    # to_regclass() call) so this is genuinely exercised by the SQLite-based
    # test suite too, not just live-proofed against real Postgres.
    try:
        with engine.connect() as connection:
            if not inspect(engine).has_table("alembic_version"):
                return None
            return connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    except SQLAlchemyError:
        return None


def check_schema_compatibility(engine: Engine) -> SchemaCompatibilityReport:
    app_head = get_app_migration_head()
    try:
        db_revision = get_database_migration_revision(engine)
    except Exception:
        logger.warning("Could not determine the database's current migration revision.")
        return SchemaCompatibilityReport(
            app_migration_head=app_head,
            database_migration_revision=None,
            compatibility=SchemaCompatibility.UNREACHABLE,
        )

    if db_revision is None:
        return SchemaCompatibilityReport(
            app_migration_head=app_head,
            database_migration_revision=None,
            compatibility=SchemaCompatibility.UNMIGRATED,
        )
    if db_revision == app_head:
        compatibility = SchemaCompatibility.MATCHED
    elif db_revision in _known_revisions():
        compatibility = SchemaCompatibility.BEHIND
    else:
        compatibility = SchemaCompatibility.UNSUPPORTED
        logger.error(
            "Database migration revision %r is not in this application version's "
            "known migration chain (expected head %r). Refusing to report ready.",
            db_revision,
            app_head,
        )
    return SchemaCompatibilityReport(
        app_migration_head=app_head,
        database_migration_revision=db_revision,
        compatibility=compatibility,
    )
