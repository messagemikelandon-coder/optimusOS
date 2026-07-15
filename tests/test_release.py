from __future__ import annotations

import re
import tomllib
from pathlib import Path

from app import __version__

ROOT = Path(__file__).resolve().parents[1]

_SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def test_version_is_semantic_versioning_shaped() -> None:
    assert _SEMVER_PATTERN.match(__version__), (
        f"__version__ = {__version__!r} does not look like MAJOR.MINOR.PATCH semver."
    )


def test_pyproject_version_matches_app_version() -> None:
    """The two version declarations (app/__init__.py, the real source of
    truth surfaced at runtime via /health, and pyproject.toml, used for the
    packaged distribution) must never drift -- this is exactly the kind of
    staleness a real release process is supposed to prevent, not something
    to notice by hand at release time."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert pyproject["project"]["version"] == __version__
