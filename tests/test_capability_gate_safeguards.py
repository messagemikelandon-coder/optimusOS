from __future__ import annotations

import ast
from pathlib import Path

from app.capability_gate import _AVAILABLE_LEVELS
from app.capability_store import _MODE_LEVELS, _TECHNICIAN_LEVELS
from app.models import CapabilityId, CapabilityLevel, OperatingMode

# Route modules: the FastAPI app entrypoint plus every extracted APIRouter.
# These are the only files that turn an HTTP request into a call chain, so
# they are where a capability *decision* could be (wrongly) inlined or an
# enforcement mode (wrongly) activated.
_ROUTE_FILES = [Path("app/main.py"), *sorted(Path("app/api/routers").glob("*.py"))]

# (module_name, capability) pairs explicitly approved to run the gate in
# ENFORCE mode. EMPTY during the observe-only pilot: bays runs OBSERVE only,
# and no other route touches the gate at all. Adding an entry here is the
# deliberate, reviewed OBSERVE->ENFORCE flip (see the runbook in
# docs/architecture/OPERATING-MODES-ARCHITECTURE-BRIDGE.md); removing it is
# the instant rollback switch. The test below fails the build if any route
# module references ENFORCE without a matching approval, so enforcement can
# never be switched on silently.
_ENFORCE_APPROVED: frozenset[str] = frozenset()

# main.py legitimately calls resolve_capabilities() directly for the
# read-only GET /api/capabilities snapshot -- that is a report, not a gate,
# so it is the one route file allowed to bypass evaluate_capability(). Every
# other route that wants a capability decision must go through the gate.
_RESOLVE_DIRECTLY_ALLOWED = {"main.py"}


def _mode_enforce_references(tree: ast.AST) -> list[int]:
    """Line numbers of any `CapabilityGateMode.ENFORCE` attribute access or a
    bare `ENFORCE` name (e.g. from a `from ... import ENFORCE`)."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Attribute) and node.attr == "ENFORCE") or (
            isinstance(node, ast.Name) and node.id == "ENFORCE"
        ):
            lines.append(node.lineno)
    return lines


def _calls_named(tree: ast.AST, name: str) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if (isinstance(func, ast.Name) and func.id == name) or (
                isinstance(func, ast.Attribute) and func.attr == name
            ):
                lines.append(node.lineno)
    return lines


def test_no_route_module_activates_enforce_mode_without_explicit_approval() -> None:
    """The central-helper bypass guard, modeled on the tenant-boundary AST
    test (tests/test_membership_tenant_boundary.py): a route may not activate
    capability ENFORCE mode unless its module is on the (currently empty)
    _ENFORCE_APPROVED allowlist. This makes the observe-only guarantee
    structural, not just a convention -- flipping any route to enforce
    requires editing this allowlist in the same diff, which is the reviewed
    OBSERVE->ENFORCE gate."""
    violations: list[str] = []
    for path in _ROUTE_FILES:
        if not path.exists():
            continue
        tree = ast.parse(path.read_text())
        enforce_lines = _mode_enforce_references(tree)
        if enforce_lines and path.name not in _ENFORCE_APPROVED:
            for lineno in enforce_lines:
                violations.append(f"{path}:{lineno}: references ENFORCE mode")
    assert violations == [], (
        "route module(s) activate capability ENFORCE without being on "
        f"_ENFORCE_APPROVED: {violations}. During the observe-only pilot this "
        "allowlist must stay empty; adding a route is the deliberate "
        "OBSERVE->ENFORCE flip and must carry its own evidence + review."
    )


def test_router_modules_do_not_call_resolve_capabilities_directly() -> None:
    """A route wanting a capability decision must go through
    evaluate_capability() (which emits telemetry and centralizes the
    allow/deny rule), never resolve_capabilities() inline. Only main.py's
    read-only GET /api/capabilities snapshot may call the resolver directly."""
    violations: list[str] = []
    for path in _ROUTE_FILES:
        if not path.exists():
            continue
        if path.name in _RESOLVE_DIRECTLY_ALLOWED:
            continue
        tree = ast.parse(path.read_text())
        for lineno in _calls_named(tree, "resolve_capabilities"):
            violations.append(f"{path}:{lineno}: calls resolve_capabilities() directly")
    assert violations == [], (
        "route module(s) call resolve_capabilities() directly instead of "
        f"routing the decision through evaluate_capability(): {violations}."
    )


def test_enforce_approvals_reference_real_route_files() -> None:
    """Guards the allowlist itself: a stale approval (renamed/deleted route
    module) must not silently mask a future gap."""
    route_names = {path.name for path in _ROUTE_FILES}
    for entry in _ENFORCE_APPROVED:
        assert entry in route_names, f"_ENFORCE_APPROVED entry {entry!r} is not a route module"


# --- Matrix-drift guard: the in-code capability matrix is the single source,
# and this golden copy (transcribed from ADR-022 §2 /
# docs/architecture/OPERATING-MODES-ARCHITECTURE-BRIDGE.md §2) pins it so a
# silent change to app/capability_store.py fails the build until the change
# is consciously reconciled here. Not parsed from markdown at runtime. -------

_F = CapabilityLevel.FULL
_L = CapabilityLevel.LIMITED
_H = CapabilityLevel.HIDDEN
_NA = CapabilityLevel.NOT_APPLICABLE

_ADR_022_MODE_MATRIX: dict[OperatingMode, dict[CapabilityId, CapabilityLevel]] = {
    OperatingMode.SOLO: {
        CapabilityId.CUSTOMERS: _F,
        CapabilityId.VEHICLES: _F,
        CapabilityId.ESTIMATES: _F,
        CapabilityId.DIAGNOSTICS: _F,
        CapabilityId.WORK_ORDERS: _F,
        CapabilityId.INVOICES: _F,
        CapabilityId.SCHEDULING: _L,
        CapabilityId.BAYS: _H,
        CapabilityId.TECHNICIANS: _H,
        CapabilityId.PARTS: _F,
        CapabilityId.REPORTS: _L,
        CapabilityId.FIELD_FUNCTIONS: _NA,
        CapabilityId.OPTIMUS_ACTIONS: _F,
    },
    OperatingMode.MOBILE_FIELD: {
        CapabilityId.CUSTOMERS: _F,
        CapabilityId.VEHICLES: _F,
        CapabilityId.ESTIMATES: _F,
        CapabilityId.DIAGNOSTICS: _F,
        CapabilityId.WORK_ORDERS: _F,
        CapabilityId.INVOICES: _F,
        CapabilityId.SCHEDULING: _F,
        CapabilityId.BAYS: _H,
        CapabilityId.TECHNICIANS: _L,
        CapabilityId.PARTS: _L,
        CapabilityId.REPORTS: _L,
        CapabilityId.FIELD_FUNCTIONS: _F,
        CapabilityId.OPTIMUS_ACTIONS: _F,
    },
    OperatingMode.SHOP: {
        CapabilityId.CUSTOMERS: _F,
        CapabilityId.VEHICLES: _F,
        CapabilityId.ESTIMATES: _F,
        CapabilityId.DIAGNOSTICS: _F,
        CapabilityId.WORK_ORDERS: _F,
        CapabilityId.INVOICES: _F,
        CapabilityId.SCHEDULING: _F,
        CapabilityId.BAYS: _F,
        CapabilityId.TECHNICIANS: _F,
        CapabilityId.PARTS: _F,
        CapabilityId.REPORTS: _F,
        CapabilityId.FIELD_FUNCTIONS: _L,
        CapabilityId.OPTIMUS_ACTIONS: _F,
    },
}

_ADR_022_TECHNICIAN_ROW: dict[CapabilityId, CapabilityLevel] = {
    CapabilityId.CUSTOMERS: _F,
    CapabilityId.VEHICLES: _F,
    CapabilityId.ESTIMATES: _H,
    CapabilityId.DIAGNOSTICS: _F,
    CapabilityId.WORK_ORDERS: _F,
    CapabilityId.INVOICES: _H,
    CapabilityId.SCHEDULING: _H,
    CapabilityId.BAYS: _NA,
    CapabilityId.TECHNICIANS: _L,
    CapabilityId.PARTS: _L,
    CapabilityId.REPORTS: _H,
    CapabilityId.FIELD_FUNCTIONS: _H,
    CapabilityId.OPTIMUS_ACTIONS: _L,
}


def test_capability_matrix_has_no_silent_gaps() -> None:
    """Every mode (and the technician row) must assign a level to every
    capability id -- a missing cell would resolve to None and silently drift
    from the ADR."""
    for mode in OperatingMode:
        assert set(_MODE_LEVELS[mode]) == set(CapabilityId), mode
    assert set(_TECHNICIAN_LEVELS) == set(CapabilityId)
    assert set(_MODE_LEVELS) == set(OperatingMode)


def test_capability_matrix_matches_adr_022_exactly() -> None:
    """Pins app/capability_store.py's matrix to the ADR-022 §2 golden copy.
    A change to the code matrix that is not reflected here fails the build,
    forcing a conscious reconciliation with the ADR rather than silent
    drift."""
    assert _MODE_LEVELS == _ADR_022_MODE_MATRIX
    assert _TECHNICIAN_LEVELS == _ADR_022_TECHNICIAN_ROW


def test_available_levels_definition_is_full_and_limited() -> None:
    """The gate's allow/deny split must stay FULL|LIMITED = available,
    HIDDEN|NOT_APPLICABLE = unavailable -- the ADR-022 §2 legend. Pinned so a
    future edit to the gate cannot silently reclassify a level."""
    assert frozenset({CapabilityLevel.FULL, CapabilityLevel.LIMITED}) == _AVAILABLE_LEVELS
