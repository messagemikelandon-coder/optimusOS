"""Shared FastAPI dependency aliases.

Phase 2C (router extraction) moves the app's dependency-injection aliases
here so that extracted `APIRouter` modules can import them without importing
`app.main` (which would create an import cycle: main imports the routers).
These are defined once, here, and imported by both `app.main` and each
router -- not duplicated. Nothing in this module imports `app.main` or any
router, so it is a safe leaf import for both sides.

The aliases wrap the same underlying dependency callables
(`get_settings`, `get_db_session`, the `require_*` auth functions) the app
has always used, so FastAPI behavior and test `dependency_overrides` (which
key on those underlying callables, not on these aliases) are unchanged.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.auth import (
    AuthContext,
    get_current_auth_context,
    require_authenticated_user,
    require_billing_context,
    require_owner_context,
    require_owner_or_technician_context,
    require_support_context,
    require_verified_auth_context,
)
from app.config import Settings, get_settings
from app.db import get_db_session
from app.db_models import UserAccount

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSessionDep = Annotated[Session, Depends(get_db_session)]
AuthContextDep = Annotated[AuthContext, Depends(get_current_auth_context)]
VerifiedAuthContextDep = Annotated[AuthContext, Depends(require_verified_auth_context)]
CurrentUserDep = Annotated[UserAccount, Depends(require_authenticated_user)]
OwnerAuthContextDep = Annotated[AuthContext, Depends(require_owner_context)]
OwnerOrTechnicianAuthContextDep = Annotated[
    AuthContext, Depends(require_owner_or_technician_context)
]
BillingAuthContextDep = Annotated[AuthContext, Depends(require_billing_context)]
SupportAuthContextDep = Annotated[AuthContext, Depends(require_support_context)]
