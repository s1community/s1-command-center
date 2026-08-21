"""Guard test: every element the backup captures must also be RESTORED.

Backup, validation and the restore report are all driven by
``pages.BACKUP_ELEMENTS``. Before this test, ``tags_endpoint`` was captured by
backup, counted by validation and offered as a restore checkbox — but the
restore loop had no branch for it, so a targeted "restore tags" run reported
nothing at all and silently created nothing on the destination (reported by
Joshua Tooley, 2026-08).

The restore loop gates each element on ``"<element>" in elements``. Anything
that is deliberately not restored has to be declared here with a reason, so
adding a new backup element without a restore branch fails CI instead of
shipping as a silent no-op.
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import s1_api
from pages import BACKUP_ELEMENTS, RestorePage


# Restored, but driven by the backed-up `settings` payload rather than an
# `in elements` gate — the element checkbox is honoured at BACKUP time, so a
# setting that wasn't captured simply isn't present to push.
_DATA_DRIVEN = {
    "settings_notifications": '("notifications", api.set_notification_settings)',
    "settings_sso": 'stg.get("sso")',
    "settings_smtp": 'stg.get("smtp")',
    "settings_syslog": '("syslog", api.set_syslog_settings)',
    "settings_ad": '("activeDirectory", api.set_ad_settings)',
}

# Captured for reporting/audit only — intentionally never written to the
# destination.
_NOT_RESTORED = {
    # API tokens can't be migrated; a service user must be re-created (and a
    # new token issued) on the destination by hand.
    "service_users",
    # Proxy/gateway infrastructure is environment-specific.
    "gateways",
}


def _restore_source() -> str:
    return inspect.getsource(RestorePage._run_restore)


def test_every_backup_element_is_restored_or_declared():
    src = _restore_source()
    missing = []
    for element in BACKUP_ELEMENTS:
        if element in _NOT_RESTORED:
            continue
        if element in _DATA_DRIVEN:
            assert _DATA_DRIVEN[element] in src, (
                f"'{element}' is documented as data-driven but its payload "
                f"key {_DATA_DRIVEN[element]} is gone from the restore loop")
            continue
        if f'"{element}" in elements' not in src:
            missing.append(element)
    assert not missing, (
        "backup elements with no restore branch — they would be captured and "
        f"then silently skipped on restore: {missing}")


def test_declared_exceptions_are_real_elements():
    known = set(BACKUP_ELEMENTS)
    assert set(_DATA_DRIVEN) <= known
    assert _NOT_RESTORED <= known


def test_endpoint_tags_restore_uses_the_tag_manager_api():
    # Both halves of `tags_endpoint` must be pushed: device-inventory tags go
    # through /tags, unified endpoint tags through /tag-manager.
    src = _restore_source()
    assert '"tags_endpoint" in elements' in src
    assert "device-inventory" in src
    assert "create_endpoint_tag" in src


def test_tag_restore_filters_inherited_tags():
    # /tags returns inherited tags at every level; restoring them re-creates
    # parent tags at each child scope.
    assert "_tags_for_scope" in _restore_source()


def test_endpoint_tag_api_paths():
    # /endpoint-tags is not a real S1 route — calling it 404s, which the
    # backup swallows as "n/a".
    listing = inspect.getsource(s1_api.S1API.get_endpoint_tags)
    create = inspect.getsource(s1_api.S1API.create_endpoint_tag)
    assert "/agents/tags" in listing and "/endpoint-tags" not in listing
    assert "/tag-manager" in create and "/endpoint-tags" not in create
