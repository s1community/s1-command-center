"""Tests for the pure migration helpers in migtools.py."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migtools import (
    AuditLog, evaluate_preflight, preflight_verdict, reconcile_agents,
    diff_config_fields, select_backups_to_prune, check_backup_integrity,
)


# ── Backup retention ─────────────────────────────────────────────────────

def test_prune_keeps_newest_n():
    entries = [(f"b{i}.json", 1000 + i) for i in range(10)]  # b9 newest
    prune = select_backups_to_prune(entries, keep_last=3)
    assert set(prune) == {f"b{i}.json" for i in range(7)}  # 7 oldest pruned
    assert "b9.json" not in prune and "b7.json" not in prune


def test_prune_respects_keep_days():
    now = 1_000_000
    day = 86400
    entries = [("recent.json", now - day), ("old.json", now - 30 * day)]
    # keep_last=0 but keep_days=7 → recent kept, old pruned
    prune = select_backups_to_prune(entries, keep_last=0, keep_days=7,
                                    now_ts=now)
    assert prune == ["old.json"]


def test_prune_nothing_when_under_limit():
    entries = [("a.json", 1), ("b.json", 2)]
    assert select_backups_to_prune(entries, keep_last=20) == []


# ── Backup integrity ─────────────────────────────────────────────────────

def test_integrity_good_backup():
    nodes = [{"type": "account", "path": "Acme", "data": {"policy": {}},
              "backupMetadata": {"url": "x"}}]
    r = check_backup_integrity(nodes)
    assert r["ok"] and r["errors"] == []
    assert r["node_count"] == 1 and r["element_nodes"] == 1


def test_integrity_not_a_list_is_fatal():
    r = check_backup_integrity({"oops": 1})
    assert r["ok"] is False and r["errors"]


def test_integrity_warns_missing_data_and_meta():
    nodes = [{"type": "site", "path": "Acme/HQ"}]  # no data, no metadata
    r = check_backup_integrity(nodes)
    assert r["ok"] is True  # warnings, not errors
    assert any("data" in w for w in r["warnings"])
    assert any("backupMetadata" in w for w in r["warnings"])


def test_integrity_bad_node_is_error():
    r = check_backup_integrity([{"type": "account", "data": {}}, "not-a-dict"])
    assert r["ok"] is False
    assert any("not an object" in e for e in r["errors"])


# ── AuditLog ─────────────────────────────────────────────────────────────

def test_audit_append_and_recent(tmp_path):
    log = AuditLog(str(tmp_path / "audit.jsonl"))
    log.record("backup", when="2026-06-30T10:00:00", nodes=3, console="src")
    log.record("restore", when="2026-06-30T11:00:00", nodes=3, console="dst")
    recent = log.recent()
    assert [e["action"] for e in recent] == ["restore", "backup"]  # newest first
    assert recent[0]["nodes"] == 3
    assert recent[1]["console"] == "src"


def test_audit_recent_limit_and_bad_lines(tmp_path):
    p = tmp_path / "audit.jsonl"
    log = AuditLog(str(p))
    for i in range(5):
        log.record("x", when=f"2026-06-30T10:0{i}:00", i=i)
    with open(p, "a") as f:
        f.write("not json\n")  # must be skipped, not crash
    assert len(log.recent(limit=3)) == 3
    assert len(log.recent(limit=99)) == 5


def test_audit_missing_file_is_empty(tmp_path):
    assert AuditLog(str(tmp_path / "nope.jsonl")).recent() == []


# ── Pre-flight ───────────────────────────────────────────────────────────

def test_preflight_token_expiry_states():
    base = {"now": "2026-06-30T00:00:00+00:00"}
    expired = evaluate_preflight({**base, "token_expires": "2026-06-01T00:00:00+00:00"})
    assert preflight_verdict(expired) == "fail"
    soon = evaluate_preflight({**base, "token_expires": "2026-07-05T00:00:00+00:00"})
    assert preflight_verdict(soon) == "warn"
    ok = evaluate_preflight({**base, "token_expires": "2026-12-31T00:00:00+00:00"})
    assert preflight_verdict(ok) == "pass"


def test_preflight_scope_too_narrow_fails():
    checks = evaluate_preflight({"token_scope": "site", "target_type": "account"})
    assert any(c.status == "fail" and "scope" in c.name.lower() for c in checks)


def test_preflight_scope_adequate_passes():
    checks = evaluate_preflight({"token_scope": "account", "target_type": "site"})
    assert any(c.status == "pass" and "scope" in c.name.lower() for c in checks)


def test_preflight_license_shortfall_fails():
    checks = evaluate_preflight(
        {"licenses_total": 100, "licenses_used": 98, "agents_to_move": 10})
    assert any(c.status == "fail" and "license" in c.name.lower() for c in checks)


def test_preflight_unreachable_dest_fails():
    checks = evaluate_preflight({"src_reachable": True, "dst_reachable": False})
    assert preflight_verdict(checks) == "fail"


def test_preflight_missing_scope_is_warn_not_fail():
    checks = evaluate_preflight({"dest_scope_exists": False})
    assert preflight_verdict(checks) == "warn"


# ── Agent reconciliation ─────────────────────────────────────────────────

def test_reconcile_clean_move():
    r = reconcile_agents(expected_moved=10, src_before=50, src_after=40,
                         dst_before=5, dst_after=15)
    assert r["reconciled"] is True and r["issues"] == []
    assert r["source_drop"] == 10 and r["dest_gain"] == 10


def test_reconcile_stragglers_on_source():
    r = reconcile_agents(expected_moved=10, src_before=50, src_after=45,
                         dst_before=5, dst_after=10)
    assert r["reconciled"] is False
    assert any("source" in i for i in r["issues"])


def test_reconcile_not_yet_on_dest():
    r = reconcile_agents(expected_moved=10, src_before=50, src_after=40,
                         dst_before=5, dst_after=8)
    assert r["reconciled"] is False
    assert any("destination" in i for i in r["issues"])


# ── Field-level diff ─────────────────────────────────────────────────────

def test_diff_detects_value_change():
    d = diff_config_fields({"mode": "protect", "engines": {"ml": True}},
                           {"mode": "detect", "engines": {"ml": True}})
    assert d == [{"field": "mode", "src": "protect", "dst": "detect"}]


def test_diff_ignores_volatile_keys():
    d = diff_config_fields(
        {"id": "A1", "createdAt": "x", "scopeId": "s1", "host": "a"},
        {"id": "B9", "createdAt": "y", "scopeId": "s2", "host": "a"})
    assert d == []  # only volatile keys differ


def test_diff_nested_and_lists():
    d = diff_config_fields(
        {"smtp": {"host": "a", "port": 25}, "recipients": ["x", "y"]},
        {"smtp": {"host": "a", "port": 587}, "recipients": ["y", "x"]})
    # port differs; recipients same set (order-insensitive)
    assert {"field": "smtp.port", "src": 25, "dst": 587} in d
    assert all(x["field"] != "recipients" for x in d)
