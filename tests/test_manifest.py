"""Unit tests for the migration manifest builders in export_utils.py.

These turn a Migration Validation result set into the structured manifest and
the PSO ticket comment that feeds the 'done with PSO-XXX' closing workflow, so
their output shape is worth locking down.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from export_utils import build_migration_manifest, manifest_to_pso_comment


_META = {
    "src_url": "https://src.sentinelone.net",
    "dst_url": "https://dst.sentinelone.net",
    "when": "2026-06-29T10:11:12+00:00",
    "levels": ["account", "site"],
    "src_filters": {"account": "Acme", "site": "HQ"},
    "dst_filters": {"account": "Acme-New", "site": "HQ"},
}


def _clean_results():
    return [
        {"type": "account", "path": "Acme", "matched": True, "diffs": 0,
         "rows": [{"cat": "policy", "src": 1, "dst": 1, "status": "match"}]},
        {"type": "site", "path": "Acme/HQ", "matched": True, "diffs": 0,
         "rows": []},
    ]


def _dirty_results():
    return [
        {"type": "account", "path": "Acme", "matched": True, "diffs": 1,
         "rows": [
             {"cat": "star_rules", "src": 5, "dst": 3, "status": "diff",
              "missing": ["RuleA", "RuleB"], "extra": []},
             {"cat": "policy", "src": 1, "dst": 1, "status": "match"},
         ]},
        {"type": "site", "path": "Acme/Branch", "matched": False,
         "diffs": 0, "rows": []},
    ]


# ── build_migration_manifest ────────────────────────────────────────────

def test_manifest_verified_summary():
    m = build_migration_manifest(_META, _clean_results())
    s = m["summary"]
    assert s["nodesCompared"] == 2
    assert s["identical"] == 2
    assert s["withDifferences"] == 0
    assert s["missingOnDestination"] == 0
    assert s["status"] == "verified"
    assert m["source"] == "https://src.sentinelone.net"
    assert m["destination"] == "https://dst.sentinelone.net"


def test_manifest_counts_diffs_and_missing():
    m = build_migration_manifest(_META, _dirty_results())
    s = m["summary"]
    assert s["nodesCompared"] == 2
    assert s["withDifferences"] == 1
    assert s["missingOnDestination"] == 1
    assert s["identical"] == 0
    assert s["totalDifferences"] == 1
    assert s["status"] == "differences"
    # the diff node carries the per-element detail
    acct = next(n for n in m["nodes"] if n["path"] == "Acme")
    assert acct["result"] == "differences"
    assert acct["differences"][0]["element"] == "star_rules"
    assert acct["differences"][0]["missing"] == ["RuleA", "RuleB"]
    branch = next(n for n in m["nodes"] if n["path"] == "Acme/Branch")
    assert branch["result"] == "missing"


def test_manifest_empty_is_incomplete():
    m = build_migration_manifest(_META, [])
    assert m["summary"]["status"] == "incomplete"
    assert m["summary"]["nodesCompared"] == 0


# ── manifest_to_pso_comment ─────────────────────────────────────────────

def test_pso_comment_verified():
    c = manifest_to_pso_comment(build_migration_manifest(_META, _clean_results()))
    assert "completed successfully" in c
    assert "**Source:** https://src.sentinelone.net" in c
    assert "**Completed:** 2026-06-29" in c
    assert "verified" in c.lower()
    # nothing to flag → no attention section
    assert "Items needing attention" not in c


def test_pso_comment_flags_differences():
    c = manifest_to_pso_comment(build_migration_manifest(_META, _dirty_results()))
    assert "review needed" in c
    assert "Items needing attention" in c
    assert "RuleA" in c
    assert "Acme/Branch" in c  # missing scope is called out
