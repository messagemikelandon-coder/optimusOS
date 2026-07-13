#!/usr/bin/env python3
"""Scan running Docker Compose service logs for secret-shaped values.

Reusable operator tool for Phase 4 ("Full Local MVP Hardening") and for any
later staging/production log audit. Never prints the matched text itself --
only the pattern name, service, and line number -- so running this script
cannot itself become a leak vector.

Usage:
    python -m scripts.scan_logs_for_secrets --project optimus_e2e
    python -m scripts.scan_logs_for_secrets --project optimus-server --services backend worker
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

from app.config import get_settings

_GENERIC_SECRET_LABEL = re.compile(
    r"(?i)(password|api[_-]?key|secret|bearer|client[_-]?secret|auth[_-]?token)\s*[:=]\s*\S+"
)
_OPENAI_KEY = re.compile(r"sk-[A-Za-z0-9_-]{12,}")
# Any credentialed connection URL, not just Postgres -- Redis is one of the
# default scanned services, so a leaked `redis://user:pass@host` must match too.
_CREDENTIALED_URL = re.compile(r"[a-z][a-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@")
_APPROVAL_TOKEN_IN_URL = re.compile(r"token=[A-Za-z0-9_-]{20,}")


def build_patterns() -> list[tuple[str, re.Pattern[str]]]:
    """Patterns are built at call time (not import time) so the session
    cookie name always reflects the live configured value rather than a
    hardcoded guess that could drift if the setting is ever renamed."""
    settings = get_settings()
    cookie_pattern = re.compile(
        rf"{re.escape(settings.session_cookie_name)}=[A-Za-z0-9_.\-]{{16,}}"
    )
    return [
        ("openai-api-key", _OPENAI_KEY),
        ("generic-secret-label", _GENERIC_SECRET_LABEL),
        ("credentialed-url", _CREDENTIALED_URL),
        ("session-cookie-value", cookie_pattern),
        ("approval-token-in-url", _APPROVAL_TOKEN_IN_URL),
    ]


def fetch_logs(project: str, services: list[str]) -> str:
    command = ["docker", "compose", "-p", project, "logs", "--no-color", *services]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to fetch logs for project {project!r}: {result.stderr.strip()}")
    return result.stdout


def scan(log_text: str) -> list[tuple[str, int]]:
    patterns = build_patterns()
    findings: list[tuple[str, int]] = []
    for line_number, line in enumerate(log_text.splitlines(), start=1):
        for name, pattern in patterns:
            if pattern.search(line):
                findings.append((name, line_number))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="optimus_e2e", help="Docker Compose project name.")
    parser.add_argument(
        "--services",
        nargs="*",
        default=["backend", "worker", "frontend", "postgres", "redis"],
        help="Services to scan (default: all).",
    )
    args = parser.parse_args()

    log_text = fetch_logs(args.project, args.services)
    findings = scan(log_text)

    if findings:
        print(
            f"Potential secret-like values found in project {args.project!r} logs:", file=sys.stderr
        )
        for name, line_number in findings:
            print(f"- pattern={name} line={line_number}", file=sys.stderr)
        return 1

    print(f"Log secret scan: OK ({len(args.services)} service(s), project={args.project!r}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
