"""Tests for the duplicate STAR rule cleanup script's matching logic.

`scripts/cleanup_duplicate_star_rules.py` performs a DESTRUCTIVE bulk delete
against a live console, so its selection logic is pinned here. It must:
  * only ever select SITE-scoped rules,
  * only select them when they genuinely duplicate an account- or tenant-scoped
    rule (so the "original" is always kept),
  * never conflate two different accounts that reuse a rule name.
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

_spec = importlib.util.spec_from_file_location(
    "cleanup_duplicate_star_rules",
    os.path.join(ROOT, "scripts", "cleanup_duplicate_star_rules.py"))
cleanup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cleanup)

find_extras = cleanup.find_extras


def _rule(rid, name, scope, account="A1", site=None,
          desc="d", s1ql="q"):
    return {"id": rid, "name": name, "scope": scope,
            "accountId": account, "siteId": site, "siteName": site,
            "description": desc, "s1ql": s1ql}


def _ids(rules):
    return sorted(r["id"] for r in rules)


# ── the reported scenario ───────────────────────────────────────────────

def test_account_rule_copied_to_every_site_selects_only_the_site_copies():
    rules = [
        _rule("1", "BruteForce", "account"),
        _rule("2", "BruteForce", "site", site="Default site"),
        _rule("3", "BruteForce", "site", site="TestSite"),
    ]
    assert _ids(find_extras(rules)) == ["2", "3"]


def test_never_selects_the_account_or_tenant_original():
    rules = [
        _rule("1", "BruteForce", "account"),
        _rule("2", "BruteForce", "site", site="S"),
    ]
    picked = find_extras(rules)
    assert all(r["scope"] == "site" for r in picked)


# ── safety: genuine site rules must survive ─────────────────────────────

def test_site_only_rule_with_no_parent_is_kept():
    rules = [
        _rule("1", "AcctRule", "account"),
        _rule("2", "SiteOnlyRule", "site", site="S"),
    ]
    assert find_extras(rules) == []


def test_same_name_in_a_different_account_is_not_cross_matched():
    rules = [
        _rule("1", "Shared", "account", account="A1"),
        _rule("2", "Shared", "site", account="A2", site="S"),
    ]
    assert find_extras(rules) == []


def test_differing_description_or_query_is_kept_by_default():
    rules = [
        _rule("1", "Rule", "account", desc="original"),
        _rule("2", "Rule", "site", site="S", desc="edited on purpose"),
    ]
    assert find_extras(rules) == []
    # ...but --match-name-only is deliberately looser
    assert _ids(find_extras(rules, name_only=True)) == ["2"]


# ── tenant/global parents (rules carry no accountId of their own) ───────

def test_tenant_scoped_parent_matches_site_copies_in_any_account():
    rules = [
        _rule("1", "GlobalRule", "global", account=None),
        _rule("2", "GlobalRule", "site", account="A1", site="S1"),
        _rule("3", "GlobalRule", "site", account="A2", site="S2"),
    ]
    assert _ids(find_extras(rules)) == ["2", "3"]


def test_tenant_alias_scope_is_recognised():
    rules = [
        _rule("1", "R", "tenant", account=None),
        _rule("2", "R", "site", site="S"),
    ]
    assert _ids(find_extras(rules)) == ["2"]


def test_empty_and_no_duplicates():
    assert find_extras([]) == []
    assert find_extras([_rule("1", "A", "account")]) == []


# ── site targeting / all-site-scoped mode (the TR-Servers cleanup) ──────

filter_to_site = cleanup.filter_to_site
find_site_scoped = cleanup.find_site_scoped


def test_filter_to_site_matches_by_name_case_insensitively():
    rules = [
        _rule("1", "A", "site", site="TR-Servers"),
        _rule("2", "B", "site", site="TR-Containers"),
        _rule("3", "C", "global", account=None),
    ]
    assert _ids(filter_to_site(rules, site_name="tr-servers")) == ["1"]
    # must not partial-match a similarly named site
    assert _ids(filter_to_site(rules, site_name="TR-Containers")) == ["2"]


def test_filter_to_site_matches_by_id():
    rules = [
        {"id": "1", "siteId": "S100", "siteName": "TR-Servers",
         "scope": "site"},
        {"id": "2", "siteId": "S200", "siteName": "Other", "scope": "site"},
    ]
    assert _ids(filter_to_site(rules, site_id="S100")) == ["1"]


def test_all_site_scoped_selects_every_site_rule_even_without_a_parent():
    # TR-Servers: 960 site-scoped copies of the tenant's GLOBAL rules. The
    # global originals may not match by signature, so duplicate-matching is
    # not enough -- this mode takes every site-scoped rule at the site.
    rules = [
        _rule("1", "G1", "site", site="TR-Servers"),
        _rule("2", "G2", "site", site="TR-Servers"),
        _rule("3", "G1", "global", account=None),
    ]
    targeted = filter_to_site(rules, site_name="TR-Servers")
    assert _ids(find_site_scoped(targeted)) == ["1", "2"]
    # the global original is never in the target set
    assert all(r["scope"] == "site" for r in find_site_scoped(targeted))
