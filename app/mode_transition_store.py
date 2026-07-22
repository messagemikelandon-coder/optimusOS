"""ADR-022 post-signup operating-mode management: lets an owner/manager
deliberately move their shop between `solo`, `mobile_field`, and `shop`
after signup, with a dry-run preview, an audited atomic apply, and
optimistic-concurrency protection.

This is a workflow-shaping change only. It never touches subscription tier
or seat limits, never deletes/archives/migrates any business data, never
changes route access or activates capability ENFORCE, and never grants a
technician appointment access. A mode that hides a capability (e.g. Solo
hiding bays) leaves every underlying row stored and untouched -- switching
back restores the view. The preview exists precisely so an owner sees, and
consciously accepts, what will be hidden before applying.

All scoping goes through `effective_shop_id(db, auth)` (the existing tenant
boundary), so a caller can only ever preview or change their own shop --
there is no shop_id parameter to target another tenant. The capability
projection reuses `capability_store.capability_levels_for`, the same single
matrix `resolve_capabilities` applies, so preview and reality can never
diverge.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_shop_id
from app.capability_store import capability_levels_for, resolve_capabilities
from app.db_models import (
    Appointment,
    Bay,
    ScheduleBlock,
    Shop,
    ShopEvent,
    Technician,
    WorkingHours,
)
from app.models import (
    CapabilityId,
    CapabilityLevel,
    ModeOnboardingResult,
    ModeOnboardingStatus,
    ModeTransitionCapabilityChange,
    ModeTransitionPreview,
    ModeTransitionResult,
    ModeTransitionWarning,
    OperatingMode,
)

__all__ = [
    "ModeTransitionConflictError",
    "ModeTransitionError",
    "apply_mode_transition",
    "complete_mode_onboarding",
    "get_mode_onboarding_status",
    "preview_mode_transition",
]

# Source recorded on the audit event, so a future signup-time selector or an
# admin tool can be told apart from this owner/manager self-service path.
_SOURCE = "operating_mode_management_api"

# Distinct source for the one-time post-signup onboarding selection, so the
# audit trail (and any future analytics) can tell a first-run confirmation
# apart from an ongoing Settings-driven mode change.
_ONBOARDING_SOURCE = "post_signup_onboarding"

_DATA_HANDLING_STATEMENT = (
    "No data will be deleted, archived, or migrated by this change. A hidden "
    "capability simply stops being surfaced by default; every bay, "
    "technician, appointment, working-hours, and schedule-block record stays "
    "stored and is shown again if the mode is changed back."
)

# Level availability ordering, most to least available. Used only to decide
# whether a transition *reduces* a capability's availability (so we warn
# about existing data that would be de-emphasized or hidden). FULL/LIMITED
# are "available"; HIDDEN/NOT_APPLICABLE are "unavailable".
_RANK: dict[CapabilityLevel, int] = {
    CapabilityLevel.FULL: 3,
    CapabilityLevel.LIMITED: 2,
    CapabilityLevel.HIDDEN: 1,
    CapabilityLevel.NOT_APPLICABLE: 0,
}
_UNAVAILABLE = frozenset({CapabilityLevel.HIDDEN, CapabilityLevel.NOT_APPLICABLE})

# The five business-data categories the goal calls out for warnings, each
# mapped to the capability whose level governs whether it is surfaced.
# appointments/working_hours/schedule_blocks all ride the SCHEDULING
# capability.
_CATEGORY_CAPABILITY: dict[str, CapabilityId] = {
    "bays": CapabilityId.BAYS,
    "technicians": CapabilityId.TECHNICIANS,
    "appointments": CapabilityId.SCHEDULING,
    "working_hours": CapabilityId.SCHEDULING,
    "schedule_blocks": CapabilityId.SCHEDULING,
}


class ModeTransitionError(ValueError):
    pass


class ModeTransitionConflictError(ModeTransitionError):
    """Raised when the caller's `expected_current_mode` no longer matches the
    shop's real mode (a concurrent change happened first)."""


def _count_existing_data(db: Session, shop_id: int) -> dict[str, int]:
    """Row counts per warning category, tenant-scoped. Bays and technicians
    exclude archived rows (an archived row is already not surfaced); the
    three scheduling tables have no archive concept, so all rows count."""
    return {
        "bays": db.scalar(
            select(func.count())
            .select_from(Bay)
            .where(Bay.shop_id == shop_id, Bay.is_archived.is_(False))
        )
        or 0,
        "technicians": db.scalar(
            select(func.count())
            .select_from(Technician)
            .where(Technician.shop_id == shop_id, Technician.is_archived.is_(False))
        )
        or 0,
        "appointments": db.scalar(
            select(func.count()).select_from(Appointment).where(Appointment.shop_id == shop_id)
        )
        or 0,
        "working_hours": db.scalar(
            select(func.count()).select_from(WorkingHours).where(WorkingHours.shop_id == shop_id)
        )
        or 0,
        "schedule_blocks": db.scalar(
            select(func.count()).select_from(ScheduleBlock).where(ScheduleBlock.shop_id == shop_id)
        )
        or 0,
    }


def _capability_changes(
    current: dict[CapabilityId, CapabilityLevel],
    proposed: dict[CapabilityId, CapabilityLevel],
) -> list[ModeTransitionCapabilityChange]:
    return [
        ModeTransitionCapabilityChange(
            id=capability_id, from_level=current[capability_id], to_level=proposed[capability_id]
        )
        for capability_id in CapabilityId
        if current[capability_id] != proposed[capability_id]
    ]


def _would_be_hidden(
    current: dict[CapabilityId, CapabilityLevel],
    proposed: dict[CapabilityId, CapabilityLevel],
) -> list[CapabilityId]:
    return [
        capability_id
        for capability_id in CapabilityId
        if proposed[capability_id] in _UNAVAILABLE and current[capability_id] not in _UNAVAILABLE
    ]


def _warnings(
    current: dict[CapabilityId, CapabilityLevel],
    proposed: dict[CapabilityId, CapabilityLevel],
    counts: dict[str, int],
    proposed_mode: OperatingMode,
) -> list[ModeTransitionWarning]:
    warnings: list[ModeTransitionWarning] = []
    for category, capability_id in _CATEGORY_CAPABILITY.items():
        from_level = current[capability_id]
        to_level = proposed[capability_id]
        count = counts[category]
        if count <= 0 or _RANK[to_level] >= _RANK[from_level]:
            # No data, or the capability is not being reduced -- nothing to warn about.
            continue
        readable = category.replace("_", " ")
        if to_level in _UNAVAILABLE:
            message = (
                f"{count} {readable} record(s) will be hidden under "
                f"{proposed_mode.value} mode but are retained and never deleted."
            )
        else:
            message = (
                f"{count} {readable} record(s) remain available but de-emphasized "
                f"under {proposed_mode.value} mode; nothing is deleted."
            )
        warnings.append(
            ModeTransitionWarning(
                category=category,
                count=count,
                from_level=from_level,
                to_level=to_level,
                message=message,
            )
        )
    return warnings


def preview_mode_transition(
    db: Session, auth: AuthContext, *, proposed_mode: OperatingMode
) -> ModeTransitionPreview:
    """Dry run: computes what changing to `proposed_mode` would do, with zero
    side effects. Reflects the owner/manager view of the capability matrix
    (this endpoint is owner/manager-only)."""
    shop_id = effective_shop_id(db, auth)
    shop = db.get(Shop, shop_id)
    if shop is None:
        raise ModeTransitionError("This shop does not exist.")

    current_mode = OperatingMode(shop.operating_mode)
    role = auth.user.role
    current_levels = capability_levels_for(current_mode, role)
    proposed_levels = capability_levels_for(proposed_mode, role)
    counts = _count_existing_data(db, shop_id)

    retained = [category for category, count in counts.items() if count > 0]

    return ModeTransitionPreview(
        current_mode=current_mode,
        proposed_mode=proposed_mode,
        is_noop=(current_mode == proposed_mode),
        capability_changes=_capability_changes(current_levels, proposed_levels),
        would_be_hidden=_would_be_hidden(current_levels, proposed_levels),
        retained_data_categories=retained,
        warnings=_warnings(current_levels, proposed_levels, counts, proposed_mode),
        no_data_deleted=True,
        data_handling_statement=_DATA_HANDLING_STATEMENT,
    )


def _lock_shop_and_require_mode(
    db: Session, auth: AuthContext, expected_current_mode: OperatingMode
) -> tuple[Shop, OperatingMode]:
    """Shared check-then-set primitive for every mode-changing path (the
    Settings apply and the post-signup onboarding completion). Resolves the
    caller's own shop (tenant boundary), row-locks it -- matching
    subscription_store's `_require_subscription(..., for_update=True)` so two
    concurrent writers serialize and the second sees the first's new mode --
    and enforces optimistic concurrency against `expected_current_mode`.
    Returns the locked shop and its current mode. Callers must not duplicate
    this locking/validation."""
    shop_id = effective_shop_id(db, auth)
    shop = db.get(Shop, shop_id)
    if shop is None:
        raise ModeTransitionError("This shop does not exist.")
    db.refresh(shop, with_for_update=True)

    current_mode = OperatingMode(shop.operating_mode)
    if current_mode != expected_current_mode:
        raise ModeTransitionConflictError(
            f"The shop's operating mode is '{current_mode.value}', not the expected "
            f"'{expected_current_mode.value}'. Reload the current mode and try again."
        )
    return shop, current_mode


def apply_mode_transition(
    db: Session,
    auth: AuthContext,
    *,
    expected_current_mode: OperatingMode,
    proposed_mode: OperatingMode,
) -> ModeTransitionResult:
    """Atomically set the shop's operating mode, guarded by optimistic
    concurrency (`expected_current_mode`) and an audit event. Only the
    caller's own shop is reachable (tenant boundary). No business data is
    touched; only `Shop.operating_mode` changes."""
    shop, current_mode = _lock_shop_and_require_mode(db, auth, expected_current_mode)

    role = auth.user.role
    current_levels = capability_levels_for(current_mode, role)
    proposed_levels = capability_levels_for(proposed_mode, role)
    changed = proposed_mode != current_mode

    if changed:
        shop.operating_mode = proposed_mode.value
        db.add(shop)
        db.add(
            ShopEvent(
                shop_id=shop.id,
                event_type="operating_mode_changed",
                actor_user_account_id=auth.user.id,
                actor_name=auth.user.username,
                event_metadata={
                    "from_mode": current_mode.value,
                    "to_mode": proposed_mode.value,
                    "source": _SOURCE,
                },
            )
        )
        db.commit()
        db.refresh(shop)

    return ModeTransitionResult(
        previous_mode=current_mode,
        new_mode=proposed_mode,
        changed=changed,
        capability_changes=_capability_changes(current_levels, proposed_levels),
        capabilities=resolve_capabilities(db, auth),
    )


def get_mode_onboarding_status(db: Session, auth: AuthContext) -> ModeOnboardingStatus:
    """Owner-only read: has this shop's operating mode been deliberately
    confirmed yet? `needs_onboarding` is true only while
    `operating_mode_confirmed_at` is NULL -- i.e. a newly created shop whose
    owner has not yet made a first-run selection. Read-only, no side effects,
    tenant-scoped through `effective_shop_id`."""
    shop_id = effective_shop_id(db, auth)
    shop = db.get(Shop, shop_id)
    if shop is None:
        raise ModeTransitionError("This shop does not exist.")
    confirmed_at = shop.operating_mode_confirmed_at
    return ModeOnboardingStatus(
        needs_onboarding=confirmed_at is None,
        operating_mode=OperatingMode(shop.operating_mode),
        confirmed_at=confirmed_at,
    )


def complete_mode_onboarding(
    db: Session,
    auth: AuthContext,
    *,
    expected_current_mode: OperatingMode,
    proposed_mode: OperatingMode,
) -> ModeOnboardingResult:
    """Record a shop owner's one-time post-signup operating-mode selection.

    Reuses the exact same locking/optimistic-concurrency primitive and
    capability matrix as `apply_mode_transition` -- no transition logic is
    duplicated. The only differences from the Settings apply are onboarding
    semantics: it always stamps `operating_mode_confirmed_at` (so even
    *confirming* the default `shop` without changing mode records a
    deliberate choice), and it always writes exactly one audit event tagged
    `source=post_signup_onboarding` -- including for a no-op confirmation --
    so completion is provable in the audit trail.

    Atomic: the mode change (if any) and the confirmation stamp commit
    together in one transaction. Touches only `Shop.operating_mode` and
    `Shop.operating_mode_confirmed_at`; never tier, seats, or business data.
    """
    shop, current_mode = _lock_shop_and_require_mode(db, auth, expected_current_mode)

    role = auth.user.role
    current_levels = capability_levels_for(current_mode, role)
    proposed_levels = capability_levels_for(proposed_mode, role)
    changed = proposed_mode != current_mode
    confirmed_at = datetime.now(UTC)

    if changed:
        shop.operating_mode = proposed_mode.value
    shop.operating_mode_confirmed_at = confirmed_at
    db.add(shop)
    # Exactly one event, always -- even when `changed` is False (the owner
    # deliberately kept the default) -- carrying from/to, the changed flag,
    # the onboarding source, and the acting owner.
    db.add(
        ShopEvent(
            shop_id=shop.id,
            event_type="operating_mode_onboarding_completed",
            actor_user_account_id=auth.user.id,
            actor_name=auth.user.username,
            event_metadata={
                "from_mode": current_mode.value,
                "to_mode": proposed_mode.value,
                "changed": changed,
                "source": _ONBOARDING_SOURCE,
                "confirmed_at": confirmed_at.isoformat(),
            },
        )
    )
    db.commit()
    db.refresh(shop)

    return ModeOnboardingResult(
        previous_mode=current_mode,
        new_mode=proposed_mode,
        changed=changed,
        confirmed_at=confirmed_at,
        capability_changes=_capability_changes(current_levels, proposed_levels),
        capabilities=resolve_capabilities(db, auth),
    )
