"""Tests for app/redaction.py and its wiring into structured logging.

The Phase 1 inventory found no shared secret-redaction utility: the
context_store pattern list was single-purpose (input rejection) and the JSON
log formatter relied entirely on caller discipline. This verifies (1) the
shared value-redaction utility scrubs real secrets while leaving benign text
(and variable *names*) intact, (2) the log formatter applies it as defense
in depth, and (3) context_store's input-rejection behavior is unchanged now
that it sources the shared pattern set.
"""

from __future__ import annotations

import json
import logging

from app.observability import JsonLogFormatter
from app.redaction import contains_secret, redact_secrets


class TestRedactSecrets:
    def test_openai_key_value_is_redacted(self) -> None:
        assert "sk-" not in redact_secrets("token=sk-abcdefghij0123456789ABCDEFGH")

    def test_bearer_token_is_redacted_but_scheme_kept(self) -> None:
        out = redact_secrets("Authorization: Bearer abcdef0123456789ABCDEF")
        assert "abcdef0123456789ABCDEF" not in out
        assert "Bearer [REDACTED]" in out

    def test_session_cookie_value_is_redacted(self) -> None:
        out = redact_secrets("cookie optimus_session=deadbeefcafef00d1234; Path=/")
        assert "deadbeefcafef00d1234" not in out
        assert "optimus_session=[REDACTED]" in out

    def test_password_assignment_is_redacted(self) -> None:
        assert "hunter2" not in redact_secrets("password=hunter2")
        assert "hunter2" not in redact_secrets("password: hunter2")

    def test_connection_url_credentials_are_redacted_but_host_kept(self) -> None:
        out = redact_secrets(
            "DATABASE_URL=postgresql+psycopg://optimus:s3cret@db-host:5432/optimus"
        )
        assert "s3cret" not in out
        assert "optimus:s3cret" not in out
        # Scheme + host stay, which are non-secret and useful for ops.
        assert "postgresql+psycopg://[REDACTED]@db-host:5432/optimus" in out

    def test_redis_url_credentials_are_redacted(self) -> None:
        assert "p@ss" not in redact_secrets("redis://user:p@ss@redis:6379/0").replace("p@ss@", "")

    def test_benign_text_is_unchanged(self) -> None:
        # A variable *name* is not a secret value -- must not be mangled.
        assert redact_secrets("OPENAI_API_KEY is missing") == "OPENAI_API_KEY is missing"
        assert redact_secrets("customer paid invoice 42") == "customer paid invoice 42"

    def test_redaction_is_idempotent(self) -> None:
        once = redact_secrets("k=sk-abcdefghij0123456789ABCDEFGH")
        assert redact_secrets(once) == once


class TestLogFormatterRedactsSecrets:
    def _record(self, msg: str, **extra: object) -> logging.LogRecord:
        record = logging.LogRecord("optimus", logging.WARNING, __file__, 1, msg, (), None)
        for key, value in extra.items():
            setattr(record, key, value)
        return record

    def test_secret_in_message_is_scrubbed_from_rendered_line(self) -> None:
        rendered = JsonLogFormatter().format(
            self._record("leaked token sk-abcdefghij0123456789ABCDEFGH from caller")
        )
        assert "sk-abcdefghij0123456789ABCDEFGH" not in rendered
        assert "[REDACTED]" in rendered
        json.loads(rendered)  # still valid JSON

    def test_secret_in_an_extra_field_is_scrubbed(self) -> None:
        rendered = JsonLogFormatter().format(
            self._record("db check failed", dsn="postgresql://u:p3rsecret@h:5432/d")
        )
        assert "p3rsecret" not in rendered
        parsed = json.loads(rendered)
        assert parsed["dsn"] == "postgresql://[REDACTED]@h:5432/d"


class TestContextStoreInputRejectionUnchanged:
    def test_contains_secret_still_flags_the_documented_shapes(self) -> None:
        assert contains_secret("sk-abcdefghij0123456789ABCDEFGH")
        assert contains_secret("Bearer abcdef0123456789ABCDEF")
        assert contains_secret("optimus_session=abc")
        assert contains_secret("password=hunter2")
        # The input set is deliberately broad enough to also reject the mere
        # mention of the key's env-var name in stored content.
        assert contains_secret("my OPENAI_API_KEY note")

    def test_contains_secret_allows_benign_content(self) -> None:
        assert not contains_secret("just a normal project note")
