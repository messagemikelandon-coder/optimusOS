from __future__ import annotations

from app.auth import bootstrap_support_account


def main() -> int:
    return bootstrap_support_account()


if __name__ == "__main__":
    raise SystemExit(main())
