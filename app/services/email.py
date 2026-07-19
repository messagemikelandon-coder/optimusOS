from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger("optimus")


@dataclass(frozen=True, slots=True)
class EmailMessage:
    to: str
    subject: str
    body: str


class EmailAdapter(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class LoggingEmailAdapter:
    """Non-sending local/test email adapter (/goal Phase 5: "Use
    non-sending local/test email adapters"). No real email provider is
    integrated anywhere in this codebase -- wiring one up requires real
    provider credentials and is an explicit stop condition
    (`/goal`: "real email/SMS"), so this adapter is what every
    environment (local dev, tests, and today's deployment) actually uses.
    It logs delivery metadata only. Message bodies can contain raw
    verification/reset tokens, so they must never be written to logs.
    Tests that need to inspect a message inject an in-memory adapter.
    """

    def send(self, message: EmailMessage) -> None:
        recipient_hash = hashlib.sha256(message.to.strip().lower().encode("utf-8")).hexdigest()[:12]
        logger.info(
            "email (not sent -- no real email provider configured): recipient_hash=%s subject=%s",
            recipient_hash,
            message.subject,
            extra={"email_recipient_hash": recipient_hash, "email_subject": message.subject},
        )
