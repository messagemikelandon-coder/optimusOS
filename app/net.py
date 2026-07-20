"""Small network-readiness helpers shared across the app.

`_tcp_dependency_ready` lived in app/main.py and is used by the /ready
endpoint, by scripts/optimus_worker.py (via `from app.main import
_tcp_dependency_ready`), and by the context-dependency guard. Phase 2C
Step 2 moves the /api/context routes and their `ensure_context_dependencies`
guard into leaf modules that must not import app.main; this helper is
relocated here (a neutral leaf) so both app.main and app/api/context_deps.py
can share the single implementation without a cycle or a duplicated copy.
app.main re-imports it, so `app.main._tcp_dependency_ready` (which
scripts/optimus_worker.py imports and tests monkeypatch) is unchanged.
"""

from __future__ import annotations

import socket
from urllib.parse import urlparse


def _tcp_dependency_ready(url: str, default_port: int, timeout_seconds: float = 1.0) -> bool:
    parsed = urlparse(url)
    if not parsed.hostname:
        return False
    port = parsed.port or default_port
    try:
        with socket.create_connection((parsed.hostname, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False
