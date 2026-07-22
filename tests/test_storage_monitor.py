"""Unit tests for app/storage_monitor.py (Phase 2A).

Every host/Docker boundary is injected, so these never touch the developer's
real filesystem or a real Docker daemon.
"""

from __future__ import annotations

import json
import subprocess
from collections import namedtuple

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.storage_monitor import (
    DiskThresholdStatus,
    DockerAvailability,
    _parse_human_size,
    classify_disk_status,
    collect_storage_snapshot,
    read_disk_usage,
    read_docker_storage,
)

_FakeUsage = namedtuple("_FakeUsage", "total used free")


def _fake_disk_usage(total: int, used: int, free: int):
    def _inner(_path: str) -> _FakeUsage:
        return _FakeUsage(total=total, used=used, free=free)

    return _inner


def _fake_run(stdout: str, *, returncode: int = 0, stderr: str = ""):
    def _inner(command, **_kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(
            args=command, returncode=returncode, stdout=stdout, stderr=stderr
        )

    return _inner


_DF_ALL_CATEGORIES = "\n".join(
    [
        '{"Active":"1","Reclaimable":"500MB (33%)","Size":"1.5GB","TotalCount":"2","Type":"Images"}',
        '{"Active":"1","Reclaimable":"0B","Size":"120MB","TotalCount":"3","Type":"Containers"}',
        '{"Active":"2","Reclaimable":"0B","Size":"50MB","TotalCount":"2","Type":"Local Volumes"}',
        '{"Active":"0","Reclaimable":"200MB","Size":"200MB","TotalCount":"5","Type":"Build Cache"}',
    ]
)

_DF_ALL_ZERO = "\n".join(
    [
        '{"Active":"0","Reclaimable":"0B","Size":"0B","TotalCount":"0","Type":"Images"}',
        '{"Active":"0","Reclaimable":"0B","Size":"0B","TotalCount":"0","Type":"Containers"}',
        '{"Active":"0","Reclaimable":"0B","Size":"0B","TotalCount":"0","Type":"Local Volumes"}',
        '{"Active":"0","Reclaimable":"0B","Size":"0B","TotalCount":"0","Type":"Build Cache"}',
    ]
)


# --- disk usage ---------------------------------------------------------------


def test_read_disk_usage_computes_bytes_and_percent() -> None:
    disk = read_disk_usage("/data", disk_usage=_fake_disk_usage(1000, 800, 200))
    assert disk.path == "/data"
    assert disk.total_bytes == 1000
    assert disk.used_bytes == 800
    assert disk.available_bytes == 200
    assert disk.used_percent == 80.0


def test_read_disk_usage_zero_total_yields_none_percent_not_zero_division() -> None:
    disk = read_disk_usage("/", disk_usage=_fake_disk_usage(0, 0, 0))
    assert disk.total_bytes == 0
    assert disk.used_percent is None


def test_read_disk_usage_oserror_degrades_to_all_none() -> None:
    def _raises(_path: str):
        raise OSError("no such path")

    disk = read_disk_usage("/missing", disk_usage=_raises)
    assert disk.path == "/missing"
    assert disk.total_bytes is None
    assert disk.used_bytes is None
    assert disk.available_bytes is None
    assert disk.used_percent is None


# --- threshold classification -------------------------------------------------


@pytest.mark.parametrize(
    ("used_percent", "expected"),
    [
        (None, DiskThresholdStatus.UNKNOWN),
        (0.0, DiskThresholdStatus.OK),
        (79.99, DiskThresholdStatus.OK),
        (80.0, DiskThresholdStatus.WARNING),
        (85.0, DiskThresholdStatus.WARNING),
        (89.99, DiskThresholdStatus.WARNING),
        (90.0, DiskThresholdStatus.CRITICAL),
        (99.9, DiskThresholdStatus.CRITICAL),
    ],
)
def test_classify_disk_status_boundaries(used_percent, expected) -> None:
    assert (
        classify_disk_status(used_percent, warning_percent=80.0, critical_percent=90.0) == expected
    )


def test_classify_disk_status_none_is_unknown_never_ok() -> None:
    # Absence of a reading must never be reported as healthy.
    status = classify_disk_status(None, warning_percent=80.0, critical_percent=90.0)
    assert status is DiskThresholdStatus.UNKNOWN
    assert status is not DiskThresholdStatus.OK


# --- docker storage: available ------------------------------------------------


def test_read_docker_storage_available_parses_all_categories() -> None:
    docker = read_docker_storage(run=_fake_run(_DF_ALL_CATEGORIES))
    assert docker.availability is DockerAvailability.AVAILABLE
    assert docker.reason is None
    by_category = {c.category: c for c in docker.categories}
    assert set(by_category) == {"images", "containers", "volumes", "build_cache"}
    images = by_category["images"]
    assert images.count == 2
    assert images.size_bytes == 1_500_000_000
    assert images.reclaimable_bytes == 500_000_000
    # Category order is stable.
    assert [c.category for c in docker.categories] == [
        "images",
        "containers",
        "volumes",
        "build_cache",
    ]


def test_read_docker_storage_healthy_zero_usage_is_available_not_unavailable() -> None:
    # Required distinction: a docker daemon with zero usage is AVAILABLE with
    # zeroes, NOT reported as unavailable.
    docker = read_docker_storage(run=_fake_run(_DF_ALL_ZERO))
    assert docker.availability is DockerAvailability.AVAILABLE
    assert docker.reason is None
    assert all(c.size_bytes == 0 and c.count == 0 for c in docker.categories)


# --- docker storage: unavailable (fails safely, never raises, no leak) --------


def test_read_docker_storage_cli_missing_is_unavailable() -> None:
    def _raises(_command, **_kwargs):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("docker")

    docker = read_docker_storage(run=_raises)
    assert docker.availability is DockerAvailability.UNAVAILABLE
    assert docker.categories == ()
    assert docker.reason is not None
    assert "not installed" in docker.reason


def test_read_docker_storage_timeout_is_unavailable() -> None:
    def _raises(_command, **_kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd="docker", timeout=5.0)

    docker = read_docker_storage(run=_raises)
    assert docker.availability is DockerAvailability.UNAVAILABLE
    assert "timed out" in (docker.reason or "")


def test_read_docker_storage_malformed_output_is_unavailable_not_a_crash() -> None:
    docker = read_docker_storage(run=_fake_run("this is not json {{{"))
    assert docker.availability is DockerAvailability.UNAVAILABLE
    assert "could not be parsed" in (docker.reason or "")


def test_read_docker_storage_nonzero_exit_never_leaks_stderr() -> None:
    # Sensitive-data guarantee: a failing docker invocation's stderr (which can
    # contain host paths or secrets) must never be surfaced in the reason.
    secret_stderr = "error: DATABASE_URL=postgresql://optimus:s3cr3t@host/db unreachable"
    docker = read_docker_storage(run=_fake_run("", returncode=1, stderr=secret_stderr))
    assert docker.availability is DockerAvailability.UNAVAILABLE
    assert docker.reason is not None
    assert "s3cr3t" not in docker.reason
    assert "DATABASE_URL" not in docker.reason
    assert "non-zero" in docker.reason


# --- human size parsing -------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0B", 0),
        ("1.5GB", 1_500_000_000),
        ("10.5MB", 10_500_000),
        ("1.2kB", 1200),
        ("2TB", 2_000_000_000_000),
        ("", None),
        ("N/A", None),
        ("not-a-size", None),
        (None, None),
        (123, None),
    ],
)
def test_parse_human_size(text, expected) -> None:
    assert _parse_human_size(text) == expected


# --- exact command / no mutation ----------------------------------------------


def test_docker_command_is_exactly_system_df_and_never_mutating() -> None:
    captured: dict[str, list[str]] = {}

    def _capture(command, **_kwargs):  # type: ignore[no-untyped-def]
        captured["command"] = command
        return subprocess.CompletedProcess(
            args=command, returncode=0, stdout=_DF_ALL_CATEGORIES, stderr=""
        )

    read_docker_storage(run=_capture)
    assert captured["command"] == ["docker", "system", "df", "--format", "{{json .}}"]
    # No mutating docker verb appears as a command token (checked per token, so
    # "rm" inside "--format" is not a false positive).
    forbidden = {"prune", "rm", "rmi", "kill", "stop", "restart", "delete", "down", "exec", "run"}
    assert not (set(captured["command"]) & forbidden)


# --- partial output must not be presented as healthy --------------------------


def test_read_docker_storage_partial_output_is_unavailable_not_healthy() -> None:
    # Only two of the four expected categories -- truncated/partial output.
    partial = "\n".join(
        [
            '{"Type":"Images","TotalCount":"1","Size":"1GB","Reclaimable":"0B"}',
            '{"Type":"Containers","TotalCount":"0","Size":"0B","Reclaimable":"0B"}',
        ]
    )
    docker = read_docker_storage(run=_fake_run(partial))
    assert docker.availability is DockerAvailability.UNAVAILABLE
    assert docker.categories == ()


# --- fail closed on malformed category measurements ---------------------------


def _df_lines(
    *,
    images=("2", "1.5GB", "0B"),
    containers=("1", "120MB", "0B"),
    volumes=("2", "50MB", "0B"),
    build=("5", "200MB", "200MB"),
) -> str:
    rows = [
        ("Images", *images),
        ("Containers", *containers),
        ("Local Volumes", *volumes),
        ("Build Cache", *build),
    ]
    return "\n".join(
        json.dumps({"Type": t, "TotalCount": c, "Size": s, "Reclaimable": r, "Active": "0"})
        for (t, c, s, r) in rows
    )


def test_all_categories_present_but_malformed_count_is_unavailable() -> None:
    docker = read_docker_storage(run=_fake_run(_df_lines(images=("abc", "1.5GB", "0B"))))
    assert docker.availability is DockerAvailability.UNAVAILABLE
    assert docker.categories == ()


def test_all_categories_present_but_negative_count_is_unavailable() -> None:
    docker = read_docker_storage(run=_fake_run(_df_lines(volumes=("-1", "50MB", "0B"))))
    assert docker.availability is DockerAvailability.UNAVAILABLE


def test_all_categories_present_but_malformed_size_is_unavailable() -> None:
    docker = read_docker_storage(run=_fake_run(_df_lines(containers=("1", "??", "0B"))))
    assert docker.availability is DockerAvailability.UNAVAILABLE


def test_all_categories_present_but_malformed_reclaimable_is_unavailable() -> None:
    docker = read_docker_storage(run=_fake_run(_df_lines(build=("5", "200MB", "N/A"))))
    assert docker.availability is DockerAvailability.UNAVAILABLE


def test_missing_required_field_is_unavailable() -> None:
    # Build Cache row is missing the Reclaimable field entirely.
    missing = "\n".join(
        [
            json.dumps({"Type": "Images", "TotalCount": "1", "Size": "1GB", "Reclaimable": "0B"}),
            json.dumps(
                {"Type": "Containers", "TotalCount": "0", "Size": "0B", "Reclaimable": "0B"}
            ),
            json.dumps(
                {"Type": "Local Volumes", "TotalCount": "0", "Size": "0B", "Reclaimable": "0B"}
            ),
            json.dumps({"Type": "Build Cache", "TotalCount": "1", "Size": "1GB"}),
        ]
    )
    docker = read_docker_storage(run=_fake_run(missing))
    assert docker.availability is DockerAvailability.UNAVAILABLE


def test_valid_zero_measurements_remain_available() -> None:
    zeros = _df_lines(
        images=("0", "0B", "0B"),
        containers=("0", "0B", "0B"),
        volumes=("0", "0B", "0B"),
        build=("0", "0B", "0B"),
    )
    docker = read_docker_storage(run=_fake_run(zeros))
    assert docker.availability is DockerAvailability.AVAILABLE
    assert all(
        c.count == 0 and c.size_bytes == 0 and c.reclaimable_bytes == 0 for c in docker.categories
    )


@pytest.mark.parametrize("field", ["count", "size", "reclaimable"])
def test_absurdly_long_numeric_measurement_fails_closed_without_raising(field: str) -> None:
    # A 5,000-digit value would make int()/float()->int() raise (Python's
    # max-str-digits limit / float overflow). It must fail closed to
    # UNAVAILABLE with the sanitized parse-failure reason, never raise.
    huge_digits = "9" * 5000
    if field == "count":
        stdout = _df_lines(images=(huge_digits, "1GB", "0B"))
    elif field == "size":
        stdout = _df_lines(containers=("1", huge_digits + "GB", "0B"))
    else:
        stdout = _df_lines(build=("5", "200MB", huge_digits + "GB"))
    docker = read_docker_storage(run=_fake_run(stdout))
    assert docker.availability is DockerAvailability.UNAVAILABLE
    assert docker.reason == "docker system df output could not be parsed"
    assert docker.categories == ()


def test_unquoted_oversized_json_integer_fails_closed_without_raising() -> None:
    # An UNQUOTED >4300-digit integer literal makes json.loads' own int() raise
    # a bare ValueError (not JSONDecodeError). It must fail closed, not raise.
    huge = "9" * 5000
    stdout = '{"Type":"Images","TotalCount":' + huge + ',"Size":"1GB","Reclaimable":"0B"}'
    docker = read_docker_storage(run=_fake_run(stdout))
    assert docker.availability is DockerAvailability.UNAVAILABLE
    assert docker.reason == "docker system df output could not be parsed"


def test_ordinary_and_zero_values_remain_available_after_hardening() -> None:
    # Sanity: the overflow guards do not change normal or zero behavior.
    normal = read_docker_storage(run=_fake_run(_DF_ALL_CATEGORIES))
    assert normal.availability is DockerAvailability.AVAILABLE
    zeros = read_docker_storage(run=_fake_run(_DF_ALL_ZERO))
    assert zeros.availability is DockerAvailability.AVAILABLE
    assert all(c.size_bytes == 0 and c.count == 0 for c in zeros.categories)


def test_unicode_digit_count_fails_closed_without_raising() -> None:
    # "²" (superscript two) is str.isdigit() True but int() would raise;
    # the collector must fail closed to UNAVAILABLE, not propagate an exception.
    docker = read_docker_storage(run=_fake_run(_df_lines(images=("²", "1GB", "0B"))))
    assert docker.availability is DockerAvailability.UNAVAILABLE


def test_malformed_measurement_never_exposes_input_or_stderr() -> None:
    # A malformed Size value that looks sensitive must not appear in the reason.
    docker = read_docker_storage(
        run=_fake_run(_df_lines(images=("2", "s3cr3t-not-a-size", "0B")), stderr="s3cr3t-stderr")
    )
    assert docker.availability is DockerAvailability.UNAVAILABLE
    assert docker.reason is not None
    assert "s3cr3t" not in docker.reason
    assert docker.reason == "docker system df output could not be parsed"


# --- collect_storage_snapshot -------------------------------------------------


def test_collect_storage_snapshot_bundles_disk_and_docker() -> None:
    snap = collect_storage_snapshot(
        "/some/path",
        disk_usage=_fake_disk_usage(1000, 500, 500),
        run=_fake_run(_DF_ALL_CATEGORIES),
    )
    assert snap.disk.path == "/some/path"
    assert snap.disk.used_percent == 50.0
    assert snap.docker.availability is DockerAvailability.AVAILABLE


# --- configuration validation -------------------------------------------------


def test_settings_reject_warning_above_critical() -> None:
    with pytest.raises(ValidationError):
        Settings(disk_warning_percent=95.0, disk_critical_percent=90.0)


@pytest.mark.parametrize("ttl", [0, -1, 100_000])
def test_settings_reject_invalid_snapshot_ttl(ttl: int) -> None:
    with pytest.raises(ValidationError):
        Settings(storage_snapshot_ttl_seconds=ttl)


@pytest.mark.parametrize("percent", [-1.0, 101.0])
def test_settings_reject_out_of_range_threshold(percent: float) -> None:
    with pytest.raises(ValidationError):
        Settings(disk_warning_percent=percent)
