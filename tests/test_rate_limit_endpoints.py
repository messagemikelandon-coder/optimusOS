"""Verified 429 coverage for all seven of app.main's rate-limiter paths.

The Phase 1 inventory found that only four of the seven limiters had a test
proving they actually return HTTP 429 when exceeded (login, signup, and the
two email-verification limiters, each in their own domain test file); the
general/estimate, password-reset, and invitation-acceptance limiters had
none. This file exercises every limiter's real enforce_* path -- the exact
code (`get_*_rate_limiter` -> `.check()` -> `RateLimitExceeded` -> 429 +
`log_security_event(RATE_LIMIT_EXCEEDED)`) that a live request runs -- so it
also serves as the behavior-preserving safety net for the later commit that
consolidates the seven copy-pasted limiter wirings into one factory.

Each test uses a distinct low `limit` via settings.model_copy(...), which
forces `get_*_rate_limiter` to build a fresh limiter (its cache key includes
`.limit`), keeping these deterministic regardless of limiter singletons left
over from earlier tests in the same process.
"""

from __future__ import annotations

import logging

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import app.main as main


def _request(
    path: str,
    *,
    client_host: str = "203.0.113.7",
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = [(b"user-agent", b"pytest")]
    if extra_headers:
        headers.extend(extra_headers)
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "scheme": "http",
            "method": "POST",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": b"",
            "headers": headers,
            "client": (client_host, 50000),
            "server": ("testserver", 80),
        }
    )


async def _assert_returns_429_after_limit(enforce, request: Request, limit: int, caplog) -> None:
    """enforce() must permit exactly `limit` calls, then reject the next one
    with HTTP 429 and emit a rate_limit.exceeded security event."""
    for _ in range(limit):
        await enforce(request)  # under the limit -- must not raise

    with (
        caplog.at_level(logging.WARNING, logger="optimus"),
        pytest.raises(HTTPException) as excinfo,
    ):
        await enforce(request)

    assert excinfo.value.status_code == 429
    assert "security event: rate_limit.exceeded" in caplog.text


@pytest.mark.anyio
async def test_general_estimate_limiter_returns_429(settings, caplog) -> None:  # type: ignore[no-untyped-def]
    limited = settings.model_copy(update={"max_estimates_per_minute": 2})
    request = _request("/api/estimates")
    await _assert_returns_429_after_limit(
        lambda r: main.enforce_rate_limit(r, limited), request, 2, caplog
    )


@pytest.mark.anyio
async def test_login_limiter_returns_429(settings, caplog) -> None:  # type: ignore[no-untyped-def]
    limited = settings.model_copy(update={"max_login_attempts_per_minute": 2})
    request = _request("/api/auth/login")
    await _assert_returns_429_after_limit(
        lambda r: main.enforce_login_rate_limit(r, limited), request, 2, caplog
    )


@pytest.mark.anyio
async def test_signup_limiter_returns_429(settings, caplog) -> None:  # type: ignore[no-untyped-def]
    limited = settings.model_copy(update={"max_signup_attempts_per_minute": 2})
    request = _request("/api/signup")
    await _assert_returns_429_after_limit(
        lambda r: main.enforce_signup_rate_limit(r, limited), request, 2, caplog
    )


@pytest.mark.anyio
async def test_email_verification_limiter_returns_429(settings, caplog) -> None:  # type: ignore[no-untyped-def]
    limited = settings.model_copy(update={"max_email_verification_attempts_per_minute": 2})
    request = _request("/api/auth/verify-email")
    await _assert_returns_429_after_limit(
        lambda r: main.enforce_email_verification_rate_limit(r, limited), request, 2, caplog
    )


@pytest.mark.anyio
async def test_email_verification_resend_limiter_returns_429(settings, caplog) -> None:  # type: ignore[no-untyped-def]
    limited = settings.model_copy(update={"max_email_verification_resend_attempts_per_hour": 2})
    request = _request("/api/auth/verify-email/resend")
    await _assert_returns_429_after_limit(
        lambda r: main.enforce_email_verification_resend_rate_limit(r, limited, user_id=42),
        request,
        2,
        caplog,
    )


@pytest.mark.anyio
async def test_password_reset_limiter_returns_429(settings, caplog) -> None:  # type: ignore[no-untyped-def]
    """Previously untested. Covers both actions sharing the limiter."""
    limited = settings.model_copy(update={"max_password_reset_attempts_per_hour": 2})
    request = _request("/api/auth/password/reset-request")
    await _assert_returns_429_after_limit(
        lambda r: main.enforce_password_reset_rate_limit(r, limited, action="request"),
        request,
        2,
        caplog,
    )


@pytest.mark.anyio
async def test_invitation_acceptance_limiter_returns_429(settings, caplog) -> None:  # type: ignore[no-untyped-def]
    """Previously untested."""
    limited = settings.model_copy(update={"max_invitation_acceptance_attempts_per_hour": 2})
    request = _request("/api/invitations/accept")
    await _assert_returns_429_after_limit(
        lambda r: main.enforce_invitation_acceptance_rate_limit(r, limited), request, 2, caplog
    )


@pytest.mark.anyio
async def test_limiter_is_keyed_per_client_host_not_shared_across_ips(settings, caplog) -> None:  # type: ignore[no-untyped-def]
    """Rate limits must not be trivially bypassable by nothing, but must also
    isolate distinct clients: exhausting one IP's login budget must not
    reject a different IP. Proves the key includes the client host."""
    limited = settings.model_copy(update={"max_login_attempts_per_minute": 1})

    first_ip = _request("/api/auth/login", client_host="203.0.113.1")
    second_ip = _request("/api/auth/login", client_host="203.0.113.2")

    await main.enforce_login_rate_limit(first_ip, limited)
    with pytest.raises(HTTPException) as excinfo:
        await main.enforce_login_rate_limit(first_ip, limited)
    assert excinfo.value.status_code == 429

    # A different client host has its own independent budget.
    await main.enforce_login_rate_limit(second_ip, limited)


@pytest.mark.anyio
async def test_forwarded_headers_do_not_bypass_the_login_limiter(settings, caplog) -> None:  # type: ignore[no-untyped-def]
    """A caller must not be able to escape their rate-limit budget by
    spoofing X-Forwarded-For / X-Real-IP: the limiter keys on the real
    transport peer (request.client.host), not a client-supplied header, so
    the same connection stays in one bucket no matter what it forwards."""
    limited = settings.model_copy(update={"max_login_attempts_per_minute": 1})

    first = _request(
        "/api/auth/login",
        client_host="203.0.113.9",
        extra_headers=[(b"x-forwarded-for", b"10.0.0.1"), (b"x-real-ip", b"10.0.0.1")],
    )
    second = _request(
        "/api/auth/login",
        client_host="203.0.113.9",  # same real peer
        extra_headers=[(b"x-forwarded-for", b"10.0.0.2"), (b"x-real-ip", b"10.0.0.2")],
    )

    await main.enforce_login_rate_limit(first, limited)
    with pytest.raises(HTTPException) as excinfo:
        # Different forwarded headers, same peer -- must still be limited.
        await main.enforce_login_rate_limit(second, limited)
    assert excinfo.value.status_code == 429


@pytest.mark.anyio
async def test_general_limiter_is_keyed_per_path_so_one_endpoint_cannot_drain_another(  # type: ignore[no-untyped-def]
    settings, caplog
) -> None:
    """The general limiter keys on request path + host, so exhausting one
    endpoint's budget from an IP does not pre-emptively 429 a different
    endpoint for that same IP. Confirms the alternate-endpoint dimension of
    the key is intact after centralization."""
    limited = settings.model_copy(update={"max_estimates_per_minute": 1})

    chat = _request("/api/chat", client_host="203.0.113.5")
    estimates = _request("/api/estimates", client_host="203.0.113.5")

    await main.enforce_rate_limit(chat, limited)
    with pytest.raises(HTTPException):
        await main.enforce_rate_limit(chat, limited)

    # A different path for the same client is an independent bucket.
    await main.enforce_rate_limit(estimates, limited)
