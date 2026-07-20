"""Regression test for a Phase 1 security-kernel finding.

``integration/optimus_adapter.py``'s ``OptimusInternetSkill`` wrapped
``OptimusChatService.chat()`` and ``OptimusResearchOrchestrator.estimate_job()``
directly, with no authentication, no tenant scoping, and no rate limiting --
a total bypass of every control the security kernel enforces on the real
``/api/chat``/``/api/estimates`` endpoints. Verified to have zero runtime,
dynamic-import, plugin, script, or test dependency anywhere in this repo
before removal; its only reference was stale documentation (``INTEGRATION.md``)
describing an abandoned integration design for an external "host" that does
not exist in this workspace, removed in the same change.

This test fails if the module (or an equivalent unguarded wrapper at the
same import path) is ever reintroduced.
"""

import importlib

import pytest


def test_optimus_internet_skill_bypass_has_been_removed() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("integration.optimus_adapter")
