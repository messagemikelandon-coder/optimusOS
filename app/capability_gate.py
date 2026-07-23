"""ADR-022 capability gate: the one place a route asks "is this capability
available for the caller's shop, and what should happen if not?" It wraps
the deterministic `resolve_capabilities()` snapshot (app/capability_store.py)
with a decision + one structured telemetry event, and is the single helper
every current and future capability-gated route must call -- routes must
never re-derive a capability decision inline (enforced by the AST safeguard
in tests/test_capability_gate_safeguards.py, mirroring the tenant-boundary
AST test for `effective_shop_id`).

Two explicit modes:

* OBSERVE -- never changes the request outcome. It records whether a future
  enforcement pass *would* allow or deny (`would_allow`/`would_deny`) and
  returns. On a resolution failure it fails **open** (allows) and records
  `resolution_error`. This is the only mode any route may use today; the
  bays pilot uses it to validate the matrix against real traffic before any
  enforcement exists.
* ENFORCE -- denies an unavailable capability with 403, and fails **closed**
  on a resolution failure. Real and unit-tested here so the deny path is not
  vaporware, but no route may activate it: the AST safeguard fails the build
  if any route module references `CapabilityGateMode.ENFORCE`. Flipping a
  route to enforce is therefore a deliberate, reviewed change to that
  safeguard's (currently empty) allowlist -- see the OBSERVE->ENFORCE runbook
  in docs/architecture/OPERATING-MODES-ARCHITECTURE-BRIDGE.md.

Capability logic is always additive to, never a replacement for, the
existing auth/role/tenant/validation/store path: a route still runs every
one of those exactly as before and only *also* calls this gate. In OBSERVE
that means behavior is provably identical with or without the gate.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from fastapi import HTTPException, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_shop_id
from app.capability_metrics import capability_metrics
from app.capability_store import CapabilityStoreError, resolve_capabilities
from app.models import CapabilityId, CapabilityLevel
from app.security_events import (
    ActorType,
    EventResult,
    SecurityEventType,
    log_security_event,
)

logger = logging.getLogger("optimus")

# FULL and LIMITED both surface the capability as part of the shop's
# workflow (LIMITED merely reduces it); HIDDEN and NOT_APPLICABLE mean it is
# not part of this mode's workflow. This is the single definition of
# "available", used for both the observe decision and any future enforce
# decision, so the two can never diverge.
_AVAILABLE_LEVELS = frozenset({CapabilityLevel.FULL, CapabilityLevel.LIMITED})


class CapabilityGateMode(StrEnum):
    OBSERVE = "observe"
    ENFORCE = "enforce"


class CapabilityDecision(StrEnum):
    WOULD_ALLOW = "would_allow"
    WOULD_DENY = "would_deny"
    # Resolution failed; OBSERVE fails open (allows) having recorded this,
    # ENFORCE fails closed (denies).
    RESOLUTION_ERROR = "resolution_error"


@dataclass(frozen=True, slots=True)
class CapabilityObservation:
    capability: CapabilityId
    mode: CapabilityGateMode
    decision: CapabilityDecision
    # None only when decision is RESOLUTION_ERROR.
    level: CapabilityLevel | None


def _safe_shop_id(db: Session, auth: AuthContext) -> int | None:
    """Best-effort shop id for telemetry only. Never raises: if even the
    tenant primitive cannot resolve (the same failure that would make
    capability resolution fail), the event is still emitted with shop_id
    omitted rather than losing the observation entirely."""
    try:
        return effective_shop_id(db, auth)
    except Exception:  # telemetry must never raise
        return None


def _level_for(capabilities, capability: CapabilityId) -> CapabilityLevel | None:
    for entry in capabilities.capabilities:
        if entry.id is capability:
            return entry.level
    return None


def _emit(
    *,
    auth: AuthContext,
    shop_id: int | None,
    capability: CapabilityId,
    mode: CapabilityGateMode,
    decision: CapabilityDecision,
    level: CapabilityLevel | None,
    operating_mode: str | None,
    tier: str | None,
    action: str,
    request: Request | None,
) -> None:
    """Emit exactly one structured, secret-free capability-observation event
    through the existing security-event mechanism. Every value here is a
    role/mode/tier/capability enum or an id -- never a token, password, or
    provider secret."""
    # Roll this decision into the process-wide OBSERVE-only counters (Phase 2B)
    # that back the support operational summary. Additive telemetry beside the
    # per-request event below; record() is total (cannot raise) so it never
    # disturbs the gate's outcome, and the counter is OBSERVE-only -- it holds no
    # enforcement semantics.
    capability_metrics.record(str(decision))
    result = (
        EventResult.SUCCESS
        if decision is not CapabilityDecision.RESOLUTION_ERROR
        else EventResult.FAILURE
    )
    log_security_event(
        logger,
        SecurityEventType.CAPABILITY_OBSERVED,
        request=request,
        level=logging.INFO,
        actor_type=ActorType.USER,
        actor_id=auth.user.id,
        actor_label=auth.user.username,
        shop_id=shop_id,
        resource=str(capability),
        result=result,
        # Event-specific fields (become the event's metadata, flattened onto
        # the structured log record). This is the required telemetry set:
        # actor role, gate mode, tier, operating mode, capability, level,
        # decision, and the route/action; shop_id and timestamp come from the
        # standardized top-level event fields above.
        actor_role=auth.user.role,
        gate_mode=str(mode),
        operating_mode=operating_mode,
        tier=tier,
        capability=str(capability),
        capability_level=(str(level) if level is not None else None),
        decision=str(decision),
        route_action=action,
    )


def evaluate_capability(
    db: Session,
    auth: AuthContext,
    capability: CapabilityId,
    *,
    action: str,
    mode: CapabilityGateMode = CapabilityGateMode.OBSERVE,
    request: Request | None = None,
) -> CapabilityObservation:
    """Resolve `capability` for the caller's shop, emit one telemetry event,
    and (only in ENFORCE) raise 403 when the capability is unavailable.

    OBSERVE never raises for a capability reason and never on a resolution
    failure -- it is behavior-neutral by construction. ENFORCE denies an
    unavailable capability and fails closed on resolution failure. No route
    passes ENFORCE today (AST safeguard); it exists so the deny path is real
    and unit-testable before the first route flips.
    """
    shop_id = _safe_shop_id(db, auth)

    try:
        capabilities = resolve_capabilities(db, auth)
    except (CapabilityStoreError, SQLAlchemyError) as exc:
        _emit(
            auth=auth,
            shop_id=shop_id,
            capability=capability,
            mode=mode,
            decision=CapabilityDecision.RESOLUTION_ERROR,
            level=None,
            operating_mode=None,
            tier=None,
            action=action,
            request=request,
        )
        if mode is CapabilityGateMode.ENFORCE:
            # Fail closed: an unresolvable capability must not be treated as
            # available under enforcement.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Capability could not be resolved.",
            ) from exc
        return CapabilityObservation(
            capability=capability,
            mode=mode,
            decision=CapabilityDecision.RESOLUTION_ERROR,
            level=None,
        )

    level = _level_for(capabilities, capability)
    decision = (
        CapabilityDecision.WOULD_ALLOW
        if level in _AVAILABLE_LEVELS
        else CapabilityDecision.WOULD_DENY
    )
    _emit(
        auth=auth,
        shop_id=shop_id,
        capability=capability,
        mode=mode,
        decision=decision,
        level=level,
        operating_mode=str(capabilities.operating_mode),
        tier=str(capabilities.tier),
        action=action,
        request=request,
    )
    if mode is CapabilityGateMode.ENFORCE and decision is CapabilityDecision.WOULD_DENY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This capability is not available for the shop's current operating mode.",
        )
    return CapabilityObservation(
        capability=capability,
        mode=mode,
        decision=decision,
        level=level,
    )
