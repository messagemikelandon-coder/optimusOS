#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from pathlib import Path

PATH = Path("docs/context/SESSION_HANDOFF.md")
REQUIRED = (
    "## Identity",
    "## Active task",
    "## Verified baseline",
    "## Evidence",
    "## Unverified",
    "## Unrelated preexisting changes",
    "## Blockers and risks",
    "## Exact next task",
)
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)(password|api[_-]?key|secret)\s*[:=]\s*\S+"),
)


def main() -> int:
    if not PATH.exists():
        print(f"Missing {PATH}", file=sys.stderr)
        return 1
    text = PATH.read_text(encoding="utf-8")
    missing = [heading for heading in REQUIRED if heading not in text]
    if missing:
        print("Missing required handoff headings:", *missing, sep="\n- ", file=sys.stderr)
        return 1
    if len(text.splitlines()) > 260:
        print("SESSION_HANDOFF.md is too long; keep it under 260 lines.", file=sys.stderr)
        return 1
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            print("Potential secret-like value found in handoff.", file=sys.stderr)
            return 1
    print("AI handoff structure: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
