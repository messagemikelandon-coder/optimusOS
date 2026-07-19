from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth import ensure_utc
from app.config import Settings
from app.db_models import EmailVerificationToken, UserAccount
from app.services.email import EmailAdapter, EmailMessage


class EmailVerificationError(Exception):
    pass


class EmailVerificationTokenError(EmailVerificationError):
    pass


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def request_email_verification(
    db: Session, settings: Settings, user: UserAccount, email_adapter: EmailAdapter
) -> None:
    """Generates a new verification token for `user`, revokes any prior
    still-active token for that account first (single active token per
    user at a time), and sends the raw token via the non-sending email
    adapter (/goal Phase 5). Raises if the account has no email on file
    or is already verified -- both real, user-facing conditions, not
    left to a raw constraint violation.
    """
    # Serialize resend requests for this account. Without this lock, two
    # concurrent resends could each revoke the old token and then create
    # two independently usable "active" replacements.
    locked_user = db.scalar(select(UserAccount).where(UserAccount.id == user.id).with_for_update())
    if locked_user is None:
        raise EmailVerificationError("This account is unavailable.")
    if not locked_user.email:
        raise EmailVerificationError("This account has no email address to verify.")
    if locked_user.email_verified_at is not None:
        raise EmailVerificationError("This email address is already verified.")

    db.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_account_id == user.id,
            EmailVerificationToken.status == "active",
        )
        .values(status="revoked", revoked_at=datetime.now(UTC))
    )

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(hours=settings.email_verification_token_ttl_hours)
    db.add(
        EmailVerificationToken(
            user_account_id=locked_user.id,
            token_hash=_hash_token(token),
            status="active",
            expires_at=expires_at,
        )
    )
    db.commit()

    email_adapter.send(
        EmailMessage(
            to=locked_user.email,
            subject="Verify your OptimusOS email address",
            body=(
                f"Hi {locked_user.display_name},\n\n"
                "Confirm your email address with this verification code:\n\n"
                f"{token}\n\n"
                f"This code expires in {settings.email_verification_token_ttl_hours} hour(s) "
                "and can only be used once. If you didn't request this, you can ignore it."
            ),
        )
    )


def confirm_email_verification(db: Session, token: str) -> UserAccount:
    """Validates a raw verification token and marks the owning account's
    email as verified. Every failure path (unknown token, already-used
    token, revoked token, expired token) raises the same
    `EmailVerificationTokenError` with a generic message -- distinct
    wording per failure reason would let a caller enumerate which
    tokens exist, the same account-enumeration class of issue fixed for
    signup conflicts in /goal Phase 4 slice 1.
    """
    generic_error = "This verification code is invalid or has expired."
    record = db.scalar(
        select(EmailVerificationToken)
        .where(EmailVerificationToken.token_hash == _hash_token(token))
        .with_for_update()
    )
    if record is None or record.status != "active":
        raise EmailVerificationTokenError(generic_error)
    if ensure_utc(record.expires_at) <= datetime.now(UTC):
        record.status = "expired"
        db.add(record)
        db.commit()
        raise EmailVerificationTokenError(generic_error)

    user = db.get(UserAccount, record.user_account_id)
    if user is None:
        raise EmailVerificationTokenError(generic_error)

    record.status = "used"
    record.used_at = datetime.now(UTC)
    user.email_verified_at = datetime.now(UTC)
    db.add(record)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
