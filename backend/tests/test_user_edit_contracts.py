from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.api.users import update_user
from backend.app.database import Base
from backend.app.models import User
from backend.app.schemas import UserUpdate
from backend.app.security import hash_password, verify_password


@pytest.fixture
def users_db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin = User(username='contract-admin', password_hash='unused', role='admin')
        viewer = User(username='contract-viewer', password_hash='unused', role='viewer')
        db.add_all([admin, viewer])
        db.commit()
        yield db, admin, viewer
    engine.dispose()


@pytest.mark.parametrize('payload', [
    {'display_name': 'New name'},
    {'email': 'viewer@example.com'},
    {'role': 'viewer'},
    {'is_active': True},
    {'role': 'viewer', 'is_active': True, 'display_name': 'New name'},
])
def test_profile_and_unchanged_security_fields_preserve_sessions(users_db, payload):
    db, admin, viewer = users_db
    old_version = viewer.token_version
    updated = update_user(viewer.id, UserUpdate(**payload), db, admin)
    assert updated.token_version == old_version


@pytest.mark.parametrize('payload', [{'role': 'admin'}, {'is_active': False}])
def test_real_privilege_or_activation_changes_revoke_sessions(users_db, payload):
    db, admin, viewer = users_db
    old_version = viewer.token_version
    updated = update_user(viewer.id, UserUpdate(**payload), db, admin)
    assert updated.token_version == old_version + 1


def test_reenabling_account_also_revokes_preexisting_sessions(users_db):
    db, admin, viewer = users_db
    viewer.is_active = False
    db.commit()
    old_version = viewer.token_version
    updated = update_user(viewer.id, UserUpdate(is_active=True), db, admin)
    assert updated.token_version == old_version + 1


def test_password_reset_always_revokes_sessions(users_db):
    db, admin, viewer = users_db
    password = 'same-valid-password-123'
    viewer.password_hash = hash_password(password)
    db.commit()
    old_version = viewer.token_version
    updated = update_user(viewer.id, UserUpdate(password=password), db, admin)
    assert updated.token_version == old_version + 1
    assert verify_password(password, updated.password_hash)


def test_admin_can_edit_own_display_name_without_logout(users_db):
    db, admin, _ = users_db
    old_version = admin.token_version
    updated = update_user(admin.id, UserUpdate(display_name='Display name', role='admin'), db, admin)
    assert updated.token_version == old_version
