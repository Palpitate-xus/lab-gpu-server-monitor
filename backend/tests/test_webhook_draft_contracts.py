from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.app import notifier
from backend.app.api.alerts import _WebhookTestIn, test_webhook as run_webhook_test


def test_saved_url_uses_current_unsaved_template_without_saving(monkeypatch):
    observed = []
    monkeypatch.setattr(notifier, 'get_webhook_config', lambda: ('https://hook.example/saved-token', 'old-template'))
    monkeypatch.setattr(notifier, 'send_webhook', lambda *args: (observed.append(args) or True, 'sent'))
    monkeypatch.setattr(notifier, 'notify_alert', lambda *args: pytest.fail('draft testing must not fan out to channels'))
    response = run_webhook_test(_WebhookTestIn(template='new-draft-template'), object())
    assert response['ok']
    assert observed[0][:2] == ('https://hook.example/saved-token', 'new-draft-template')


def test_cleared_draft_template_tests_default_not_old_template(monkeypatch):
    observed = []
    monkeypatch.setattr(notifier, 'get_webhook_config', lambda: ('https://hook.example/saved', 'old-template'))
    monkeypatch.setattr(notifier, 'send_webhook', lambda *args: (observed.append(args) or True, 'sent'))
    run_webhook_test(_WebhookTestIn(template=''), object())
    assert observed[0][1] == notifier.DEFAULT_TEMPLATE


def test_new_url_draft_does_not_load_or_modify_stored_target(monkeypatch):
    observed = []
    monkeypatch.setattr(notifier, 'get_webhook_config', lambda: pytest.fail('new URL must use the draft target'))
    monkeypatch.setattr(notifier, 'send_webhook', lambda *args: (observed.append(args) or True, 'sent'))
    run_webhook_test(_WebhookTestIn(url='https://hook.example/new', template='new-template'), object())
    assert observed[0][:2] == ('https://hook.example/new', 'new-template')


def test_missing_stored_primary_url_is_reported_instead_of_testing_other_channels(monkeypatch):
    monkeypatch.setattr(notifier, 'get_webhook_config', lambda: ('', 'old-template'))
    monkeypatch.setattr(notifier, 'notify_alert', lambda *args: pytest.fail('missing primary target must not fan out'))
    with pytest.raises(HTTPException) as exc:
        run_webhook_test(_WebhookTestIn(), object())
    assert exc.value.status_code == 400


def test_bodyless_legacy_webhook_test_remains_compatible(monkeypatch):
    monkeypatch.setattr(notifier, 'notify_alert', lambda *args: (True, 'legacy sent'))
    assert run_webhook_test(None, object())['message'] == 'legacy sent'
