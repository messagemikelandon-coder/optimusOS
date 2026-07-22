"""Read-only host-disk and Docker-storage observability (Phase 2A).

Neutral leaf module, modeled on ``app/net.py``: stateless probe functions
that never raise for a real host/Docker failure and never mutate anything.
They collect host filesystem usage (via ``shutil.disk_usage``) and Docker
storage aggregates (via a read-only ``docker system df`` subprocess) so a
platform support operator can see disk pressure before it causes an outage.

Strictly read-only. This module never deletes, prunes, restarts, resizes, or
otherwise mutates any host or Docker resource -- ``docker system df`` reports
usage only, and no other docker subcommand is ever invoked.

Every host/Docker boundary is injected (``disk_usage=`` / ``run=``) with a
real default, so unit tests substitute a fake and never touch the developer's
actual machine. On any failure -- Docker CLI absent, daemon unreachable,
non-zero exit, timeout, or malformed output -- the Docker snapshot degrades to
an ``unavailable`` result with a *sanitized* reason (never the raw stderr,
which could carry host paths or secrets), kept deliberately distinct from a
healthy zero-usage state, rather than raising.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol


class _DiskUsageResult(Protocol):
    """Structural shape of what ``shutil.disk_usage`` returns -- the only three
    fields this module reads. Read-only properties so a NamedTuple (whose
    fields are read-only) satisfies it; lets a test inject any object with
    these attributes without depending on shutil's private tuple type."""

    @property
    def total(self) -> int: ...
    @property
    def used(self) -> int: ...
    @property
    def free(self) -> int: ...


# The four Docker storage categories the endpoint surfaces (stable snake_case
# keys), used as a closed type so the API response models stay type-safe.
DockerCategory = Literal["images", "containers", "volumes", "build_cache"]

# Canonical Docker storage categories the endpoint surfaces. `docker system df`
# reports these under its own `Type` labels; we normalize to stable snake_case
# keys and a fixed display order.
_DOCKER_TYPE_TO_CATEGORY: dict[str, DockerCategory] = {
    "Images": "images",
    "Containers": "containers",
    "Local Volumes": "volumes",
    "Build Cache": "build_cache",
}
_CATEGORY_ORDER: tuple[DockerCategory, ...] = ("images", "containers", "volumes", "build_cache")

# `docker` reports human sizes base-1000 with SI-style unit labels (e.g. "0B",
# "1.5GB", "10.5MB", "1.2kB"). Multipliers for parsing back to bytes.
_SIZE_UNITS: dict[str, int] = {
    "B": 1,
    "KB": 1000,
    "MB": 1000**2,
    "GB": 1000**3,
    "TB": 1000**4,
    "PB": 1000**5,
}
_SIZE_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([kKMGTP]?B)\s*$")

_DOCKER_TIMEOUT_SECONDS = 5.0


class DiskThresholdStatus(StrEnum):
    """Disk-usage severity relative to the configured thresholds."""

    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    # Distinct from OK: the filesystem usage could not be read at all, so no
    # severity can be asserted (fail-safe -- never reported as healthy).
    UNKNOWN = "unknown"


class DockerAvailability(StrEnum):
    """Whether Docker storage information could be collected at all.

    ``AVAILABLE`` means ``docker system df`` was queried and parsed -- even if
    every category is zero (a healthy empty host). ``UNAVAILABLE`` means Docker
    could not be inspected (CLI missing, daemon down, error, timeout, or
    unparseable output); this is deliberately kept distinct from a healthy
    zero-usage state.
    """

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class Freshness(StrEnum):
    """How current a served snapshot is, given the bounded-collection cache.

    ``FRESH`` = collected on this request; ``CACHED`` = served from the cache
    within its TTL; ``STALE`` = the cache is older than its TTL but was served
    anyway (a concurrent refresh was already in progress, so this request did
    not launch a second Docker subprocess)."""

    FRESH = "fresh"
    CACHED = "cached"
    STALE = "stale"


@dataclass(frozen=True)
class DiskUsage:
    """Host filesystem usage snapshot. All byte fields (and ``used_percent``)
    are ``None`` when the path could not be read -- a fail-safe, never a
    fabricated zero."""

    path: str
    total_bytes: int | None
    used_bytes: int | None
    available_bytes: int | None
    used_percent: float | None


@dataclass(frozen=True)
class DockerCategoryUsage:
    """Aggregate usage for one Docker storage category. Contains only counts
    and byte totals -- never image/container/volume names, which could leak
    tenant or host detail."""

    category: DockerCategory
    count: int | None
    size_bytes: int | None
    reclaimable_bytes: int | None


@dataclass(frozen=True)
class DockerStorage:
    availability: DockerAvailability
    reason: str | None
    categories: tuple[DockerCategoryUsage, ...]


@dataclass(frozen=True)
class StorageSnapshot:
    """One collected unit: host filesystem usage plus Docker storage. The
    single thing the bounded-collection cache stores and hands back, so a
    Docker subprocess runs at most once per TTL window regardless of request
    volume. ``disk.path`` is retained internally for diagnostics but is never
    placed in an API response or a log line (a configured label is exposed
    instead)."""

    disk: DiskUsage
    docker: DockerStorage


def collect_storage_snapshot(
    path: str,
    *,
    disk_usage: Callable[[str], _DiskUsageResult] = shutil.disk_usage,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> StorageSnapshot:
    """Collect a full storage snapshot (one disk read + one read-only
    ``docker system df``). Does not raise for the host/Docker failures the two
    probes handle (see ``read_disk_usage`` / ``read_docker_storage``). This is
    the only place the Docker subprocess is launched; the caller's cache/
    single-flight layer decides how often it runs."""
    return StorageSnapshot(
        disk=read_disk_usage(path, disk_usage=disk_usage),
        docker=read_docker_storage(run=run),
    )


def read_disk_usage(
    path: str,
    *,
    disk_usage: Callable[[str], _DiskUsageResult] = shutil.disk_usage,
) -> DiskUsage:
    """Read total/used/available/percent for ``path``. Degrades to an all-
    ``None`` snapshot on ``OSError`` (the failure ``shutil.disk_usage`` raises
    for a missing mount or permission error) rather than raising. ``disk_usage``
    is injectable so tests never touch the real filesystem."""
    try:
        usage = disk_usage(path)
    except OSError:
        return DiskUsage(
            path=path,
            total_bytes=None,
            used_bytes=None,
            available_bytes=None,
            used_percent=None,
        )
    total = int(usage.total)
    used = int(usage.used)
    available = int(usage.free)
    used_percent = round(used / total * 100, 2) if total > 0 else None
    return DiskUsage(
        path=path,
        total_bytes=total,
        used_bytes=used,
        available_bytes=available,
        used_percent=used_percent,
    )


def classify_disk_status(
    used_percent: float | None,
    *,
    warning_percent: float,
    critical_percent: float,
) -> DiskThresholdStatus:
    """Map a used-percent value to a severity. ``None`` (unreadable) maps to
    ``UNKNOWN``, never to ``OK`` -- absence of a reading is not health."""
    if used_percent is None:
        return DiskThresholdStatus.UNKNOWN
    if used_percent >= critical_percent:
        return DiskThresholdStatus.CRITICAL
    if used_percent >= warning_percent:
        return DiskThresholdStatus.WARNING
    return DiskThresholdStatus.OK


def read_docker_storage(
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    docker_binary: str = "docker",
    timeout_seconds: float = _DOCKER_TIMEOUT_SECONDS,
) -> DockerStorage:
    """Collect aggregate Docker storage usage via a read-only
    ``docker system df``. Never raises for a real Docker failure (CLI missing,
    daemon down, timeout, non-zero exit, malformed/partial output) and never
    mutates anything -- each such failure yields an ``UNAVAILABLE`` snapshot
    with a short, static reason (the raw stderr is deliberately never surfaced,
    since it can contain host paths). ``run`` is injectable so tests exercise
    the available / unavailable / malformed paths without a real Docker
    daemon."""
    command = [docker_binary, "system", "df", "--format", "{{json .}}"]
    try:
        completed = run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError:
        return _docker_unavailable("docker CLI is not installed or not on PATH")
    except subprocess.TimeoutExpired:
        return _docker_unavailable("docker system df timed out")
    except (OSError, subprocess.SubprocessError):
        return _docker_unavailable("docker system df could not be invoked")

    if completed.returncode != 0:
        # Daemon down / permission denied / etc. Do NOT include stderr -- it can
        # carry host paths or other sensitive detail.
        return _docker_unavailable("docker system df exited with a non-zero status")

    categories = _parse_docker_df(completed.stdout)
    if categories is None:
        return _docker_unavailable("docker system df output could not be parsed")
    return DockerStorage(
        availability=DockerAvailability.AVAILABLE, reason=None, categories=categories
    )


def _docker_unavailable(reason: str) -> DockerStorage:
    return DockerStorage(availability=DockerAvailability.UNAVAILABLE, reason=reason, categories=())


def _parse_docker_df(stdout: str) -> tuple[DockerCategoryUsage, ...] | None:
    """Parse ``docker system df --format '{{json .}}'`` (one JSON object per
    line). Returns ``None`` on malformed output (so the caller degrades to
    UNAVAILABLE) rather than raising. An empty-but-well-formed result with all
    zero values IS a valid AVAILABLE snapshot, not a parse failure."""
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        return None
    seen: dict[DockerCategory, DockerCategoryUsage] = {}
    for line in lines:
        try:
            obj = json.loads(line)
        except ValueError:
            # JSONDecodeError is a ValueError subclass; catching ValueError also
            # covers the JSON scanner's own int() raising on an unquoted integer
            # literal beyond Python's max-str-digits limit -- so even that
            # fails closed (None -> UNAVAILABLE) rather than raising.
            return None
        if not isinstance(obj, dict):
            return None
        docker_type = obj.get("Type")
        if not isinstance(docker_type, str):
            continue
        category = _DOCKER_TYPE_TO_CATEGORY.get(docker_type)
        if category is None:
            continue
        # Fail closed: a recognized category must carry valid TotalCount, Size,
        # and Reclaimable measurements. Numeric zero is valid; a missing,
        # malformed, negative, or otherwise unparseable required value makes the
        # whole Docker result UNAVAILABLE rather than an "available" snapshot
        # with null measurements.
        count = _parse_int(obj.get("TotalCount"))
        size = _parse_human_size(obj.get("Size"))
        reclaimable = _parse_human_size(_first_token(obj.get("Reclaimable")))
        if count is None or size is None or reclaimable is None:
            return None
        seen[category] = DockerCategoryUsage(
            category=category,
            count=count,
            size_bytes=size,
            reclaimable_bytes=reclaimable,
        )
    # Require all four canonical categories. `docker system df` always reports
    # Images/Containers/Local Volumes/Build Cache; a result missing any of them
    # is truncated/partial output and must NOT be presented as a complete
    # healthy snapshot -- degrade to unavailable instead.
    if len(seen) != len(_CATEGORY_ORDER):
        return None
    ordered: Sequence[DockerCategory] = [c for c in _CATEGORY_ORDER if c in seen]
    return tuple(seen[c] for c in ordered)


def _first_token(value: object) -> object:
    # Reclaimable is reported like "1.2GB (80%)"; keep only the size token.
    if isinstance(value, str):
        return value.split()[0] if value.strip() else value
    return value


def _parse_int(value: object) -> int | None:
    # Non-negative integers only (a count is never negative). bool is excluded
    # (it is an int subclass). Strings must be ASCII all-digits: `.isascii()`
    # guards against a Unicode digit (e.g. "²") that is `str.isdigit()`
    # true but would make `int()` raise -- keeping the fail-closed contract
    # intact (unparseable -> None -> UNAVAILABLE) rather than raising.
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isascii() and stripped.isdigit():
            # int() of a very long digit string raises ValueError (Python's
            # max-str-digits limit); catch it so a huge numeric-looking count
            # fails closed (None -> UNAVAILABLE) instead of raising.
            try:
                parsed = int(stripped)
            except (ValueError, OverflowError):
                return None
            return parsed if parsed >= 0 else None
    return None


def _parse_human_size(value: object) -> int | None:
    """Parse a docker human size like "1.5GB"/"0B" to bytes (base-1000 SI
    units). Returns ``None`` for anything unrecognized, non-finite, or too
    large to convert. In ``_parse_docker_df`` a ``None`` for a required
    category measurement makes the complete Docker result UNAVAILABLE (fail
    closed), so an invalid required size never yields an available snapshot."""
    if not isinstance(value, str):
        return None
    match = _SIZE_RE.match(value)
    if match is None:
        return None
    number, unit = match.group(1), match.group(2).upper()
    multiplier = _SIZE_UNITS.get(unit)
    if multiplier is None:
        return None
    # A very long digit string parses to float ``inf`` (or could overflow the
    # final int conversion); reject any non-finite or unconvertible result so a
    # malformed size fails closed rather than raising.
    try:
        scaled = float(number) * multiplier
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(scaled):
        return None
    try:
        return int(scaled)
    except (ValueError, OverflowError):
        return None
