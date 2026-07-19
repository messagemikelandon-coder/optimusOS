from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

from sqlalchemy import func, select

from app.auth import AuthContext, effective_shop_id
from app.db import build_session_factory
from app.db_models import AuthSession, ShopSubscription, Technician, UserAccount
from app.models import TechnicianCreate
from app.technician_store import TechnicianConflictError, create_technician
from tests.e2e.conftest import LiveServer, SyntheticCredentials


def _auth_session(db, owner: UserAccount, suffix: str) -> AuthSession:
    auth_session = AuthSession(
        user_id=owner.id,
        token_hash=f"seat-race-{suffix}-{owner.id}",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        last_seen_at=datetime.now(UTC),
    )
    db.add(auth_session)
    db.commit()
    db.refresh(auth_session)
    return auth_session


def test_concurrent_technician_creation_cannot_exceed_the_seat_limit(
    live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    session_factory = build_session_factory(live_server.database_url)
    with session_factory() as db:
        owner = db.get(UserAccount, synthetic_owner.user_id)
        assert owner is not None
        setup_auth = AuthContext(user=owner, session=_auth_session(db, owner, "setup"))
        shop_id = effective_shop_id(db, setup_auth)
        subscription = db.scalar(
            select(ShopSubscription).where(ShopSubscription.shop_id == shop_id)
        )
        assert subscription is not None
        # The synthetic owner starts grandfathered onto the unlimited-seat
        # tier -- downgrade to exactly one free seat so two concurrent
        # creates race for the same slot.
        subscription.tier = "solo"
        subscription.seat_limit = 1
        db.add(subscription)
        db.commit()

    barrier = Barrier(2)

    def worker(suffix: str) -> str:
        with session_factory() as db:
            owner = db.get(UserAccount, synthetic_owner.user_id)
            assert owner is not None
            auth = AuthContext(user=owner, session=_auth_session(db, owner, suffix))
            barrier.wait(timeout=5)
            try:
                create_technician(
                    db=db,
                    auth=auth,
                    payload=TechnicianCreate(
                        first_name=f"Race{suffix}",
                        last_name="Technician",
                        phone=None,
                        email=None,
                        employment_status=None,
                        job_title=None,
                        hourly_cost=None,
                    ),
                )
                return "created"
            except TechnicianConflictError:
                return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, suffix) for suffix in ("a", "b")]
        outcomes = sorted(future.result(timeout=10) for future in futures)

    assert outcomes == ["created", "rejected"]

    with session_factory() as db:
        owner = db.get(UserAccount, synthetic_owner.user_id)
        assert owner is not None
        auth = AuthContext(user=owner, session=_auth_session(db, owner, "verify"))
        shop_id = effective_shop_id(db, auth)
        active_seats = db.scalar(
            select(func.count())
            .select_from(Technician)
            .where(Technician.shop_id == shop_id, Technician.is_archived.is_(False))
        )
        assert active_seats == 1
