from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

from sqlalchemy import func, select

from app.auth import AuthContext
from app.db import build_session_factory
from app.db_models import AuthSession, UserAccount, WorkflowGap, WorkflowGapEvent
from app.models import WorkflowGapCreate
from app.workflow_gap_store import create_workflow_gap, record_workflow_gap_occurrence
from tests.e2e.conftest import LiveServer, SyntheticCredentials


def test_concurrent_occurrences_are_not_lost_on_postgres(
    live_server: LiveServer, synthetic_owner: SyntheticCredentials
) -> None:
    session_factory = build_session_factory(live_server.database_url)
    with session_factory() as db:
        owner = db.get(UserAccount, synthetic_owner.user_id)
        assert owner is not None
        auth_session = AuthSession(
            user_id=owner.id,
            token_hash=f"workflow-gap-concurrency-{owner.id}",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            last_seen_at=datetime.now(UTC),
        )
        db.add(auth_session)
        db.commit()
        db.refresh(auth_session)
        gap = create_workflow_gap(
            db,
            AuthContext(user=owner, session=auth_session),
            WorkflowGapCreate(
                title="Concurrent pilot gap",
                description="Two operators observed the same gap at once.",
                workflow_area="pilot",
            ),
        )
        gap_id = gap.id

    barrier = Barrier(2)

    def worker(suffix: str) -> int:
        with session_factory() as db:
            owner = db.get(UserAccount, synthetic_owner.user_id)
            assert owner is not None
            auth_session = AuthSession(
                user_id=owner.id,
                token_hash=f"workflow-gap-worker-{suffix}-{owner.id}",
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                last_seen_at=datetime.now(UTC),
            )
            db.add(auth_session)
            db.commit()
            barrier.wait(timeout=5)
            return record_workflow_gap_occurrence(
                db, AuthContext(user=owner, session=auth_session), gap_id
            ).occurrence_count

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, suffix) for suffix in ("a", "b")]
        observed = sorted(future.result(timeout=10) for future in futures)
    assert observed == [2, 3]

    with session_factory() as db:
        gap = db.get(WorkflowGap, gap_id)
        assert gap is not None and gap.occurrence_count == 3
        event_count = db.scalar(
            select(func.count())
            .select_from(WorkflowGapEvent)
            .where(
                WorkflowGapEvent.workflow_gap_id == gap_id,
                WorkflowGapEvent.event_type == "occurrence_recorded",
            )
        )
        assert event_count == 2
