"""Regression tests for the context dependency guard (Phase 2C Step 2).

`ensure_context_dependencies` moved from app.main to app/api/context_deps.py.
Every existing context test runs with app_env="test", which makes the guard a
no-op, so its production 503-on-unreachable behavior was not directly
protected. These tests cover the guard's real logic and the fact that the
context handlers actually invoke it (the wiring), independent of app_env.
"""

from __future__ import annotations

from typing import cast

import pytest
from fastapi import HTTPException

import app.api.context_deps as context_deps
from app.api.context_deps import ensure_context_dependencies


def test_guard_is_a_noop_in_the_test_environment(settings) -> None:  # type: ignore[no-untyped-def]
    # The settings fixture is app_env="test"; the guard must return without
    # touching the network even if a dependency were unreachable.
    ensure_context_dependencies(settings)  # must not raise


def test_guard_raises_503_when_dependencies_are_unreachable(settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    prod_like = settings.model_copy(update={"app_env": "staging"})
    monkeypatch.setattr(context_deps, "_tcp_dependency_ready", lambda url, port: False)

    with pytest.raises(HTTPException) as excinfo:
        ensure_context_dependencies(prod_like)

    assert excinfo.value.status_code == 503
    detail = cast("dict[str, object]", excinfo.value.detail)
    assert detail["code"] == "context_dependencies_unavailable"
    assert set(cast("list[str]", detail["unavailable_dependencies"])) == {"postgres", "redis"}


def test_guard_reports_only_the_unreachable_dependency(settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    prod_like = settings.model_copy(update={"app_env": "staging"})
    # Postgres reachable (5432), Redis not.
    monkeypatch.setattr(context_deps, "_tcp_dependency_ready", lambda url, port: port == 5432)

    with pytest.raises(HTTPException) as excinfo:
        ensure_context_dependencies(prod_like)

    detail = cast("dict[str, object]", excinfo.value.detail)
    assert detail["unavailable_dependencies"] == ["redis"]


def test_guard_passes_when_dependencies_are_reachable(settings, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    prod_like = settings.model_copy(update={"app_env": "staging"})
    monkeypatch.setattr(context_deps, "_tcp_dependency_ready", lambda url, port: True)

    ensure_context_dependencies(prod_like)  # must not raise
