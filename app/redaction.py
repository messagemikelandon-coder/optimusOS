"""Shared secret-handling patterns and redaction (Phase 1 security kernel).

Two related but distinct jobs, deliberately kept separate:

* INPUT REJECTION (``SECRET_INPUT_PATTERNS`` / :func:`contains_secret`) --
  conservative: used by app/context_store.py to refuse to *store* a
  user-supplied value that looks like it might carry a secret, including the
  mere mention of a variable name like ``OPENAI_API_KEY``. Rejecting a bit
  too eagerly is fine for stored user content.

* OUTPUT REDACTION (:func:`redact_secrets`) -- used as a defense-in-depth
  scrubbing pass on log output. This must only remove *actual secret
  values* (a key, a token, a password assignment, credentials embedded in a
  connection URL), never a bare variable name, so it doesn't mangle a
  legitimate operational line such as "OPENAI_API_KEY is missing".

Redaction is a safety net, not a license to log secrets: call sites remain
responsible for not passing credentials in the first place.
"""

from __future__ import annotations

import re

_REDACTED = "[REDACTED]"

# Conservative input-rejection set. This is the exact set app/context_store.py
# has always used to reject secret-shaped stored values; it now lives here so
# there is one canonical definition. Behavior is unchanged.
SECRET_INPUT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bOPENAI_API_KEY\b", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{16,}\b", re.IGNORECASE),
    re.compile(r"\boptimus_session=", re.IGNORECASE),
    re.compile(r"\bpassword\s*[:=]\s*\S+", re.IGNORECASE),
)


def contains_secret(text: str) -> bool:
    """True if the text matches any input-rejection pattern."""
    return any(pattern.search(text) for pattern in SECRET_INPUT_PATTERNS)


# Value-only redaction rules for log output. Each entry is (pattern,
# replacement). Unlike the input set, this does NOT include the bare
# ``OPENAI_API_KEY`` name -- redacting a variable name out of log messages
# would corrupt legitimate operational logging.
_REDACTION_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # OpenAI-style secret key value.
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), _REDACTED),
    # Bearer token value.
    (re.compile(r"\bBearer\s+[A-Za-z0-9._-]{16,}\b", re.IGNORECASE), f"Bearer {_REDACTED}"),
    # Session cookie value (redact the value, keep the name for context).
    (re.compile(r"\boptimus_session=[^\s;\"']+", re.IGNORECASE), f"optimus_session={_REDACTED}"),
    # password: <value> / password=<value>.
    (re.compile(r"\b(password\s*[:=]\s*)\S+", re.IGNORECASE), rf"\1{_REDACTED}"),
    # Credentials embedded in a connection URL (postgres/redis/etc.):
    # scheme://user:pass@host -> scheme://[REDACTED]@host. Keeps the scheme
    # and host (useful for ops) while removing the user:password.
    (
        re.compile(r"(?P<scheme>\b[a-z][a-z0-9+.\-]*://)[^\s:/@]+:[^\s/@]+@"),
        rf"\g<scheme>{_REDACTED}@",
    ),
)


def redact_secrets(text: str) -> str:
    """Replace any actual secret values in ``text`` with a placeholder.
    Idempotent and safe to run over already-clean text (a no-op then)."""
    for pattern, replacement in _REDACTION_RULES:
        text = pattern.sub(replacement, text)
    return text
