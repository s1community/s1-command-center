"""Unit tests for the pure restore/backup helper functions in pages.py.

These functions decide what gets sent to a destination console during a
migration, so they are the highest-value pure logic to lock down with tests.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pages import (
    _strip_non_printable,
    _whitelist,
    _scope,
    _clean_for_restore,
    _drop_forensics_triggering,
    _build_role_payload,
    _role_scope_filter,
    _overlay_role_permissions,
    explain_error,
    _is_exists_error,
    _FW_RULE_FIELDS,
    _rules_for_scope,
    _scope_inherits_config,
    _sched_report_payload,
    _SCHED_REPORT_DEFAULTS,
    _strip_unknown_fields,
    _excl_key,
    _ue_rename_payload,
    _nq_rules_for_scope,
    _star_rules_for_scope,
    _tags_for_scope,
    _tag_payload,
    _endpoint_tag_payload,
    _endpoint_tags_for_scope,
    _overrides_for_scope,
    _override_payload,
)


# ── _strip_non_printable ────────────────────────────────────────────────

def test_strip_removes_zero_width_and_bom():
    dirty = "C:\\Program​ Files﻿\\app.exe‎"
    assert _strip_non_printable(dirty) == "C:\\Program Files\\app.exe"


def test_strip_keeps_ordinary_text():
    clean = "/usr/local/bin/agent"
    assert _strip_non_printable(clean) == clean


def test_strip_removes_bidi_marks():
    assert _strip_non_printable("a‮b‬c") == "abc"


def test_strip_passes_through_non_strings():
    assert _strip_non_printable(None) is None
    assert _strip_non_printable(123) == 123
    assert _strip_non_printable(["x"]) == ["x"]


# ── _whitelist ──────────────────────────────────────────────────────────

def test_whitelist_keeps_only_allowed():
    obj = {"a": 1, "b": 2, "c": 3}
    assert _whitelist(obj, {"a", "c"}) == {"a": 1, "c": 3}


def test_whitelist_drops_none_values():
    obj = {"a": 1, "b": None}
    assert _whitelist(obj, {"a", "b"}) == {"a": 1}


def test_whitelist_empty_when_nothing_allowed():
    assert _whitelist({"a": 1}, set()) == {}


# ── firewall multi-IP rules ─────────────────────────────────────────────
# S1 v2.1 stores multiple IPs in the plural `remoteHosts`/`localHosts`
# arrays (each entry = {type, values:[...]}). The legacy singular
# remoteHost/localHost only carries the first host, so the whitelist must
# keep the plural arrays or every extra IP is silently dropped on restore.

def test_fw_whitelist_keeps_plural_host_arrays():
    assert "remoteHosts" in _FW_RULE_FIELDS
    assert "localHosts" in _FW_RULE_FIELDS


def test_fw_whitelist_preserves_multi_ip_rule():
    rule = {
        "name": "multi-ip",
        "action": "Allow",
        "remoteHost": {"type": "addresses", "values": ["10.0.0.1"]},
        "remoteHosts": [
            {"type": "addresses", "values": ["10.0.0.1", "10.0.0.2"]},
            {"type": "addresses", "values": ["10.0.0.3"]},
        ],
        "id": "should-be-dropped",
        "createdAt": "2024-01-01",
    }
    cleaned = _whitelist(rule, _FW_RULE_FIELDS)
    # all IPs survive via the plural array
    all_ips = [ip for host in cleaned["remoteHosts"] for ip in host["values"]]
    assert all_ips == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
    # read-only server fields are stripped
    assert "id" not in cleaned
    assert "createdAt" not in cleaned


# ── _rules_for_scope (inherited-rule leak guard) ────────────────────────
# The firewall/device-control APIs return inherited rules at every level.
# A site restore must NOT re-create the account/global rules that flow down
# to it, or unchecking the Account level still restores account rules.

def test_rules_for_scope_keeps_only_matching_level():
    rules = [
        {"name": "acct-rule", "scope": "account"},
        {"name": "site-rule", "scope": "site"},
        {"name": "group-rule", "scope": "group"},
        {"name": "global-rule", "scope": "global"},
    ]
    assert [r["name"] for r in _rules_for_scope(rules, "site")] == ["site-rule"]
    assert [r["name"] for r in _rules_for_scope(rules, "account")] == ["acct-rule"]
    assert [r["name"] for r in _rules_for_scope(rules, "global")] == ["global-rule"]


def test_rules_for_scope_is_case_insensitive():
    rules = [{"name": "s", "scope": "SITE"}]
    assert _rules_for_scope(rules, "site") == rules


def test_rules_for_scope_drops_missing_scope_and_handles_empty():
    assert _rules_for_scope([{"name": "x"}], "site") == []
    assert _rules_for_scope(None, "site") == []
    assert _rules_for_scope([], "account") == []


# ── _excl_key ─────────────────────────────────────────────────────
# Legacy and unified exclusions are two views of one object; only the
# unified view has the name the console displays.

def test_excl_key_matches_the_legacy_and_unified_view_of_one_exclusion():
    legacy = {"type": "path", "osType": "windows", "value": "C:\\a.exe",
              "description": "ticket 42"}
    unified = {"type": "path", "osType": "windows", "value": "C:\\a.exe",
               "exclusionName": "Vendor agent", "threatType": "EDR"}
    assert _excl_key(legacy) == _excl_key(unified)


def test_excl_key_separates_different_exclusions():
    base = {"type": "path", "osType": "windows", "value": "C:\\a.exe"}
    assert _excl_key(base) != _excl_key(dict(base, value="C:\\b.exe"))
    assert _excl_key(base) != _excl_key(dict(base, osType="linux"))
    assert _excl_key(base) != _excl_key(dict(base, type="white_hash"))


def test_excl_key_handles_structured_values_and_junk():
    # Unified exclusions can carry a structured value; it still has to
    # produce a stable, hashable key.
    a = _excl_key({"type": "path", "value": {"b": 2, "a": 1}})
    b = _excl_key({"type": "path", "value": {"a": 1, "b": 2}})
    assert a == b and isinstance(hash(a), int)
    assert _excl_key(None) == () and _excl_key({}) == ("", "", "")


# ── _ue_rename_payload ──────────────────────────────────────────

def test_rename_payload_changes_nothing_but_the_name():
    dest = {"id": "7", "type": "path", "osType": "windows",
            "modeType": "suppression", "threatType": "EDR",
            "reason": "performance", "value": "C:\\a.exe"}
    out = _ue_rename_payload(dest, "Vendor agent", {"reason": "other"})
    assert out["exclusionName"] == "Vendor agent"
    assert out["id"] == "7" and out["reason"] == "performance"
    assert out["type"] == "path" and out["threatType"] == "EDR"


def test_rename_payload_fills_the_required_fields_the_console_nulls():
    # `reason` comes back null on most exclusions but the edit schema
    # requires it, so it falls back to the source and then to 'other'.
    dest = {"id": "7", "type": "path", "osType": "windows",
            "modeType": "suppression", "threatType": "EDR",
            "reason": None}
    assert _ue_rename_payload(dest, "n", {"reason": "performance"})[
        "reason"] == "performance"
    assert _ue_rename_payload(dest, "n")["reason"] == "other"


def test_rename_payload_refuses_an_item_it_cannot_address():
    assert _ue_rename_payload({"type": "path"}, "n") == {}
    assert _ue_rename_payload(None, "n") == {}


# ── _strip_unknown_fields ───────────────────────────────────────────
# The destination's OWN role template carries `pages`, and POST /rbac/role
# then refuses it — all three Beijer Ref custom roles died on that
# (2026-09-02).

def test_strip_unknown_fields_reads_the_dict_values_shape():
    payload = {"name": "Ranger Role", "description": "d", "pages": [1, 2]}
    err = ("Validation Error :: data: dict_values(['pages']): "
           "Unknown field (code 4000010)")
    trimmed, dropped = _strip_unknown_fields(payload, err)
    assert dropped == ["pages"]
    assert trimmed == {"name": "Ranger Role", "description": "d"}
    assert "pages" in payload          # original left intact


def test_strip_unknown_fields_reads_the_plain_shape():
    payload = {"name": "r", "widget": 1}
    trimmed, dropped = _strip_unknown_fields(
        payload, "data: widget: Unknown field")
    assert dropped == ["widget"] and trimmed == {"name": "r"}


def test_strip_unknown_fields_only_reports_fields_it_can_remove():
    # No field named, or a field that isn't in the payload: no retry.
    assert _strip_unknown_fields({"name": "r"}, "some other error") == \
        ({"name": "r"}, [])
    assert _strip_unknown_fields(
        {"name": "r"}, "data: dict_values(['pages']): Unknown field") == \
        ({"name": "r"}, [])


# ── _sched_report_payload ───────────────────────────────────────────
# All 159 of Beijer Ref's scheduled reports were rejected on 2026-09-02:
# GET /report-tasks returns `day`, `recipients` and `isTrend` as null and
# POST /report-tasks refuses them as null.

def test_sched_report_fills_the_fields_the_create_api_refuses_as_null():
    rep = {"id": "r1", "name": "Threats", "frequency": "daily",
           "day": None, "recipients": None, "isTrend": None}
    data, filled = _sched_report_payload(rep)
    assert data["recipients"] == [] and data["isTrend"] is False
    assert data["day"] == 1
    assert sorted(filled) == ["day", "isTrend", "recipients"]
    assert "id" not in data          # still cleaned of source identifiers


def test_sched_report_never_overwrites_a_real_value():
    rep = {"name": "Weekly", "day": 4, "recipients": ["a@b.com"],
           "isTrend": True}
    data, filled = _sched_report_payload(rep)
    assert filled == []
    assert (data["day"], data["recipients"], data["isTrend"]) == \
        (4, ["a@b.com"], True)


def test_sched_report_does_not_invent_a_data_window():
    # fromDate/toDate decide which period the report covers. A wrong
    # window that looks migrated is worse than a visible failure.
    assert "fromDate" not in _SCHED_REPORT_DEFAULTS
    assert "toDate" not in _SCHED_REPORT_DEFAULTS
    data, filled = _sched_report_payload({"name": "x", "fromDate": None})
    assert data["fromDate"] is None and "fromDate" not in filled


# ── _scope_inherits_config ────────────────────────────────────────────
# Writing a config the source only INHERITED onto a destination scope that
# also inherits is rejected: "Cannot change firewall settings while
# inheriting settings from parent (code 4000010)" — 141 of them in one
# Beijer Ref run (2026-09-02). The payloads below are verbatim from that
# customer's backup.

_FW_INHERITED = {"enabled": True, "inheritAllFirewallRules": True,
                 "inheritSettings": True, "inheritedFrom": None,
                 "inherits": True, "locationAware": True,
                 "selectedTags": []}
_FW_OWN = {**_FW_INHERITED, "inheritSettings": False}
_DC_INHERITED = {"enabled": False, "inheritedFrom": "global",
                 "inherits": True, "reportBlocked": True}
_DC_OWN = {"enabled": True, "inheritedFrom": None, "inherits": False,
           "reportBlocked": True}


def test_firewall_inheritance_is_read_from_inherit_settings():
    # `inherits` is true on EVERY firewall config, including the scopes
    # holding a real override — only `inheritSettings` distinguishes them.
    assert _scope_inherits_config({}, _FW_INHERITED) is True
    assert _scope_inherits_config({}, _FW_OWN) is False


def test_device_control_inheritance_is_read_from_inherits():
    # Device Control has no `inheritSettings` field at all.
    assert "inheritSettings" not in _DC_INHERITED
    assert _scope_inherits_config({}, _DC_INHERITED) is True
    assert _scope_inherits_config({}, _DC_OWN) is False


def test_group_policy_inheritance_is_not_config_inheritance():
    # group.inherits is POLICY inheritance. Treating it as config
    # inheritance skipped the firewall overrides of 4 Beijer groups.
    node = {"group": {"inherits": True}}
    assert _scope_inherits_config(node, _FW_OWN) is False
    assert _scope_inherits_config(node, _DC_OWN) is False
    # ...and it must not rescue an inheriting scope either — the config says
    # so on its own.
    assert _scope_inherits_config({"group": {"inherits": False}},
                                  _FW_INHERITED) is True


def test_scope_inherits_config_handles_missing_config():
    assert _scope_inherits_config({}, None) is False
    assert _scope_inherits_config({}, {}) is False


# ── _nq_rules_for_scope ────────────────────────────────────────────────
# Network Quarantine rules are served by the firewall-control API and are
# returned at every level, so they leak downwards exactly like firewall
# rules. Nobody hit this before 2.3.0 because the route was wrong and the
# rules were never captured at all (Landeshauptstadt Muenchen, 2026-09).

def test_nq_rules_for_scope_site_drops_inherited_account_rule():
    rules = [
        {"name": "AcctAllow", "scope": "account"},
        {"name": "SiteAllow", "scope": "site"},
    ]
    assert [r["name"] for r in _nq_rules_for_scope(rules, "site")] == \
        ["SiteAllow"]


def test_nq_rules_for_scope_global_accepts_tenant_alias():
    rules = [{"name": "g", "scope": "tenant"},
             {"name": "a", "scope": "account"}]
    assert [r["name"] for r in _nq_rules_for_scope(rules, "global")] == ["g"]


def test_nq_rules_for_scope_keeps_rules_with_no_scope_field():
    # The rule shape is unverified (the route 404'd until 2.3.0), so an
    # unlabelled rule is restored rather than silently dropped — trading one
    # silent loss for another is not a fix.
    rules = [{"name": "NoScope"}, {"name": "Acct", "scope": "account"}]
    assert [r["name"] for r in _nq_rules_for_scope(rules, "site")] == \
        ["NoScope"]


def test_nq_rules_for_scope_case_insensitive_and_empty():
    assert _nq_rules_for_scope([{"scope": "GROUP"}], "group") == \
        [{"scope": "GROUP"}]
    assert _nq_rules_for_scope(None, "site") == []


# ── _star_rules_for_scope (custom detection rule leak guard) ────────────
# /cloud-detection/rules returns inherited rules at every level, so an
# account rule is also returned under each child site. Without scope
# filtering the account rule is backed up (and re-created) under every site
# (reported by DJ Wilhelm 2026-07). STAR rules carry a `scope` field too.

def test_star_rules_for_scope_site_drops_inherited_account_rule():
    # A site query returns the site's own rule AND the inherited account rule.
    rules = [
        {"name": "BruteForce", "scope": "account"},
        {"name": "SiteOnly", "scope": "site"},
    ]
    assert [r["name"] for r in _star_rules_for_scope(rules, "site")] == \
        ["SiteOnly"]


def test_star_rules_for_scope_account_drops_descendant_site_rules():
    # An account query returns account rules AND all descendant site rules.
    rules = [
        {"name": "AcctRule", "scope": "account"},
        {"name": "SiteA", "scope": "site"},
        {"name": "SiteB", "scope": "site"},
    ]
    assert [r["name"] for r in _star_rules_for_scope(rules, "account")] == \
        ["AcctRule"]


def test_star_rules_for_scope_site_drops_inherited_global_rules():
    # ThomsonReuters: the source site CONTAINERS had 482 rules that all live at
    # GLOBAL scope. The API returns them when querying the site, and a pre-2.1.9
    # restore re-created every one of them at SITE scope on the migrated site
    # (TR-Servers). A site node must keep only its own rules.
    rules = [
        {"name": "G1", "scope": "global"},
        {"name": "G2", "scope": "global"},
        {"name": "T1", "scope": "tenant"},
        {"name": "AcctRule", "scope": "account"},
        {"name": "SiteOwn", "scope": "site"},
    ]
    assert [r["name"] for r in _star_rules_for_scope(rules, "site")] == \
        ["SiteOwn"]
    # and a site with no rules of its own migrates nothing, rather than
    # inheriting the whole tenant's ruleset
    global_only = [{"name": "G1", "scope": "global"}]
    assert _star_rules_for_scope(global_only, "site") == []


def test_star_rules_for_scope_global_accepts_tenant_alias():
    # Some consoles report the tenant level as 'global', others as 'tenant'.
    rules = [
        {"name": "g1", "scope": "global"},
        {"name": "g2", "scope": "tenant"},
        {"name": "a1", "scope": "account"},
    ]
    assert sorted(r["name"] for r in _star_rules_for_scope(rules, "global")) \
        == ["g1", "g2"]


def test_star_rules_for_scope_case_insensitive_and_empty():
    assert _star_rules_for_scope([{"name": "s", "scope": "SITE"}], "site") == \
        [{"name": "s", "scope": "SITE"}]
    assert _star_rules_for_scope(None, "site") == []
    assert _star_rules_for_scope([{"name": "x"}], "account") == []


# ── tags (Joshua Tooley 2026-08: tags backed up but never restored) ─────
# GET /tags returns inherited tags at every level, and the create endpoint
# rejects the read-only `kind` field, so the payload has to be rebuilt.

def test_tags_for_scope_site_drops_inherited_parent_tags():
    tags = [
        {"name": "GlobalTag", "scope": "global"},
        {"name": "AcctTag", "scope": "account"},
        {"name": "SiteTag", "scope": "site"},
    ]
    assert [t["name"] for t in _tags_for_scope(tags, "site")] == ["SiteTag"]


def test_tags_for_scope_global_accepts_tenant_alias():
    tags = [{"name": "g", "scope": "global"}, {"name": "t", "scope": "tenant"},
            {"name": "a", "scope": "account"}]
    assert sorted(t["name"] for t in _tags_for_scope(tags, "global")) == \
        ["g", "t"]


def test_tags_for_scope_keeps_tags_without_a_scope_field():
    # Older backups (and some consoles) omit `scope` — dropping those would
    # silently migrate nothing, which is the bug this guards against.
    tags = [{"name": "Legacy"}, {"name": "Acct", "scope": "account"}]
    assert [t["name"] for t in _tags_for_scope(tags, "site")] == ["Legacy"]


def test_tags_for_scope_empty_input():
    assert _tags_for_scope(None, "site") == []
    assert _tags_for_scope([], "account") == []


def test_tag_payload_drops_readonly_fields_and_stamps_scope():
    src = {
        "id": "1234", "name": "Servers", "description": "web tier",
        "type": "firewall", "kind": "user", "scope": "account",
        "scopeId": "999", "affectedScopes": [{"id": "1"}],
        "linkedRules": 4, "createdAt": "2026-01-01T00:00:00Z",
        "creator": "someone",
    }
    out = _tag_payload(src, "firewall", "site")
    assert out == {"name": "Servers", "description": "web tier",
                   "type": "firewall", "scope": "site"}


def test_tag_payload_forces_the_restored_tag_type():
    out = _tag_payload({"name": "Laptops"}, "device-inventory", "account")
    assert out["type"] == "device-inventory"
    assert out["scope"] == "account"


def test_tag_payload_global_scope_value():
    assert _tag_payload({"name": "x"}, "firewall", "global")["scope"] == \
        "global"


def test_tag_payload_does_not_mutate_source():
    src = {"name": "x", "kind": "user", "scope": "account"}
    _tag_payload(src, "firewall", "site")
    assert src == {"name": "x", "kind": "user", "scope": "account"}


# ── _endpoint_tag_payload ───────────────────────────────────────────────
# Verbatim from GET /agents/tags. POST /tag-manager requires `type`, `key`
# and `value` together and validates the type, so a payload that guesses it
# is refused for every tag on every scope (beijerrefab, 2026-08-21).

def _console_endpoint_tag(**over):
    tag = {
        "allowEdit": True,
        "createdAt": "2024-11-25T18:17:44.062145Z",
        "createdBy": "SentinelOne",
        "description": "",
        "endpointsInCurrentScope": 0,
        "id": "2091530492334218617",
        "key": "ripple20",
        "scopeId": "1655835019966207609",
        "scopeLevel": "account",
        "scopePath": "Global\\FIRST QUANTUM MINERALS (UK) LTD",
        "totalEndpoints": 0,
        "type": "agents",
        "updatedAt": "2024-11-25T18:17:44.062151Z",
        "updatedBy": "SentinelOne",
        "value": "",
    }
    tag.update(over)
    return tag


def test_endpoint_tag_payload_sends_only_the_four_writable_fields():
    assert _endpoint_tag_payload(_console_endpoint_tag()) == {
        "type": "agents", "key": "ripple20", "value": "", "description": ""}


def test_endpoint_tag_payload_keeps_the_consoles_own_type():
    out = _endpoint_tag_payload(_console_endpoint_tag(key="Department",
                                                      value="Finance"))
    assert out["type"] == "agents"


def test_endpoint_tag_payload_never_guesses_the_type():
    # The 100%-failure bug: "endpoints" is rejected by the create schema.
    for tag in (_console_endpoint_tag(), {"key": "OnlyKey"}, {}):
        assert _endpoint_tag_payload(tag)["type"] == "agents"


def test_endpoint_tag_payload_defaults_a_missing_type():
    assert _endpoint_tag_payload({"key": "K", "value": "V"}) == {
        "type": "agents", "key": "K", "value": "V"}


def test_endpoint_tag_payload_always_sends_value():
    # `value` is required, so a key-only tag needs the empty string the
    # console itself stores — omitting the field is a validation error.
    assert _endpoint_tag_payload({"key": "OnlyKey"}) == {
        "type": "agents", "key": "OnlyKey", "value": ""}
    assert _endpoint_tag_payload({"key": "K", "value": None})["value"] == ""


def test_endpoint_tag_payload_keeps_a_literal_no_value():
    # "No Value" is a real stored string on these consoles, not a placeholder.
    assert _endpoint_tag_payload(
        _console_endpoint_tag(value="No Value"))["value"] == "No Value"


def test_endpoint_tag_payload_does_not_mutate_source():
    src = _console_endpoint_tag()
    before = dict(src)
    _endpoint_tag_payload(src)
    assert src == before


# ── _endpoint_tags_for_scope ────────────────────────────────────────────
# Endpoint tags carry their level in `scopeLevel`, not `scope`.

def test_endpoint_tags_for_scope_keeps_only_this_levels_tags():
    tags = [_console_endpoint_tag(key="acct", scopeLevel="account"),
            _console_endpoint_tag(key="site", scopeLevel="site"),
            _console_endpoint_tag(key="glob", scopeLevel="global")]
    assert [t["key"] for t in _endpoint_tags_for_scope(tags, "account")] == \
        ["acct"]
    assert [t["key"] for t in _endpoint_tags_for_scope(tags, "site")] == \
        ["site"]


def test_endpoint_tags_for_scope_treats_tenant_as_global():
    tags = [_console_endpoint_tag(key="a", scopeLevel="tenant"),
            _console_endpoint_tag(key="b", scopeLevel="global")]
    assert len(_endpoint_tags_for_scope(tags, "global")) == 2


def test_endpoint_tags_for_scope_keeps_tags_with_no_level():
    # Older backups have no scopeLevel; dropping them would migrate nothing.
    tags = [{"key": "K", "value": "V"}]
    assert _endpoint_tags_for_scope(tags, "site") == tags


# ── _overrides_for_scope ──────────────────────────────────────

def test_overrides_for_scope_drops_other_scopes():
    ovr = [{"name": "acct", "scope": "account"},
           {"name": "grp", "scope": "group"},
           {"name": "st", "scope": "site"}]
    assert [o["name"] for o in _overrides_for_scope(ovr, "account")] == ["acct"]
    assert [o["name"] for o in _overrides_for_scope(ovr, "group")] == ["grp"]
    assert [o["name"] for o in _overrides_for_scope(ovr, "site")] == ["st"]


def test_overrides_for_scope_global_accepts_tenant_alias():
    ovr = [{"name": "g1", "scope": "global"},
           {"name": "g2", "scope": "tenant"},
           {"name": "s", "scope": "site"}]
    assert sorted(o["name"] for o in _overrides_for_scope(ovr, "global")) == \
        ["g1", "g2"]


def test_overrides_for_scope_keeps_overrides_with_no_scope_field():
    ovr = [{"name": "Legacy"}]
    assert _overrides_for_scope(ovr, "site") == ovr


def test_overrides_for_scope_empty_input():
    assert _overrides_for_scope(None, "site") == []
    assert _overrides_for_scope([], "account") == []


def test_overrides_for_scope_account_query_owns_none_of_its_descendants():
    """Real shape from the Beijer Ref backup: querying /config-override at the
    account returned 14 group-scoped and 3 site-scoped overrides and zero
    account-scoped ones. Unfiltered, all 17 were re-created at the account."""
    account_query_result = (
        [{"name": f"g{i}", "scope": "group"} for i in range(14)]
        + [{"name": f"s{i}", "scope": "site"} for i in range(3)]
    )
    assert _overrides_for_scope(account_query_result, "account") == []


# ── _override_payload ────────────────────────────────────────

def test_override_payload_keeps_the_overrides_own_scope():
    ovr = {"name": "VSSConfig BNK", "scope": "group",
           "config": {"vssConfig": {}}}
    # Restoring the ACCOUNT node must not turn a group override into an
    # account one.
    assert _override_payload(ovr, "account")["scope"] == "group"


def test_override_payload_drops_source_console_scope_objects():
    ovr = {"name": "n", "scope": "group",
           "account": {"id": "A1", "name": "Src"},
           "site": {"id": "S1", "name": "SrcSite"},
           "group": {"id": "G1", "name": "SrcGroup"}}
    body = _override_payload(ovr, "group")
    assert "account" not in body
    assert "site" not in body
    assert "group" not in body
    assert body["name"] == "n"


def test_override_payload_strips_read_only_fields():
    ovr = {"name": "n", "scope": "site", "id": "9",
           "createdAt": "t", "updatedAt": "t"}
    body = _override_payload(ovr, "site")
    assert "id" not in body
    assert "createdAt" not in body
    assert "updatedAt" not in body


def test_override_payload_maps_tenant_to_global():
    body = _override_payload({"name": "n", "scope": "tenant"}, "global")
    assert body["scope"] == "global"


def test_override_payload_falls_back_to_the_node_type():
    # Old backups omit `scope`; the destination still requires data.scope.
    assert _override_payload({"name": "n"}, "site")["scope"] == "site"


def test_override_payload_does_not_mutate_input():
    ovr = {"name": "n", "scope": "group", "group": {"id": "G1"}}
    _override_payload(ovr, "account")
    assert ovr == {"name": "n", "scope": "group", "group": {"id": "G1"}}


def test_override_payload_binds_the_destination_site():
    # POST /config-override carries no scope filter: the destination site
    # has to be named inside the body, or the override binds to nothing.
    ovr = {"name": "n", "scope": "site", "site": {"id": "SRC", "name": "s"}}
    body = _override_payload(ovr, "site", "DEST-SITE")
    assert body["scope"] == "site"
    assert body["site"] == {"id": "DEST-SITE"}


def test_override_payload_binds_the_destination_group():
    ovr = {"name": "n", "scope": "group", "group": {"id": "SRC", "name": "g"}}
    body = _override_payload(ovr, "group", "DEST-GROUP")
    assert body["group"] == {"id": "DEST-GROUP"}
    assert "site" not in body and "account" not in body


def test_override_payload_stringifies_a_numeric_destination_id():
    body = _override_payload({"name": "n", "scope": "site"}, "site", 12345)
    assert body["site"] == {"id": "12345"}


def test_override_payload_never_binds_another_scopes_id():
    # A group override handed to the account node keeps its own scope and
    # must NOT be stamped with the account's id.
    body = _override_payload({"name": "n", "scope": "group"},
                             "account", "DEST-ACCOUNT")
    assert body["scope"] == "group"
    assert "group" not in body and "account" not in body


def test_override_payload_leaves_global_unbound():
    body = _override_payload({"name": "n", "scope": "tenant"}, "global", "")
    assert body["scope"] == "global"
    assert not any(k in body for k in ("account", "site", "group"))


def test_endpoint_tags_for_scope_handles_empty():
    assert _endpoint_tags_for_scope(None, "site") == []


# ── _scope ──────────────────────────────────────────────────────────────

def test_scope_global():
    assert _scope("global", "") == {"tenant": "true"}


def test_scope_account_site_group_use_id_arrays():
    assert _scope("account", "A1") == {"accountIds": ["A1"]}
    assert _scope("site", "S1") == {"siteIds": ["S1"]}
    assert _scope("group", "G1") == {"groupIds": ["G1"]}


def test_scope_unknown_returns_empty():
    assert _scope("nonsense", "x") == {}


# ── _clean_for_restore ──────────────────────────────────────────────────

def test_clean_strips_source_identifiers():
    obj = {"id": "abc", "name": "Policy", "createdAt": "2020", "scope": "x"}
    cleaned = _clean_for_restore(obj)
    assert "id" not in cleaned
    assert "createdAt" not in cleaned
    assert "scope" not in cleaned
    assert cleaned["name"] == "Policy"


def test_clean_keeps_payload_fields():
    obj = {"agentInterval": 5, "name": "X"}
    assert _clean_for_restore(obj) == {"agentInterval": 5, "name": "X"}


# ── saved filters: scopeLevel must be dropped on restore ────────────────

def test_clean_drops_saved_filter_scope_level():
    # ThomsonReuters / TR-Containers: GET /filters returns the filter's own
    # scope as `scopeLevel`. Saved filters are created with the DESTINATION
    # scope in the request's `filter` envelope, so sending the source
    # scopeLevel in `data` contradicts it and S1 rejects the create. Every
    # migrated site then had no filters, so each dynamic group was created
    # STATIC and Group Ranking came up empty.
    flt = {
        "id": "1338570161695321319",
        "name": "Agents older than 22.x.x",
        "filterFields": {"agentVersions": ["21.7.4.1043"]},
        "scopeLevel": "account",
        "scopeId": "647137276083260819",
        "siteId": None,
        "createdAt": "2022-01-21T20:59:57.988928Z",
    }
    cleaned = _clean_for_restore(flt)
    # the scope is carried by the request envelope, never by the payload
    for stale in ("scopeLevel", "scopeId", "siteId", "id", "createdAt"):
        assert stale not in cleaned, f"{stale} must not be sent on create"
    # ...but the parts that define the filter must survive
    assert cleaned == {
        "name": "Agents older than 22.x.x",
        "filterFields": {"agentVersions": ["21.7.4.1043"]},
    }


# ── STAR rule: activeResponse must be dropped on restore ────────────────
# The /cloud-detection/rules GET returns `activeResponse` but the create
# endpoint rejects it: "data: dict_values(['activeResponse']): Unknown
# field (code 4000010)". _clean_for_restore (used by the STAR create path)
# must strip it.

def test_clean_drops_star_active_response():
    rule = {"name": "hunt", "s1ql": "x", "activeResponse": True}
    cleaned = _clean_for_restore(rule)
    assert "activeResponse" not in cleaned
    assert cleaned["name"] == "hunt"
    assert cleaned["s1ql"] == "x"


# ── policy: forensicsAutoTriggering must be droppable on restore ─────────
# The forensics auto-trigger block references RemoteOps forensic-script
# profiles by ID; those profiles don't exist on the destination, so S1
# rejects the policy with "Bad auto-triggering policy information provided
# (code 4000010)". _drop_forensics_triggering removes the block for retry.

def test_drop_forensics_triggering_removes_block():
    policy = {
        "agentUiOn": True,
        "forensicsAutoTriggering": {
            "windowsEnabled": True,
            "windowsProfileId": "src-only-id",
        },
    }
    stripped = _drop_forensics_triggering(policy)
    assert "forensicsAutoTriggering" not in stripped
    assert stripped["agentUiOn"] is True


def test_drop_forensics_triggering_is_noop_when_absent():
    policy = {"agentUiOn": True, "mitigationMode": "protect"}
    assert _drop_forensics_triggering(policy) == policy


def test_drop_forensics_triggering_does_not_mutate_input():
    policy = {"forensicsAutoTriggering": {"windowsEnabled": True}}
    _drop_forensics_triggering(policy)
    assert "forensicsAutoTriggering" in policy


def _dest_template():
    """A destination create-ready role template (as GET /rbac/role returns).

    Everything defaults to not-allowed; a create call fills these in. Note the
    permission field is NOT `pages` (that name is only in the GET-role detail
    and is rejected by the create schema)."""
    return {
        "name": None,
        "description": None,
        "roles": [
            {"name": "Endpoints", "actions": [
                {"name": "View", "isEnabled": False},
                {"name": "Uninstall", "isEnabled": False},
            ]},
            {"name": "Policy", "actions": [
                {"name": "View", "isEnabled": False},
                {"name": "Edit", "isEnabled": False},
            ]},
        ],
    }


def _source_role():
    """A source custom role as stored in a backup (GET /rbac/role/{id})."""
    return {
        "id": "src-role-id",
        "name": "DJW-Viewer",
        "description": "Read-only",
        "scope": "account",
        "predefinedRole": False,
        "accountIds": ["SRC"],
        "createdAt": "2024-01-01",
        "usersInRole": 7,
        "pages": [
            {"name": "Endpoints", "actions": [
                {"name": "View", "isEnabled": True},
                {"name": "Uninstall", "isEnabled": False},
            ]},
            # A permission the destination doesn't expose — must be ignored.
            {"name": "Ranger", "actions": [
                {"name": "View", "isEnabled": True}]},
        ],
    }


def test_build_role_payload_drops_read_only_and_scope_fields():
    out = _build_role_payload(_source_role(), _dest_template())
    # The exact fields S1 rejected in the bug report must be gone from `data`.
    for k in ("id", "scope", "predefinedRole", "accountIds", "pages",
              "createdAt", "usersInRole"):
        assert k not in out


def test_build_role_payload_keeps_name_and_description():
    out = _build_role_payload(_source_role(), _dest_template())
    assert out["name"] == "DJW-Viewer"
    assert out["description"] == "Read-only"


def test_build_role_payload_overlays_granted_permissions_onto_template():
    out = _build_role_payload(_source_role(), _dest_template())
    groups = {g["name"]: g for g in out["roles"]}
    ep = {a["name"]: a["isEnabled"] for a in groups["Endpoints"]["actions"]}
    assert ep == {"View": True, "Uninstall": False}
    # Untouched destination group stays at its template default.
    pol = {a["name"]: a["isEnabled"] for a in groups["Policy"]["actions"]}
    assert pol == {"View": False, "Edit": False}


def test_build_role_payload_ignores_permissions_absent_from_template():
    out = _build_role_payload(_source_role(), _dest_template())
    # "Ranger" is only in the source, never in the dest template → not added.
    assert all(g["name"] != "Ranger" for g in out["roles"])


def test_build_role_payload_does_not_mutate_inputs():
    role = _source_role()
    tmpl = _dest_template()
    _build_role_payload(role, tmpl)
    assert role["accountIds"] == ["SRC"] and role["id"] == "src-role-id"
    # Template default must be untouched (deepcopy was used).
    assert tmpl["roles"][0]["actions"][0]["isEnabled"] is False


def test_build_role_payload_fallback_without_template():
    out = _build_role_payload(_source_role(), None)
    assert out == {"name": "DJW-Viewer", "description": "Read-only"}


def test_role_scope_filter_prefers_site_then_account():
    assert _role_scope_filter("A1") == {"accountIds": ["A1"]}
    assert _role_scope_filter("A1", "S1") == {"siteIds": ["S1"]}
    assert _role_scope_filter("") == {}


def test_overlay_handles_alternate_bool_key_name():
    # GET role uses isEnabled; a template variant might use isAllowed.
    tmpl = {"roles": [{"name": "Endpoints", "actions": [
        {"name": "View", "isAllowed": False}]}]}
    role = {"pages": [{"name": "Endpoints", "actions": [
        {"name": "View", "isEnabled": True}]}]}
    _overlay_role_permissions(tmpl, role)
    assert tmpl["roles"][0]["actions"][0]["isAllowed"] is True


# ── explain_error ───────────────────────────────────────────────────────

def test_explain_error_returns_full_shape():
    out = explain_error("policy", "something went wrong", 500)
    for key in ("label", "what", "why", "fix", "severity", "raw"):
        assert key in out
    assert out["label"] == "policy"
    assert "policy" in out["raw"] and "500" in out["raw"]


_SERVER_5XX = ("Internal server error :: Server could not process the "
               "request. (code 5000010)")


def test_endpoint_tag_5xx_points_at_the_diagnostic_that_settles_it():
    # 150 of 150 endpoint tags died on this one error with no guidance
    # (Beijer Ref, 2026-09-02).
    out = explain_error("ep-tags", _SERVER_5XX, 500)
    assert "endpoint tag" in out["what"].lower()
    assert "Diagnose endpoint tags" in out["fix"]


def test_override_5xx_is_not_swallowed_by_the_generic_5xx_rule():
    out = explain_error("overrides", _SERVER_5XX, 500)
    assert "config override" in out["what"].lower()


def test_override_scope_filter_rejection_is_explained_for_every_key():
    # LHM 2026-08-24: siteIds at each site, groupIds at each group.
    for key in ("accountIds", "siteIds", "groupIds"):
        detail = (f"Validation Error :: filter: {key}: Unknown field. "
                  f"(code 4000010)")
        out = explain_error("overrides", detail, 400)
        assert "config override" in out["what"].lower()
        assert "no scope filter" in out["why"].lower()


def test_group_scope_filter_rejection_elsewhere_still_reads_as_inheritance():
    # The same console message for Locations means something else: that
    # element simply doesn't exist at group scope.
    detail = "Validation Error :: filter: groupIds: Unknown field."
    out = explain_error("locations", detail, 400)
    assert "group scope" in out["what"].lower()


def test_other_elements_still_get_the_generic_5xx_explanation():
    out = explain_error("policy", _SERVER_5XX, 500)
    assert "server error" in out["what"].lower()


def test_scheduled_report_without_a_data_window_is_explained():
    detail = ("Validation Error :: data: fromDate: Field may not be null., "
              "toDate: Field may not be null. (code 4000010)")
    out = explain_error("sched-rep", detail, 400)
    assert "data window" in out["what"].lower()


def test_explain_error_unknown_falls_back_gracefully():
    out = explain_error("widget", "an utterly novel failure xyzzy", 0)
    assert "Unrecognised error" in out["what"]
    assert out["severity"] == "error"


# ── _is_exists_error (extracted module-level helper) ────────────────────

class _Err(Exception):
    def __init__(self, msg, status_code=0, detail=""):
        super().__init__(msg)
        self.status_code = status_code
        self.detail = detail


def test_is_exists_error_detects_duplicate():
    assert _is_exists_error(_Err("POST /x → 409", 409, "Item already exists"))


def test_is_exists_error_detects_inheritance_block():
    assert _is_exists_error(
        _Err("POST /x → 403", 403, "scope is decoupled from parent"))


def test_is_exists_error_false_for_real_failure():
    assert not _is_exists_error(_Err("POST /x → 500", 500, "internal error"))


def test_is_exists_error_false_for_plain_400():
    assert not _is_exists_error(_Err("POST /x → 400", 400, "validation failed"))
