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
    explain_error,
    _is_exists_error,
    _FW_RULE_FIELDS,
    _rules_for_scope,
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


def test_build_role_payload_keeps_name_desc_permissions():
    role = {
        "id": "src-role-id",
        "name": "IR Analyst",
        "description": "Incident response",
        "permissions": [{"id": "threats.view", "isAllowed": True}],
        "createdAt": "2024-01-01",
        "usersInRole": 7,
        "predefined": False,
    }
    out = _build_role_payload(role, "dest-acct-1")
    assert out["name"] == "IR Analyst"
    assert out["description"] == "Incident response"
    assert out["permissions"] == [{"id": "threats.view", "isAllowed": True}]
    for k in ("id", "createdAt", "usersInRole", "predefined"):
        assert k not in out


def test_build_role_payload_binds_destination_account():
    out = _build_role_payload({"name": "X", "accountIds": ["SRC"]}, "DEST")
    assert out["accountIds"] == ["DEST"]


def test_build_role_payload_keeps_scope_type_string_drops_scope_object():
    kept = _build_role_payload({"name": "X", "scope": "account"}, "D")
    assert kept["scope"] == "account"
    dropped = _build_role_payload(
        {"name": "X", "scope": {"id": "src", "name": "Acct"}}, "D")
    assert "scope" not in dropped


def test_build_role_payload_no_account_leaves_accountids_absent():
    out = _build_role_payload({"name": "X"}, "")
    assert "accountIds" not in out


def test_build_role_payload_does_not_mutate_input():
    role = {"name": "X", "id": "keep", "accountIds": ["SRC"]}
    _build_role_payload(role, "DEST")
    assert role["id"] == "keep" and role["accountIds"] == ["SRC"]


# ── explain_error ───────────────────────────────────────────────────────

def test_explain_error_returns_full_shape():
    out = explain_error("policy", "something went wrong", 500)
    for key in ("label", "what", "why", "fix", "severity", "raw"):
        assert key in out
    assert out["label"] == "policy"
    assert "policy" in out["raw"] and "500" in out["raw"]


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
