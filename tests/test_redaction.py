"""Tests for backup redaction — sanitised copies safe to share.

Backups embed real secrets (SMTP/AD/SSO/syslog passwords, tokens, keys);
redact_backup must mask them all while leaving the original untouched.
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from export_utils import redact_backup, count_backup_secrets, REDACTED


def _backup():
    return [{
        "type": "account", "path": "Acme",
        "data": {
            "settings": {
                "smtp": {"host": "mail.acme.com", "password": "hunter2"},
                "syslog": {"host": "10.0.0.1", "token": "abc123"},
                "activeDirectory": {"bindUser": "svc", "bindPassword": "p@ss"},
                "sso": {"clientId": "id", "clientSecret": "shh",
                        "privateKey": "-----BEGIN-----"},
            },
            "webhooks": [{"name": "slack", "headers":
                          {"Authorization": "Bearer xyz"}}],
            "policy": {"mode": "protect"},
        },
    }]


def test_masks_all_secret_kinds():
    redacted, count = redact_backup(_backup())
    s = redacted[0]["data"]["settings"]
    assert s["smtp"]["password"] == REDACTED
    assert s["syslog"]["token"] == REDACTED
    assert s["activeDirectory"]["bindPassword"] == REDACTED
    assert s["sso"]["clientSecret"] == REDACTED
    assert s["sso"]["privateKey"] == REDACTED
    assert redacted[0]["data"]["webhooks"][0]["headers"]["Authorization"] \
        == REDACTED
    assert count == 6


def test_keeps_non_secret_fields():
    redacted, _ = redact_backup(_backup())
    s = redacted[0]["data"]["settings"]
    assert s["smtp"]["host"] == "mail.acme.com"
    assert s["activeDirectory"]["bindUser"] == "svc"
    assert redacted[0]["data"]["policy"]["mode"] == "protect"


def test_original_not_mutated():
    original = _backup()
    snapshot = copy.deepcopy(original)
    redact_backup(original)
    assert original == snapshot  # input untouched


def test_count_matches():
    assert count_backup_secrets(_backup()) == 6
    assert count_backup_secrets([{"data": {"policy": {"mode": "x"}}}]) == 0
    assert count_backup_secrets([]) == 0


def test_empty_secret_values_not_counted():
    # A secret-named key with an empty value isn't a leak → not masked/counted.
    nodes = [{"data": {"settings": {"smtp": {"password": ""}}}}]
    redacted, count = redact_backup(nodes)
    assert count == 0
    assert redacted[0]["data"]["settings"]["smtp"]["password"] == ""
