from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import AuthContext, hash_password
from app.config import Settings
from app.db_models import AuthSession, Shop, ShopMembership, UserAccount
from app.shop_store import (
    ShopNotFoundError,
    create_shop_for_new_owner,
    get_current_shop,
    get_current_shop_settings,
    list_current_shop_memberships,
)


def _auth_for(db_session: Session, user: UserAccount) -> AuthContext:
    auth_session = AuthSession(
        user_id=user.id,
        token_hash=f"shop-store-test-{user.id}",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(auth_session)
    db_session.commit()
    db_session.refresh(auth_session)
    return AuthContext(user=user, session=auth_session)


def _real_owner(db_session: Session) -> UserAccount:
    owner = db_session.scalar(select(UserAccount).where(UserAccount.role == "owner"))
    assert owner is not None
    return owner


def test_bootstrap_owner_account_creates_a_shop(settings: Settings, db_session: Session) -> None:
    # db_session's fixture already ran bootstrap_owner_account -- confirms
    # the fresh-install path (zero pre-existing owners) now creates a Shop,
    # not just the owner account, closing the gap where a brand-new install
    # would otherwise end up with an owner but no shop at all.
    owner = _real_owner(db_session)
    auth = _auth_for(db_session, owner)

    shop = get_current_shop(db_session, auth)

    assert shop.display_name == settings.business_name
    assert shop.status == "active"
    assert shop.timezone == "America/Chicago"
    assert shop.currency == "USD"
    # Never fabricated -- no real value exists anywhere in this codebase.
    assert shop.address_line_1 is None
    assert shop.phone is None
    assert shop.email is None


def test_bootstrap_owner_account_creates_shop_settings_from_real_config(
    settings: Settings, db_session: Session
) -> None:
    owner = _real_owner(db_session)
    auth = _auth_for(db_session, owner)

    shop_settings = get_current_shop_settings(db_session, auth)

    assert shop_settings.labor_rate == settings.labor_rate
    assert shop_settings.mobile_service_fee == settings.mobile_service_fee
    assert shop_settings.shop_supplies_percent == settings.shop_supplies_percent
    assert shop_settings.parts_tax_rate == settings.parts_tax_rate
    assert shop_settings.operating_hours is None
    assert shop_settings.estimate_terms_text is None


def test_bootstrap_owner_account_creates_owner_membership(
    settings: Settings, db_session: Session
) -> None:
    owner = _real_owner(db_session)
    auth = _auth_for(db_session, owner)

    memberships = list_current_shop_memberships(db_session, auth)

    assert len(memberships) == 1
    assert memberships[0].user_account_id == owner.id
    assert memberships[0].role == "owner"
    assert memberships[0].is_active is True


def test_technician_sharing_owner_shop_membership_can_read_the_shop(
    settings: Settings, db_session: Session
) -> None:
    owner = _real_owner(db_session)
    technician = UserAccount(
        username="tech.one",
        display_name="Tech One",
        role="technician",
        shop_owner_id=owner.id,
        password_hash=hash_password("technician-password-123"),
        is_active=True,
    )
    db_session.add(technician)
    db_session.commit()
    db_session.refresh(technician)

    # This slice does not yet wire create_technician_record to insert a
    # ShopMembership row automatically (deferred; see KNOWN_ISSUES.md) --
    # inserted directly here to test list_current_shop_memberships's own
    # query logic independent of that separately-tracked gap.
    owner_shop = db_session.scalar(select(Shop))
    assert owner_shop is not None
    db_session.add(
        ShopMembership(shop_id=owner_shop.id, user_account_id=technician.id, role="technician")
    )
    db_session.commit()

    technician_auth = _auth_for(db_session, technician)
    # Technicians resolve to their owner's shop via effective_owner_id.
    shop = get_current_shop(db_session, technician_auth)
    assert shop.id == owner_shop.id

    memberships = list_current_shop_memberships(db_session, _auth_for(db_session, owner))
    roles = {membership.role for membership in memberships}
    assert roles == {"owner", "technician"}


def test_account_with_no_shop_membership_raises_not_found(
    settings: Settings, db_session: Session
) -> None:
    orphan_owner = UserAccount(
        username="orphan.owner",
        display_name="Orphan Owner",
        role="owner",
        password_hash=hash_password("orphan-password-123"),
        is_active=True,
    )
    db_session.add(orphan_owner)
    db_session.commit()
    db_session.refresh(orphan_owner)

    auth = _auth_for(db_session, orphan_owner)
    with pytest.raises(ShopNotFoundError):
        get_current_shop(db_session, auth)


def test_create_shop_for_new_owner_is_not_fabricated_beyond_known_config(
    settings: Settings, db_session: Session
) -> None:
    second_owner = UserAccount(
        username="second.owner",
        display_name="Second Owner",
        role="owner",
        password_hash=hash_password("second-owner-password-123"),
        is_active=True,
    )
    db_session.add(second_owner)
    db_session.commit()
    db_session.refresh(second_owner)

    shop = create_shop_for_new_owner(db_session, settings, second_owner)
    db_session.commit()

    assert shop.display_name == settings.business_name
    assert shop.legal_business_name is None
    assert shop.settings is not None
    assert shop.settings.labor_rate == settings.labor_rate
    assert len(shop.memberships) == 1
    assert shop.memberships[0].user_account_id == second_owner.id
    assert shop.memberships[0].role == "owner"


def test_shop_membership_uniqueness_is_enforced(settings: Settings, db_session: Session) -> None:
    owner = _real_owner(db_session)
    shop = db_session.scalar(select(Shop))
    assert shop is not None

    db_session.add(ShopMembership(shop_id=shop.id, user_account_id=owner.id, role="manager"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_shop_membership_role_check_constraint_is_enforced(
    settings: Settings, db_session: Session
) -> None:
    owner = _real_owner(db_session)
    technician = UserAccount(
        username="constraint.tech",
        display_name="Constraint Tech",
        role="technician",
        shop_owner_id=owner.id,
        password_hash=hash_password("technician-password-123"),
        is_active=True,
    )
    db_session.add(technician)
    db_session.commit()
    db_session.refresh(technician)

    shop = db_session.scalar(select(Shop))
    assert shop is not None
    db_session.add(
        ShopMembership(shop_id=shop.id, user_account_id=technician.id, role="not-a-real-role")
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_shop_status_check_constraint_is_enforced(settings: Settings, db_session: Session) -> None:
    db_session.add(Shop(display_name="Bad Status Shop", status="not-a-real-status"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
