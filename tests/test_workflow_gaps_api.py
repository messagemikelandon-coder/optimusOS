from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.main as main
from app.auth import AuthContext
from app.db import get_db_session, get_settings
from app.db_models import AuthSession, ShopMembership, UserAccount, WorkflowGap, WorkflowGapEvent
from app.models import WorkflowGapCreate, WorkflowGapSeverity, WorkflowGapStatus, WorkflowGapUpdate
from app.workflow_gap_store import (
    WorkflowGapConflictError,
    WorkflowGapNotFoundError,
    WorkflowGapStoreError,
    create_workflow_gap,
    get_workflow_gap,
    list_workflow_gap_events,
    list_workflow_gaps,
    record_workflow_gap_occurrence,
    update_workflow_gap,
)
from tests.test_context_api import auth_context, create_user, login_as, raw_cookie_from_response
from tests.test_role_isolation import _create_technician


def _owner(db: Session) -> UserAccount:
    owner = db.scalar(select(UserAccount).where(UserAccount.role == "owner"))
    assert owner is not None
    return owner


def _auth(db: Session, user: UserAccount, suffix: str) -> AuthContext:
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=f"workflow-gap-{user.id}-{suffix}",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        last_seen_at=datetime.now(UTC),
    )
    db.add(auth_session)
    db.commit()
    db.refresh(auth_session)
    return AuthContext(user=user, session=auth_session)


def test_workflow_gap_lifecycle_is_audited(settings, db_session: Session) -> None:
    owner = _owner(db_session)
    auth = _auth(db_session, owner, "lifecycle")
    created = create_workflow_gap(
        db_session,
        auth,
        WorkflowGapCreate(
            title="Estimate revision loses a note",
            description="The note must be re-entered after revising an estimate.",
            workflow_area="estimates",
            severity=WorkflowGapSeverity.HIGH,
            workaround="Copy the note before revising.",
        ),
    )
    assert created.status == WorkflowGapStatus.OPEN
    assert created.occurrence_count == 1

    occurrence = record_workflow_gap_occurrence(db_session, auth, created.id)
    assert occurrence.occurrence_count == 2
    investigating = update_workflow_gap(
        db_session,
        auth,
        created.id,
        WorkflowGapUpdate(
            status=WorkflowGapStatus.INVESTIGATING,
            workaround="Copy the note and attach it to the work order.",
        ),
    )
    assert investigating.status == WorkflowGapStatus.INVESTIGATING
    resolved = update_workflow_gap(
        db_session,
        auth,
        created.id,
        WorkflowGapUpdate(status=WorkflowGapStatus.RESOLVED),
    )
    assert resolved.closed_at is not None
    with pytest.raises(WorkflowGapConflictError):
        record_workflow_gap_occurrence(db_session, auth, created.id)

    events = list_workflow_gap_events(db_session, auth, created.id)
    assert [event.event_type for event in events.items] == [
        "created",
        "occurrence_recorded",
        "status_changed",
        "updated",
        "status_changed",
    ]
    assert events.items[-1].from_status == WorkflowGapStatus.INVESTIGATING
    assert events.items[-1].to_status == WorkflowGapStatus.RESOLVED

    reopened = update_workflow_gap(
        db_session,
        auth,
        created.id,
        WorkflowGapUpdate(status=WorkflowGapStatus.OPEN),
    )
    assert reopened.closed_at is None
    listing = list_workflow_gaps(
        db_session,
        auth,
        settings,
        page=1,
        page_size=20,
        status_filter=WorkflowGapStatus.OPEN,
        severity_filter=WorkflowGapSeverity.HIGH,
        search="revision note",
    )
    assert [item.id for item in listing.items] == [created.id]


def test_workflow_gap_transition_table_rejects_invalid_move(db_session: Session) -> None:
    owner = _owner(db_session)
    auth = _auth(db_session, owner, "transition")
    gap = create_workflow_gap(
        db_session,
        auth,
        WorkflowGapCreate(
            title="Scheduling exception",
            description="A recurring scheduling exception.",
            workflow_area="scheduling",
        ),
    )
    update_workflow_gap(
        db_session,
        auth,
        gap.id,
        WorkflowGapUpdate(status=WorkflowGapStatus.PLANNED),
    )
    with pytest.raises(WorkflowGapConflictError):
        update_workflow_gap(
            db_session,
            auth,
            gap.id,
            WorkflowGapUpdate(status=WorkflowGapStatus.OPEN),
        )


def test_workflow_gaps_are_shop_scoped(settings, db_session: Session) -> None:
    owner = _owner(db_session)
    owner_auth = _auth(db_session, owner, "owner")
    gap = create_workflow_gap(
        db_session,
        owner_auth,
        WorkflowGapCreate(
            title="Owner-only pilot gap",
            description="Must not cross the membership boundary.",
            workflow_area="pilot",
        ),
    )
    other_owner = create_user(
        db_session,
        username="workflow-gap-other-owner",
        password="workflow-gap-password-123",
        settings=settings,
    )
    other_auth = _auth(db_session, other_owner, "other")
    assert (
        list_workflow_gaps(
            db_session,
            other_auth,
            settings,
            page=1,
            page_size=20,
            status_filter=None,
            severity_filter=None,
            search=None,
        ).items
        == []
    )
    with pytest.raises(WorkflowGapNotFoundError):
        get_workflow_gap(db_session, other_auth, gap.id)
    with pytest.raises(WorkflowGapNotFoundError):
        update_workflow_gap(
            db_session,
            other_auth,
            gap.id,
            WorkflowGapUpdate(status=WorkflowGapStatus.RESOLVED),
        )
    with pytest.raises(WorkflowGapNotFoundError):
        record_workflow_gap_occurrence(db_session, other_auth, gap.id)
    with pytest.raises(WorkflowGapNotFoundError):
        list_workflow_gap_events(db_session, other_auth, gap.id)
    assert db_session.scalar(select(WorkflowGap).where(WorkflowGap.id == gap.id)) is not None
    assert (
        db_session.scalar(
            select(WorkflowGapEvent).where(WorkflowGapEvent.workflow_gap_id == gap.id)
        )
        is not None
    )


def test_workflow_gap_pagination_rejects_nonpositive_page_size(
    settings, db_session: Session
) -> None:
    owner = _owner(db_session)
    auth = _auth(db_session, owner, "invalid-pagination")
    for page_size in (0, -1):
        with pytest.raises(WorkflowGapStoreError):
            list_workflow_gaps(
                db_session,
                auth,
                settings,
                page=1,
                page_size=page_size,
                status_filter=None,
                severity_filter=None,
                search=None,
            )


def test_manager_membership_can_track_same_shop_gap(settings, db_session: Session) -> None:
    owner = _owner(db_session)
    membership = db_session.scalar(
        select(ShopMembership).where(ShopMembership.user_account_id == owner.id)
    )
    assert membership is not None
    manager = UserAccount(
        username="workflow-gap-manager",
        display_name="Workflow Gap Manager",
        role="manager",
        shop_owner_id=owner.id,
        password_hash=owner.password_hash,
        is_active=True,
        account_status="active",
    )
    db_session.add(manager)
    db_session.flush()
    db_session.add(
        ShopMembership(
            shop_id=membership.shop_id,
            user_account_id=manager.id,
            role="manager",
        )
    )
    db_session.commit()
    manager_auth = _auth(db_session, manager, "manager")
    gap = create_workflow_gap(
        db_session,
        manager_auth,
        WorkflowGapCreate(
            title="Manager-observed gap",
            description="A manager can track a gap for the same Shop.",
            workflow_area="operations",
        ),
    )
    assert gap.created_by_user_account_id == manager.id
    assert get_workflow_gap(db_session, _auth(db_session, owner, "owner-read"), gap.id).id == gap.id


async def test_workflow_gap_routes_map_store_errors_to_the_right_status_codes(
    settings, db_session: Session
) -> None:
    _, response = await login_as(settings, db_session)
    auth = auth_context(settings, db_session, raw_cookie_from_response(response))

    created = await main.create_workflow_gap_record(
        WorkflowGapCreate(
            title="Route-level gap",
            description="Exercises the HTTP route wrappers directly.",
            workflow_area="routes",
        ),
        db_session,
        auth,
    )
    fetched = await main.get_workflow_gap_record(created.id, db_session, auth)
    assert fetched.id == created.id

    with pytest.raises(HTTPException) as not_found:
        await main.get_workflow_gap_record(created.id + 999, db_session, auth)
    assert not_found.value.status_code == 404

    with pytest.raises(HTTPException) as not_found_update:
        await main.update_workflow_gap_record(
            created.id + 999, WorkflowGapUpdate(status=WorkflowGapStatus.RESOLVED), db_session, auth
        )
    assert not_found_update.value.status_code == 404

    with pytest.raises(HTTPException) as not_found_occurrence:
        await main.record_workflow_gap_occurrence_record(created.id + 999, db_session, auth)
    assert not_found_occurrence.value.status_code == 404

    with pytest.raises(HTTPException) as not_found_events:
        await main.list_workflow_gap_event_records(created.id + 999, db_session, auth)
    assert not_found_events.value.status_code == 404

    await main.update_workflow_gap_record(
        created.id, WorkflowGapUpdate(status=WorkflowGapStatus.RESOLVED), db_session, auth
    )
    with pytest.raises(HTTPException) as conflict:
        await main.update_workflow_gap_record(
            created.id, WorkflowGapUpdate(status=WorkflowGapStatus.INVESTIGATING), db_session, auth
        )
    assert conflict.value.status_code == 409

    with pytest.raises(HTTPException) as invalid_page:
        await main.list_workflow_gap_records(
            db_session,
            settings,
            auth,
            page=1,
            page_size=0,
            search=None,
            status_filter=None,
            severity_filter=None,
        )
    assert invalid_page.value.status_code == 422

    events = await main.list_workflow_gap_event_records(created.id, db_session, auth)
    assert [event.event_type for event in events.items] == ["created", "status_changed"]


def test_technician_session_is_rejected_on_workflow_gap_routes_end_to_end(
    settings, db_session: Session
) -> None:
    owner = db_session.scalar(select(UserAccount).where(UserAccount.role == "owner"))
    assert owner is not None
    _create_technician(db_session, shop_owner_id=owner.id)

    main.app.dependency_overrides[get_settings] = lambda: settings
    main.app.dependency_overrides[get_db_session] = lambda: db_session
    try:
        client = TestClient(main.app)
        owner_login = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "owner-password-123"},
        )
        assert owner_login.status_code == 200
        assert client.get("/api/workflow-gaps").status_code == 200
        create_response = client.post(
            "/api/workflow-gaps",
            json={
                "title": "HTTP-level gap",
                "description": "Created through a real HTTP request.",
                "workflow_area": "http",
            },
        )
        assert create_response.status_code == 200
        gap_id = create_response.json()["id"]
        client.post("/api/auth/logout")

        tech_login = client.post(
            "/api/auth/login",
            json={"username": "tech-one", "password": "tech-password-123"},
        )
        assert tech_login.status_code == 200
        assert client.get("/api/workflow-gaps").status_code == 403
        assert client.get(f"/api/workflow-gaps/{gap_id}").status_code == 403
        assert client.post(f"/api/workflow-gaps/{gap_id}/occurrences").status_code == 403
        assert (
            client.post(
                "/api/workflow-gaps",
                json={"title": "x", "description": "y", "workflow_area": "z"},
            ).status_code
            == 403
        )
    finally:
        main.app.dependency_overrides.clear()
