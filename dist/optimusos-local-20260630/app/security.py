from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from app.models import Availability, PartOption


class UnsafeUrlError(ValueError):
    pass


def _hostname_is_public(hostname: str) -> bool:
    lowered = hostname.lower().rstrip(".")
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(".local"):
        return False

    try:
        addresses = socket.getaddrinfo(lowered, None)
    except socket.gaierror:
        # DNS can fail in offline tests. HTTPS and optional domain allowlisting still apply.
        return True

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            return False
    return True


def validate_https_url(url: str, allowed_hosts: tuple[str, ...] | None = None) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise UnsafeUrlError("Only HTTPS links are allowed.")
    if not parsed.hostname:
        raise UnsafeUrlError("URL is missing a hostname.")

    hostname = parsed.hostname.lower().rstrip(".")
    if allowed_hosts:
        normalized = {host.lower().rstrip(".") for host in allowed_hosts}
        if hostname not in normalized and not any(hostname.endswith(f".{host}") for host in normalized):
            raise UnsafeUrlError(f"Host is not allowlisted: {hostname}")

    if not _hostname_is_public(hostname):
        raise UnsafeUrlError("Private, loopback, or local-network targets are blocked.")
    return url


def sanitize_part_options(
    options: list[PartOption],
    allowed_hosts: tuple[str, ...] | None,
) -> list[PartOption]:
    sanitized: list[PartOption] = []
    for option in options:
        try:
            validate_https_url(str(option.url), allowed_hosts)
        except UnsafeUrlError:
            continue
        sanitized.append(option)
    return sanitized


@dataclass(frozen=True, slots=True)
class ApprovalDecision:
    required: bool
    reason: str
    allowed: bool = True


READ_ONLY_ACTIONS = frozenset(
    {
        "search",
        "research",
        "browse",
        "estimate",
        "lookup_price",
        "check_inventory",
        "decode_vin",
        "resolve_location",
        "calculate",
        "read_file",
    }
)
LOCAL_REVERSIBLE_ACTIONS = frozenset(
    {
        "write_file",
        "edit_code",
        "update_memory",
        "create_draft",
        "generate_invoice_pdf",
        "save_report",
        "run_tests",
    }
)
EXTERNAL_REVERSIBLE_ACTIONS = frozenset(
    {
        "reserve_part",
        "book_appointment",
        "send_message",
        "submit_form",
        "change_price",
        "schedule_event",
        "publish_post",
    }
)
FINANCIAL_OR_DESTRUCTIVE_ACTIONS = frozenset(
    {
        "purchase",
        "issue_refund",
        "delete_record",
        "delete_file",
        "rotate_credentials",
        "execute_privileged_shell",
    }
)


def approval_for_action(
    action: str,
    *,
    origin: str = "owner",
    explicit_owner_instruction: bool = False,
    current_turn_confirmation: bool = False,
    optimus_authorized: bool = False,
    autonomy_mode: str = "owner_full_control",
) -> ApprovalDecision:
    """Single-confirmation owner-control policy.

    Read-only and pricing work always runs. In owner-full-control mode, local reversible
    work runs without another confirmation. An explicit owner instruction is itself the
    approval for reversible external actions. Financial or destructive actions still
    require a current-turn confirmation so an agent cannot infer consent from old context.
    """

    normalized = action.strip().lower()
    normalized_origin = origin.strip().lower()
    owner_direct = normalized_origin == "owner"
    delegated_by_optimus = normalized_origin == "agent" and optimus_authorized

    if normalized in READ_ONLY_ACTIONS:
        return ApprovalDecision(False, "Read-only research and pricing are fully autonomous.")

    if normalized in LOCAL_REVERSIBLE_ACTIONS:
        if autonomy_mode == "owner_full_control" and (owner_direct or delegated_by_optimus):
            return ApprovalDecision(False, "Owner-full-control mode allows reversible local work.")
        return ApprovalDecision(True, "Local write access requires owner or Optimus authorization.")

    if normalized in EXTERNAL_REVERSIBLE_ACTIONS:
        if explicit_owner_instruction and (owner_direct or delegated_by_optimus):
            return ApprovalDecision(
                False,
                "The owner's explicit instruction in the current request is the approval.",
            )
        return ApprovalDecision(True, "External side effects require an explicit owner instruction.")

    if normalized in FINANCIAL_OR_DESTRUCTIVE_ACTIONS:
        if current_turn_confirmation and (owner_direct or delegated_by_optimus):
            return ApprovalDecision(False, "Current-turn owner confirmation received.")
        return ApprovalDecision(
            True,
            "Money movement or destructive actions require current-turn owner confirmation.",
        )

    if autonomy_mode == "owner_full_control" and explicit_owner_instruction and (
        owner_direct or delegated_by_optimus
    ):
        return ApprovalDecision(False, "Unknown action allowed by explicit owner instruction.")

    return ApprovalDecision(True, "Unknown actions require explicit owner authorization.")


def availability_rank(value: Availability) -> int:
    ranks = {
        Availability.CONFIRMED_IN_STOCK: 0,
        Availability.LIMITED: 1,
        Availability.UNKNOWN: 2,
        Availability.ONLINE_ONLY: 3,
        Availability.OUT_OF_STOCK: 4,
    }
    return ranks[value]
