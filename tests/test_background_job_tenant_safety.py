"""Background-job tenant-safety guard (Phase 1).

The only background process today (scripts/optimus_worker.py) is a
dependency heartbeat that touches no tenant data at all -- so the risk
category "a background job reads/writes shop-scoped data without a tenant
context" does not currently exist. This test locks that in: if the worker is
ever extended to import a business-data store, an ORM model, or open a
database session, this fails, forcing whoever does it to establish an
explicit tenant context (and to reckon with how a non-request actor resolves
one) rather than silently querying across tenants.
"""

from __future__ import annotations

import ast
from pathlib import Path

_WORKER = Path("scripts/optimus_worker.py")

# Data-access surfaces a background job must not touch without first
# establishing a tenant context. If a legitimate future job needs one of
# these, that is a deliberate design decision that should update this test
# alongside a real tenant-context mechanism -- not slip in unnoticed.
_FORBIDDEN_IMPORT_SUFFIXES = ("_store", "db_models", "db")
_FORBIDDEN_SESSION_CALLS = {"get_db_session", "build_session_factory", "sessionmaker"}


def _imported_modules(tree: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_worker_touches_no_tenant_scoped_data() -> None:
    tree = ast.parse(_WORKER.read_text())

    offending_imports = [
        module
        for module in _imported_modules(tree)
        if module.startswith("app.") and module.split(".")[-1].endswith(_FORBIDDEN_IMPORT_SUFFIXES)
    ]
    assert offending_imports == [], (
        f"{_WORKER} imports data-access modules {offending_imports}; a background job "
        "must establish a tenant context before touching shop-scoped data."
    )

    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    forbidden_calls = called_names & _FORBIDDEN_SESSION_CALLS
    assert forbidden_calls == set(), (
        f"{_WORKER} opens a database session via {forbidden_calls}; a background job "
        "must establish a tenant context before querying tenant data."
    )
