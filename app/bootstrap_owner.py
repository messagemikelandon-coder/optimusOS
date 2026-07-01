from __future__ import annotations

from app.auth import bootstrap_owner_account


def main() -> int:
    return bootstrap_owner_account()


if __name__ == "__main__":
    raise SystemExit(main())
