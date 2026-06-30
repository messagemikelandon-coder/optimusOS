from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from app.config import get_settings


async def require_access_token(authorization: str | None = Header(default=None)) -> None:
    expected = get_settings().optimus_access_token
    if not expected:
        return
    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(supplied, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid Optimus access token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
