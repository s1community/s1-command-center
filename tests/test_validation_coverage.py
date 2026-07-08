"""Guard tests: Migration Validation must compare EVERY element that backup
captures, otherwise it can report 'identical' on things it never looked at.

`_summarize_node_payload` is the validation comparison engine. These tests pin
its category coverage to `BACKUP_ELEMENTS` so a newly-added backup element
fails CI until it is also given a validation category — preventing the silent
drift that previously left STAR rules, IOCs, roles, settings, etc. unchecked.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pages import _summarize_node_payload, BACKUP_ELEMENTS, EXCL_TYPES


# Maps each backup element → the category _summarize_node_payload emits for it.
# Adding a backup element without updating this map (and the summarizer) makes
# test_map_matches_backup_elements fail by design.
ELEMENT_TO_CATEGORY = {
    "policy": "policy",
    "exclusions": "excl/*",                 # one per EXCL_TYPE
    "unified_exclusions": "unified_exclusions",
    "blocklist": "blocklist",
    "firewall_rules": "fw-rules",
    "firewall_config": "firewall_config",
    "nq_config": "nq_config",
    "nq_rules": "nq-rules",
    "device_control_rules": "dc-rules",
    "device_control_config": "device_control_config",
    "tags_firewall": "tags_firewall",
    "tags_network_quarantine": "tags_network_quarantine",
    "tags_endpoint": "tags_endpoint",
    "star_rules": "star_rules",
    "saved_filters": "saved_filters",
    "threat_intel": "threat_intel",
    "config_overrides": "config_overrides",
    "log_collection_rules": "log_collection_rules",
    "auto_upgrade_policies": "auto_upgrade_policies",
    "locations": "fw-locations",
    "settings_notifications": "settings_notifications",
    "settings_sso": "settings_sso",
    "settings_smtp": "settings_smtp",
    "settings_syslog": "settings_syslog",
    "settings_ad": "settings_ad",
    "webhooks": "webhooks",
    "scheduled_reports": "scheduled_reports",
    "roles": "roles",
    "service_users": "service_users",
    "console_users": "console_users",
    "gateways": "gateways",
    "marketplace_apps": "marketplace_apps",
    "scripts": "scripts",
}


def _full_synthetic_node():
    """A node payload (backup `data` shape) with every element populated."""
    return {
        "policy": {"inheritedFrom": None},
        "exclusions": {et: [{"value": f"e-{et}"}] for et in EXCL_TYPES},
        "unified_exclusions": [{"exclusionName": "u1"}],
        "restrictions": [{"value": "hash1"}],
        "firewall": {"rules": [{"name": "fwr"}],
                     "locations": [{"name": "loc"}],
                     "config": {"enabled": True}},
        "networkQuarantine": {"rules": [{"name": "nqr"}],
                              "config": {"enabled": True}},
        "deviceControl": {"rules": [{"name": "dcr"}],
                          "config": {"enabled": True}},
        "deepVisibility": {"filters": [{"name": "f1"}]},
        "config": {"overrides": [{"name": "o1"}],
                   "tags": {"firewall": [{"name": "tf"}],
                            "networkQuarantine": [{"name": "tn"}],
                            "deviceInventory": [{"name": "td"}]},
                   "endpointTags": [{"name": "te"}]},
        "star": [{"name": "s1"}],
        "threatIntel": [{"value": "ioc1"}],
        "logCollectionRules": [{"name": "lc"}],
        "autoUpgradePolicies": [{"name": "au"}],
        "settings": {"notifications": {"x": 1}, "sso": {"x": 1},
                     "smtp": {"x": 1}, "syslog": {"x": 1},
                     "activeDirectory": {"x": 1}},
        "webhooks": [{"name": "wh"}],
        "scheduledReports": [{"name": "sr"}],
        "roles": [{"name": "r1"}],
        "serviceUsers": [{"name": "su"}],
        "consoleUsers": [{"email": "a@b.c"}],
        "gateways": [{"name": "gw"}],
        "marketplaceApps": [{"name": "mk"}],
        "scripts": [{"scriptName": "sc"}],
    }


def test_map_matches_backup_elements():
    # If this fails, a backup element was added/removed without updating the
    # validation category map (and almost certainly _summarize_node_payload).
    assert set(ELEMENT_TO_CATEGORY) == set(BACKUP_ELEMENTS)


def test_every_backup_element_has_a_validation_category():
    emitted = {cat for cat, _cnt, _names in
               _summarize_node_payload(_full_synthetic_node())}
    for element, category in ELEMENT_TO_CATEGORY.items():
        if category == "excl/*":
            assert any(c.startswith("excl/") for c in emitted), element
        else:
            assert category in emitted, (
                f"backup element '{element}' has no validation category "
                f"'{category}' — validation would silently skip it")


def test_collections_compared_by_name():
    out = dict((c, (n, names)) for c, n, names in
               _summarize_node_payload(_full_synthetic_node()))
    assert out["star_rules"][0] == 1 and out["star_rules"][1] == ["s1"]
    assert out["roles"][0] == 1 and out["roles"][1] == ["r1"]
    assert "ioc1" in out["threat_intel"][1]
    assert out["scripts"][1] == ["sc"]


def test_config_and_settings_presence():
    full = dict((c, n) for c, n, _ in
                _summarize_node_payload(_full_synthetic_node()))
    empty = dict((c, n) for c, n, _ in _summarize_node_payload({}))
    for cat in ("firewall_config", "nq_config", "device_control_config",
                "settings_sso", "settings_ad"):
        assert full[cat] == 1, cat       # present on a populated node
        assert empty[cat] == 0, cat      # absent on an empty node → diff


def test_missing_star_rule_is_detectable():
    """Source has a STAR rule the destination lacks → summaries differ."""
    src = {"star": [{"name": "Detect-X"}]}
    dst = {"star": []}
    s = dict((c, names) for c, _n, names in _summarize_node_payload(src))
    d = dict((c, names) for c, _n, names in _summarize_node_payload(dst))
    assert "Detect-X" in s["star_rules"]
    assert "Detect-X" not in d["star_rules"]
