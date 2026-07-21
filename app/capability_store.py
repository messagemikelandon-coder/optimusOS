"""ADR-022 capability foundation: one backend service that resolves what a
shop's operating mode, subscription tier, and caller role make available --
combining `Shop.operating_mode`, `ShopSubscription.tier`/seat data, and the
caller's `ShopMembership.role`, exactly the three inputs ADR-022 Decision
§2 names. Platform-controlled overrides are deferred (ADR-022 Unresolved
Decision #4): no `ShopCapabilityOverride`-style table exists yet, so
`overrides_applied` is always empty until that storage is added in a later
slice -- this module adds no such table itself.

This is resolution only, not enforcement. `resolve_capabilities()` never
raises to block an action and no route calls it as a gate yet -- every
existing route and behavior stays exactly as reachable as before this
module existed (ADR-022 Decision §5). It is designed to be the single
future call site for that gating (routes, store functions, manual UI via
`GET /api/capabilities`, and any future Optimus/AI action per ADR-016's
"one write path" discipline), matching the same "one function computes the
boundary, everything else calls it" shape `effective_shop_id()` already
established for tenant scoping (ADR-019).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.auth import AuthContext, effective_shop_id
from app.db_models import Shop
from app.models import (
    CapabilitiesRead,
    CapabilityEntry,
    CapabilityId,
    CapabilityLevel,
    OperatingMode,
    SubscriptionTier,
)
from app.subscription_store import count_active_technician_seats

__all__ = ["CapabilityStoreError", "resolve_capabilities"]


class CapabilityStoreError(ValueError):
    pass


_FULL = CapabilityLevel.FULL
_LIMITED = CapabilityLevel.LIMITED
_HIDDEN = CapabilityLevel.HIDDEN
_NA = CapabilityLevel.NOT_APPLICABLE

# ADR-022 §2 capability matrix, transcribed verbatim from
# docs/architecture/OPERATING-MODES-ARCHITECTURE-BRIDGE.md §2's Solo/Mobile
# Field/Shop columns. Applies to owner and manager callers -- a technician
# caller uses _TECHNICIAN_LEVELS below instead, mirroring how role and mode
# are resolved as separate, orthogonal axes (bridge doc §6).
_MODE_LEVELS: dict[OperatingMode, dict[CapabilityId, CapabilityLevel]] = {
    OperatingMode.SOLO: {
        CapabilityId.CUSTOMERS: _FULL,
        CapabilityId.VEHICLES: _FULL,
        CapabilityId.ESTIMATES: _FULL,
        CapabilityId.DIAGNOSTICS: _FULL,
        CapabilityId.WORK_ORDERS: _FULL,
        CapabilityId.INVOICES: _FULL,
        CapabilityId.SCHEDULING: _LIMITED,
        CapabilityId.BAYS: _HIDDEN,
        CapabilityId.TECHNICIANS: _HIDDEN,
        CapabilityId.PARTS: _FULL,
        CapabilityId.REPORTS: _LIMITED,
        CapabilityId.FIELD_FUNCTIONS: _NA,
        CapabilityId.OPTIMUS_ACTIONS: _FULL,
    },
    OperatingMode.MOBILE_FIELD: {
        CapabilityId.CUSTOMERS: _FULL,
        CapabilityId.VEHICLES: _FULL,
        CapabilityId.ESTIMATES: _FULL,
        CapabilityId.DIAGNOSTICS: _FULL,
        CapabilityId.WORK_ORDERS: _FULL,
        CapabilityId.INVOICES: _FULL,
        CapabilityId.SCHEDULING: _FULL,
        CapabilityId.BAYS: _HIDDEN,
        CapabilityId.TECHNICIANS: _LIMITED,
        CapabilityId.PARTS: _LIMITED,
        CapabilityId.REPORTS: _LIMITED,
        CapabilityId.FIELD_FUNCTIONS: _FULL,
        CapabilityId.OPTIMUS_ACTIONS: _FULL,
    },
    OperatingMode.SHOP: {
        CapabilityId.CUSTOMERS: _FULL,
        CapabilityId.VEHICLES: _FULL,
        CapabilityId.ESTIMATES: _FULL,
        CapabilityId.DIAGNOSTICS: _FULL,
        CapabilityId.WORK_ORDERS: _FULL,
        CapabilityId.INVOICES: _FULL,
        CapabilityId.SCHEDULING: _FULL,
        CapabilityId.BAYS: _FULL,
        CapabilityId.TECHNICIANS: _FULL,
        CapabilityId.PARTS: _FULL,
        CapabilityId.REPORTS: _FULL,
        CapabilityId.FIELD_FUNCTIONS: _LIMITED,
        CapabilityId.OPTIMUS_ACTIONS: _FULL,
    },
}

# ADR-022 §2's "Technician role" column -- flat across all three modes,
# since role (who) and mode (how the shop works) are orthogonal (bridge doc
# §6). Matches today's real route gates exactly: Estimates/Invoices/
# Reports/Scheduling are owner-or-manager-only today (Fact, bridge doc
# §1.3), Diagnostics/Work orders are already owner-or-technician, and
# Technicians/Parts/Optimus actions are self-service-scoped, not full
# roster/warehouse/unrestricted access.
_TECHNICIAN_LEVELS: dict[CapabilityId, CapabilityLevel] = {
    CapabilityId.CUSTOMERS: _FULL,
    CapabilityId.VEHICLES: _FULL,
    CapabilityId.ESTIMATES: _HIDDEN,
    CapabilityId.DIAGNOSTICS: _FULL,
    CapabilityId.WORK_ORDERS: _FULL,
    CapabilityId.INVOICES: _HIDDEN,
    CapabilityId.SCHEDULING: _HIDDEN,
    CapabilityId.BAYS: _NA,
    CapabilityId.TECHNICIANS: _LIMITED,
    CapabilityId.PARTS: _LIMITED,
    CapabilityId.REPORTS: _HIDDEN,
    CapabilityId.FIELD_FUNCTIONS: _HIDDEN,
    CapabilityId.OPTIMUS_ACTIONS: _LIMITED,
}


def _capability_levels_for(
    operating_mode: OperatingMode, role: str
) -> dict[CapabilityId, CapabilityLevel]:
    if role == "technician":
        return _TECHNICIAN_LEVELS
    return _MODE_LEVELS[operating_mode]


def capability_levels_for(
    operating_mode: OperatingMode, role: str
) -> dict[CapabilityId, CapabilityLevel]:
    """Public, DB-free view of the same (operating_mode, role) -> levels
    mapping `resolve_capabilities` applies, so callers that need to compare
    two hypothetical modes (e.g. the mode-transition preview) reuse the one
    matrix instead of re-deriving it -- exactly the single-source discipline
    the matrix-drift safeguard protects. Returns a fresh dict; mutating it
    never affects the canonical matrix."""
    return dict(_capability_levels_for(operating_mode, role))


def resolve_capabilities(db: Session, auth: AuthContext) -> CapabilitiesRead:
    """Deterministic snapshot for the caller's shop: same
    (operating_mode, tier, role) always resolves to the same capability
    list, in the same order, with no randomness or wall-clock-dependent
    branching other than the `resolved_at` timestamp itself."""
    shop_id = effective_shop_id(db, auth)
    shop = db.get(Shop, shop_id)
    if shop is None or shop.subscription is None:
        raise CapabilityStoreError("This shop has no resolvable subscription record.")

    operating_mode = OperatingMode(shop.operating_mode)
    tier = SubscriptionTier(shop.subscription.tier)
    role = auth.user.role

    levels = _capability_levels_for(operating_mode, role)
    capabilities = [
        CapabilityEntry(id=capability_id, level=levels[capability_id])
        for capability_id in CapabilityId
    ]

    return CapabilitiesRead(
        operating_mode=operating_mode,
        tier=tier,
        role=role,
        seat_limit=shop.subscription.seat_limit,
        seats_used=count_active_technician_seats(db, shop.id),
        capabilities=capabilities,
        overrides_applied=[],
        resolved_at=datetime.now(UTC),
    )
