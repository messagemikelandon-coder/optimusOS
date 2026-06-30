from __future__ import annotations

import pytest

from app.security import UnsafeUrlError, approval_for_action, validate_https_url


def test_rejects_http() -> None:
    with pytest.raises(UnsafeUrlError):
        validate_https_url("http://example.com")


def test_rejects_non_allowlisted_host() -> None:
    with pytest.raises(UnsafeUrlError):
        validate_https_url("https://example.com/part", ("autozone.com",))


def test_accepts_subdomain_of_allowlisted_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.security._hostname_is_public", lambda _: True)
    assert validate_https_url(
        "https://www.autozone.com/parts/example",
        ("autozone.com",),
    ).startswith("https://")


def test_read_only_price_lookup_never_requires_approval() -> None:
    assert approval_for_action("lookup_price").required is False
    assert approval_for_action("check_inventory", origin="agent").required is False


def test_owner_full_control_allows_reversible_local_work() -> None:
    assert approval_for_action("edit_code", origin="owner").required is False
    assert approval_for_action(
        "write_file", origin="agent", optimus_authorized=True
    ).required is False


def test_explicit_owner_instruction_authorizes_external_reversible_action() -> None:
    assert approval_for_action(
        "send_message",
        origin="owner",
        explicit_owner_instruction=True,
    ).required is False
    assert approval_for_action("send_message", origin="agent").required is True


def test_financial_or_destructive_actions_require_current_turn_confirmation() -> None:
    assert approval_for_action(
        "purchase",
        origin="owner",
        explicit_owner_instruction=True,
    ).required is True
    assert approval_for_action(
        "purchase",
        origin="owner",
        current_turn_confirmation=True,
    ).required is False


def test_unknown_explicit_owner_action_is_allowed_in_full_control_mode() -> None:
    assert approval_for_action(
        "new_future_tool",
        origin="owner",
        explicit_owner_instruction=True,
    ).required is False


def test_zero_price_part_is_rejected() -> None:
    from pydantic import ValidationError

    from app.models import PartOption

    with pytest.raises(ValidationError):
        PartOption(
            retailer="AutoZone",
            unit_price=0,
            availability="unknown",
            url="https://www.autozone.com/test",
        )
