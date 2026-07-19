from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import AuthContext, hash_password, normalize_username
from app.config import Settings
from app.db_models import Appointment, AuthSession, UserAccount
from app.models import TechnicianCreate, TechnicianProvisionLoginRequest
from app.shop_store import create_shop_for_new_owner
from app.technician_store import create_technician, provision_login

_USERNAME_PREFIX = "e2e-"

# Process-global state for the concurrency probe below -- deliberately not
# request-scoped, since the whole point is to observe overlap *across*
# concurrent requests within this one process. Guarded by a lock since
# multiple request-handling threads touch it at once (that's the point).
_concurrency_probe_lock = threading.Lock()
_concurrency_probe_in_flight = 0
_concurrency_probe_max_observed = 0


def concurrency_probe(delay_ms: int) -> int:
    """Sleeps for `delay_ms` while tracking how many concurrent invocations
    of this function were in flight at once, process-wide. Used by
    `tests/e2e/test_request_concurrency.py` to prove real HTTP-level
    request concurrency exists (Phase 1 of the /goal roadmap) -- a timing
    threshold (e.g. "two requests took ~1x not ~2x as long") is flaky under
    real scheduling jitter; a shared in-flight counter is not. This is a
    blocking, synchronous function by design, called via
    `asyncio.to_thread` from the route layer exactly like every other store
    function in this app -- it wouldn't prove anything about real
    concurrency if it were natively async.
    """
    global _concurrency_probe_in_flight, _concurrency_probe_max_observed
    with _concurrency_probe_lock:
        _concurrency_probe_in_flight += 1
        _concurrency_probe_max_observed = max(
            _concurrency_probe_max_observed, _concurrency_probe_in_flight
        )
    time.sleep(delay_ms / 1000)
    with _concurrency_probe_lock:
        observed = _concurrency_probe_max_observed
        _concurrency_probe_in_flight -= 1
    return observed


def reset_concurrency_probe() -> None:
    global _concurrency_probe_in_flight, _concurrency_probe_max_observed
    with _concurrency_probe_lock:
        _concurrency_probe_in_flight = 0
        _concurrency_probe_max_observed = 0


class TestSupportError(ValueError):
    """Base error for synthetic test-account provisioning failures."""


class TestSupportDisabledError(TestSupportError):
    """Raised when synthetic account provisioning is not enabled."""


class SyntheticOwnerNotFoundError(TestSupportError):
    """Raised when a referenced synthetic owner account does not exist."""


@dataclass(frozen=True, slots=True)
class SyntheticAccount:
    user_id: int
    username: str
    password: str
    role: Literal["owner", "manager", "technician"]
    technician_id: int | None = None


def provisioning_enabled(settings: Settings) -> bool:
    """Both an explicit opt-in flag and a non-production app_env are required.

    Neither condition alone is sufficient. This mirrors the double-guard
    pattern already used elsewhere in this codebase (e.g. technician
    provisioning re-validating the owner role) rather than trusting one
    signal -- a stray flag left on in a misconfigured production .env still
    can't do anything unless APP_ENV was also deliberately changed.
    """
    return bool(settings.optimus_test_account_provisioning) and settings.app_env != "production"


def _require_enabled(settings: Settings) -> None:
    if not provisioning_enabled(settings):
        raise TestSupportDisabledError("Synthetic test-account provisioning is not enabled.")


def _generate_credentials(label: str) -> tuple[str, str]:
    username = normalize_username(f"{_USERNAME_PREFIX}{label}-{secrets.token_hex(4)}")
    password = secrets.token_urlsafe(18)
    return username, password


def _synthetic_auth_context(owner: UserAccount) -> AuthContext:
    # A throwaway, never-persisted AuthSession. create_technician() and
    # provision_login() only ever read auth.user for these two calls, never
    # auth.session, so this avoids leaving a fake auth_sessions row behind
    # for something that was never a real browser session.
    fake_session = AuthSession(
        user_id=owner.id,
        token_hash="synthetic-unused",
        expires_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    return AuthContext(user=owner, session=fake_session)


def provision_synthetic_owner(*, db: Session, settings: Settings) -> SyntheticAccount:
    _require_enabled(settings)
    username, password = _generate_credentials("owner")
    owner = UserAccount(
        username=username,
        display_name="Synthetic test owner",
        role="owner",
        password_hash=hash_password(password),
        is_active=True,
        is_synthetic_test_account=True,
    )
    db.add(owner)
    db.flush()
    # Without this, every synthetic owner would have no ShopMembership at
    # all (unlike a bootstrapped or migrated real owner), so every
    # business-table row a synthetic owner or their technicians create
    # would silently keep shop_id = NULL -- closing that gap here rather
    # than leaving synthetic accounts as a permanent, undocumented
    # exception to the rest of this phase's guarantees.
    create_shop_for_new_owner(db, settings, owner)
    db.commit()
    db.refresh(owner)
    return SyntheticAccount(
        user_id=owner.id, username=owner.username, password=password, role="owner"
    )


def provision_synthetic_technician(
    *, db: Session, settings: Settings, owner_username: str
) -> SyntheticAccount:
    _require_enabled(settings)
    owner = db.scalar(
        select(UserAccount).where(UserAccount.username == normalize_username(owner_username))
    )
    if owner is None or owner.role != "owner" or not owner.is_synthetic_test_account:
        # Deliberately refuses to attach a synthetic technician to any real
        # owner account, even if the caller supplies a real, valid username.
        raise SyntheticOwnerNotFoundError(
            "owner_username must reference an existing synthetic owner account."
        )

    auth = _synthetic_auth_context(owner)
    technician_read = create_technician(
        db=db,
        auth=auth,
        payload=TechnicianCreate(first_name="Synthetic", last_name="Technician"),
    )
    username, password = _generate_credentials("tech")
    login_response = provision_login(
        db=db,
        auth=auth,
        technician_id=technician_read.id,
        payload=TechnicianProvisionLoginRequest(username=username, password=password),
    )
    technician_user = db.scalar(
        select(UserAccount).where(UserAccount.username == normalize_username(username))
    )
    if technician_user is None:  # pragma: no cover - provision_login just created this row
        raise TestSupportError("Synthetic technician login was not created as expected.")
    technician_user.is_synthetic_test_account = True
    db.add(technician_user)
    db.commit()
    return SyntheticAccount(
        user_id=technician_user.id,
        username=login_response.username,
        password=password,
        role="technician",
        technician_id=technician_read.id,
    )


def _delete_owner_and_dependents(db: Session, owner: UserAccount) -> None:
    # Deletes any technician logins under this owner explicitly rather than
    # relying solely on the database's ON DELETE CASCADE for shop_owner_id.
    # That FK cascade is real and does fire against Postgres in every real
    # deployment, but SQLite (used by the test suite) does not enforce
    # foreign keys by default, so a passive-cascade-only cleanup here would
    # pass its own tests while silently leaving orphaned technician rows
    # behind on SQLite -- explicit deletion is correct and verifiable on
    # both engines, and matches this codebase's own principle of not relying
    # only on a foreign key to establish cleanup/ownership behavior.
    technicians = db.scalars(select(UserAccount).where(UserAccount.shop_owner_id == owner.id)).all()
    for technician_user in technicians:
        db.delete(technician_user)

    # Appointments must be deleted before the owner cascade reaches
    # customers/vehicles/technicians: `appointments.customer_id`/`vehicle_id`/
    # `technician_id` are deliberately `ON DELETE RESTRICT` (an appointment
    # must never silently vanish or lose its audit trail if a customer/
    # vehicle/technician record is later removed in real usage, which only
    # ever archives those records rather than hard-deleting them). This test
    # -support cleanup path is the one place in the whole codebase that does
    # hard-delete them, and it was the first thing to ever exercise this
    # combination against real Postgres (SQLite, used by the fast unit
    # suite, does not enforce foreign keys, so this was never caught there)
    # -- found via a real `ForeignKeyViolation` on `appointments_vehicle_id_
    # fkey` while adding `tests/e2e/test_scheduling_concurrency.py`.
    # `owner_user_id` on `appointments` does cascade, so this explicit
    # delete is only needed to get the ordering right within one
    # transaction, not to avoid an orphaned row.
    appointments = db.scalars(
        select(Appointment).where(Appointment.owner_user_id == owner.id)
    ).all()
    for appointment in appointments:
        db.delete(appointment)

    db.delete(owner)


def cleanup_synthetic_account(*, db: Session, settings: Settings, user_id: int) -> bool:
    _require_enabled(settings)
    user = db.get(UserAccount, user_id)
    if user is None or not user.is_synthetic_test_account:
        # Refuses to delete anything not created through this same synthetic
        # flow -- this can never be used to delete a real account, even by
        # guessing or iterating over ids.
        return False
    if user.role == "owner":
        _delete_owner_and_dependents(db, user)
    else:
        db.delete(user)
    db.commit()
    return True


def cleanup_all_synthetic_accounts(*, db: Session, settings: Settings) -> int:
    _require_enabled(settings)
    owners = db.scalars(
        select(UserAccount).where(
            UserAccount.is_synthetic_test_account.is_(True),
            UserAccount.role == "owner",
        )
    ).all()
    count = 0
    for owner in owners:
        _delete_owner_and_dependents(db, owner)
        count += 1
    db.commit()
    return count
