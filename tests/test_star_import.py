"""STAR rule creation payloads (issue #4).

Importing a rules file on the STAR Rules page reported "Imported 0/1" with
no reason: it posted the exported JSON unchanged, which the create endpoint
refuses three different ways, and swallowed every error. The preparation is
shared with the migration restore so the two can't drift apart again.
"""
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import migtools  # noqa: E402

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


def _exported_rule(**over):
    """A rule shaped like GET /cloud-detection/rules really returns one."""
    rule = {
        "id": "1234567890",
        "name": "Suspicious PowerShell",
        "s1ql": 'ProcessName = "powershell.exe"',
        "severity": "High",
        "status": "Active",
        "expirationMode": "Permanent",
        "createdAt": "2026-01-02T10:00:00.000000Z",
        "updatedAt": "2026-02-02T10:00:00.000000Z",
        "creator": "Someone",
        "creatorId": "42",
        "scope": "site",
        "scopeName": "US",
        "siteIds": ["9"],
        "accountId": "7",
        "generatedAlerts": 12,
        "lastAlertTime": "2026-08-01T00:00:00Z",
        "activeResponse": False,
        "expired": False,
        "templateRuleId": None,
        "treatAsThreat": None,
    }
    rule.update(over)
    return rule


# ── field stripping ────────────────────────────────────────────────────

def test_identifiers_and_audit_fields_are_removed():
    out = migtools.prepare_star_rule(_exported_rule(), NOW)
    for field in ("id", "createdAt", "updatedAt", "creator", "creatorId"):
        assert field not in out


def test_scope_fields_are_removed_because_scope_travels_in_the_filter():
    out = migtools.prepare_star_rule(_exported_rule(), NOW)
    for field in ("scope", "scopeName", "accountId"):
        assert field not in out


def test_active_response_is_removed():
    # "data: dict_values(['activeResponse']): Unknown field (code 4000010)"
    out = migtools.prepare_star_rule(_exported_rule(), NOW)
    assert "activeResponse" not in out


def test_computed_counters_are_removed():
    out = migtools.prepare_star_rule(_exported_rule(), NOW)
    assert "generatedAlerts" not in out
    assert "lastAlertTime" not in out


def test_the_rule_itself_survives():
    out = migtools.prepare_star_rule(_exported_rule(), NOW)
    assert out["name"] == "Suspicious PowerShell"
    assert out["s1ql"] == 'ProcessName = "powershell.exe"'
    assert out["severity"] == "High"


# ── nulls ──────────────────────────────────────────────────────────────

def test_null_fields_are_dropped():
    # "Field may not be null (code 4000010)" — a null means "use the default".
    out = migtools.prepare_star_rule(_exported_rule(), NOW)
    assert "templateRuleId" not in out
    assert "treatAsThreat" not in out


def test_false_and_zero_are_kept():
    out = migtools.prepare_star_rule(
        _exported_rule(treatAsThreat=False, generatedAlertsLimit=0), NOW)
    assert out["treatAsThreat"] is False
    assert out["generatedAlertsLimit"] == 0


# ── expiration clamping ────────────────────────────────────────────────

def test_an_expired_date_is_pulled_into_range():
    past = (NOW - timedelta(days=30)).isoformat()
    out = migtools.prepare_star_rule(_exported_rule(expiration=past), NOW)
    exp = datetime.fromisoformat(out["expiration"])
    assert NOW < exp <= NOW + timedelta(days=migtools.STAR_EXPIRY_LIMIT_DAYS)


def test_a_date_beyond_six_months_is_pulled_back():
    far = (NOW + timedelta(days=400)).isoformat()
    out = migtools.prepare_star_rule(_exported_rule(expiration=far), NOW)
    exp = datetime.fromisoformat(out["expiration"])
    assert exp <= NOW + timedelta(days=migtools.STAR_EXPIRY_LIMIT_DAYS)


def test_a_valid_date_is_left_alone():
    ok = (NOW + timedelta(days=30)).isoformat()
    out = migtools.prepare_star_rule(_exported_rule(expiration=ok), NOW)
    assert out["expiration"] == ok


def test_a_zulu_suffixed_date_is_understood():
    past = "2026-01-01T00:00:00.000000Z"
    out = migtools.prepare_star_rule(_exported_rule(expiration=past), NOW)
    assert out["expiration"] != past
    assert datetime.fromisoformat(out["expiration"]) > NOW


def test_an_unparseable_date_is_left_for_the_console_to_reject():
    # Better a real error message than a guessed replacement.
    out = migtools.prepare_star_rule(_exported_rule(expiration="soon"), NOW)
    assert out["expiration"] == "soon"


def test_no_expiration_stays_absent():
    out = migtools.prepare_star_rule(_exported_rule(), NOW)
    assert "expiration" not in out


# ── the whole point ────────────────────────────────────────────────────

def test_nothing_the_create_endpoint_rejects_survives():
    # The exact failure in issue #4: posting this rule unchanged returns
    # 0 created. Every known-rejected field must be gone in one pass.
    out = migtools.prepare_star_rule(
        _exported_rule(expiration=(NOW - timedelta(days=1)).isoformat()), NOW)
    rejected = migtools.STRIP_FIELDS & set(out)
    assert not rejected
    assert not [k for k, v in out.items() if v is None]
    assert datetime.fromisoformat(out["expiration"]) > NOW


def test_restore_and_ops_import_share_one_implementation():
    # If these drift, one path silently stops working — which is how the
    # Operations import came to post raw JSON while restore worked.
    import inspect
    import pages
    import pages_extra
    assert pages.migtools.prepare_star_rule is migtools.prepare_star_rule
    src = inspect.getsource(pages)
    assert "migtools.prepare_star_rule" in src

    # The page hands the work to the shared creator, which prepares the rule.
    ops = inspect.getsource(pages_extra.STARRulesPage._import)
    assert "import_star_rules" in ops
    creator = inspect.getsource(pages_extra.import_star_rules)
    assert "migtools.prepare_star_rule" in creator
    # …and it must not go back to swallowing the reason.
    assert "except Exception:\n                    pass" not in creator
