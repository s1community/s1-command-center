"""Tag audit core — the logic behind the Tags page.

These cover the three explanations the audit has to tell apart: tags present
at the right scope, tags present at the wrong scope, and tags never stored.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tag_audit  # noqa: E402
from s1_api import S1APIError  # noqa: E402


class FakeAPI:
    """Minimal stand-in for S1API: canned reads, recorded writes."""

    def __init__(self, tags=None, endpoint_tags=None, accounts=None,
                 sites=None, groups=None, errors=None,
                 endpoint_route="/agents/tags"):
        self.tags = tags or []
        self.endpoint_tags = list(endpoint_tags or [])
        # Which route this console lists unified endpoint tags on.
        self.endpoint_route = endpoint_route
        self.accounts = accounts or []
        self.sites = sites or []
        self.groups = groups or []
        self.errors = errors or {}
        self.posts: list = []
        self.deletes: list = []
        # Which POST bodies actually store a tag. Default: none of them,
        # which is the beijerrefab symptom.
        self.stores = None
        self.store_at_scope = True
        # A console that says "created" but never lists the tag anywhere.
        self.claim_only = False
        self.claim_response = {"data": {"affected": 1}}

    # ── reads ──
    def get_all(self, endpoint, params=None):
        params = params or {}
        if endpoint in self.errors:
            raise S1APIError(self.errors[endpoint], 403)
        if endpoint in tag_audit.ENDPOINT_TAG_ROUTES:
            if endpoint != self.endpoint_route:
                raise S1APIError(f"GET {endpoint} → 404", 404)
            if not self.store_at_scope and params.get("tenant") != "true":
                return []
            return list(self.endpoint_tags)
        if endpoint == "/tags":
            out = [t for t in self.tags
                   if t.get("type") == params.get("type")]
            if "scope" in params:
                out = [t for t in out if t.get("scope") == params["scope"]]
            return out
        return []

    def get_accounts(self):
        return self.accounts

    def get_sites(self, params=None):
        wanted = (params or {}).get("accountIds")
        if not wanted:
            return self.sites
        return [s for s in self.sites
                if str(s.get("accountId", wanted)) == str(wanted)]

    def get_groups(self, params=None):
        return self.groups

    # ── writes ──
    def _post(self, endpoint, body=None):
        self.posts.append(body)
        if self.claim_only:
            return self.claim_response
        if self.stores is not None and body == self.stores:
            tag = body.get("data")
            if isinstance(tag, list):
                tag = tag[0]
            elif isinstance(tag, dict) and "tags" in tag:
                tag = tag["tags"][0]
            elif not isinstance(tag, dict):
                tag = dict(body)
            self.endpoint_tags.append({**tag, "id": f"id-{len(self.posts)}"})
        return {}

    def _request(self, method, endpoint, body=None):
        self.deletes.append((method, endpoint, body))
        ids = (body.get("data") or body.get("filter") or {}).get("ids") or []
        self.endpoint_tags = [t for t in self.endpoint_tags
                              if t.get("id") not in ids]
        return {}


# ── name matching ──────────────────────────────────────────────────────

def test_blank_filter_matches_everything():
    assert tag_audit.name_matches("Beijer Ref AB", "")


def test_name_match_ignores_case_and_padding():
    assert tag_audit.name_matches("  Beijer  Ref ", "beijer ref")


def test_name_match_allows_substring():
    assert tag_audit.name_matches("Beijer Ref AB", "beijer")
    assert not tag_audit.name_matches("Beijer Ref AB", "carrier")


# ── scope filters and labels ───────────────────────────────────────────

def test_scope_filter_per_level():
    assert tag_audit.scope_filter("global", "") == {"tenant": "true"}
    assert tag_audit.scope_filter("account", "1") == {"accountIds": ["1"]}
    assert tag_audit.scope_filter("site", "2") == {"siteIds": ["2"]}
    assert tag_audit.scope_filter("group", "3") == {"groupIds": ["3"]}


def test_endpoint_tags_are_labelled_key_equals_value():
    assert tag_audit.tag_label({"key": "Dept", "value": "Finance"}) \
        == "Dept=Finance"
    assert tag_audit.tag_label({"key": "Dept"}) == "Dept"
    assert tag_audit.tag_label({"name": "Block USB"}) == "Block USB"


# ── scope enumeration ──────────────────────────────────────────────────

def _api_with_tree():
    return FakeAPI(
        accounts=[{"id": "a1", "name": "Beijer"}, {"id": "a2", "name": "Other"}],
        sites=[{"id": "s1", "name": "US", "accountId": "a1"}],
        groups=[{"id": "g1", "name": "Servers"}])


def test_enumerate_scopes_starts_at_the_tenant():
    scopes = tag_audit.enumerate_scopes(_api_with_tree())
    assert scopes[0] == ("global", "", "(tenant)")


def test_account_filter_narrows_the_sweep():
    scopes = tag_audit.enumerate_scopes(_api_with_tree(), account_name="beijer")
    paths = [p for _t, _i, p in scopes]
    assert "Beijer" in paths and "Other" not in paths


def test_site_filter_drops_the_account_scope():
    # Asking about a site means the account scope is noise, not an answer.
    scopes = tag_audit.enumerate_scopes(_api_with_tree(), site_name="US")
    assert [t for t, _i, _p in scopes] == ["global", "site"]


def test_groups_are_opt_in():
    without = tag_audit.enumerate_scopes(_api_with_tree())
    within = tag_audit.enumerate_scopes(_api_with_tree(), include_groups=True)
    assert not any(t == "group" for t, _i, _p in without)
    assert any(t == "group" for t, _i, _p in within)


def test_unreadable_accounts_raise_rather_than_audit_nothing():
    api = FakeAPI()

    def boom():
        raise S1APIError("403 forbidden", 403)

    api.get_accounts = boom
    with pytest.raises(S1APIError):
        tag_audit.enumerate_scopes(api)


# ── reading one scope ──────────────────────────────────────────────────

def _api_with_tags():
    return FakeAPI(tags=[
        {"id": "t1", "name": "SiteTag", "type": "firewall", "scope": "site"},
        {"id": "t2", "name": "AcctTag", "type": "firewall", "scope": "account"},
    ], endpoint_tags=[{"id": "e1", "key": "Dept", "value": "Finance"}])


def test_inherited_tags_are_separated_from_a_scopes_own():
    found = tag_audit.read_scope(_api_with_tags(), "site", "s1")
    fw = found["named"]["firewall"]
    assert [t["name"] for t in fw["own"]] == ["SiteTag"]
    assert [t["name"] for t in fw["inherited"]] == ["AcctTag"]


def test_scope_field_is_the_fallback_when_the_api_ignores_scope():
    api = _api_with_tags()
    real_get_all = api.get_all

    def no_scope_support(endpoint, params=None):
        if endpoint == "/tags" and "scope" in (params or {}):
            raise S1APIError("unknown parameter", 400)
        return real_get_all(endpoint, params)

    api.get_all = no_scope_support
    found = tag_audit.read_scope(api, "site", "s1")
    fw = found["named"]["firewall"]
    assert [t["name"] for t in fw["own"]] == ["SiteTag"]
    assert [t["name"] for t in fw["inherited"]] == ["AcctTag"]


def test_a_tag_without_a_scope_field_still_counts_as_owned():
    api = FakeAPI(tags=[{"id": "t9", "name": "Legacy", "type": "firewall"}])
    api.get_all_original = api.get_all

    def no_scope_support(endpoint, params=None):
        if endpoint == "/tags" and "scope" in (params or {}):
            raise S1APIError("unknown parameter", 400)
        return api.get_all_original(endpoint, params)

    api.get_all = no_scope_support
    found = tag_audit.read_scope(api, "site", "s1")
    assert [t["name"] for t in found["named"]["firewall"]["own"]] == ["Legacy"]


def test_one_unreadable_tag_type_does_not_blank_the_others():
    api = _api_with_tags()
    api.errors["/agents/tags"] = "403 no Tag Management.view"
    found = tag_audit.read_scope(api, "site", "s1")
    assert found["errors"]["endpoint"]
    assert found["named"]["firewall"]["own"]


def test_endpoint_tags_are_read_from_agents_tags():
    found = tag_audit.read_scope(_api_with_tags(), "site", "s1")
    assert [t["key"] for t in found["endpoint"]] == ["Dept"]
    assert found["endpoint_route"] == "/agents/tags"


def test_endpoint_tags_are_found_on_an_alternate_route():
    # A console that doesn't serve /agents/tags must not be reported as
    # holding no endpoint tags.
    api = _api_with_tags()
    api.endpoint_route = "/tag-manager"
    found = tag_audit.read_scope(api, "site", "s1")
    assert [t["key"] for t in found["endpoint"]] == ["Dept"]
    assert found["endpoint_route"] == "/tag-manager"


def test_no_route_answering_is_recorded_as_an_error():
    api = _api_with_tags()
    api.endpoint_route = "/somewhere-else"
    found = tag_audit.read_scope(api, "site", "s1")
    assert found["errors"]["endpoint"]
    assert found["endpoint"] == []


# ── row flattening ─────────────────────────────────────────────────────

def test_rows_hide_inherited_tags_by_default():
    found = tag_audit.read_scope(_api_with_tags(), "site", "s1")
    rows = tag_audit.scope_rows("site", "Beijer/US", found)
    assert {r["owned"] for r in rows} == {"own"}
    assert {r["tag"] for r in rows} == {"SiteTag", "Dept=Finance"}


def test_rows_can_include_inherited_tags():
    found = tag_audit.read_scope(_api_with_tags(), "site", "s1")
    rows = tag_audit.scope_rows("site", "Beijer/US", found,
                                include_inherited=True)
    assert any(r["owned"] == "inherited" and r["tag"] == "AcctTag"
               for r in rows)


def test_rows_can_be_filtered_to_endpoint_tags_only():
    found = tag_audit.read_scope(_api_with_tags(), "site", "s1")
    rows = tag_audit.scope_rows("site", "Beijer/US", found,
                                tag_type="endpoint")
    assert [r["tag"] for r in rows] == ["Dept=Finance"]


# ── the write probe ────────────────────────────────────────────────────

def test_probe_reports_the_shape_the_console_actually_stores():
    api = FakeAPI()
    scope = tag_audit.scope_filter("site", "s1")
    api.stores = {"data": [{"type": "agents", "key": "s1cc-probe-120000-2",
                            "value": "probe"}], "filter": scope}
    res = tag_audit.probe_endpoint_tag_shapes(api, "site", "s1", "120000")
    assert res["winner"] == "data array + filter"
    assert not res["wrong_scope"]


def test_probe_reports_no_op_when_nothing_is_stored():
    api = FakeAPI()
    res = tag_audit.probe_endpoint_tag_shapes(api, "site", "s1", "120000")
    assert res["winner"] is None
    assert not res["unreadable"]
    assert {r["outcome"] for r in res["results"]} == {"no-op"}
    assert len(api.posts) == len(tag_audit.PROBE_SHAPES)


def test_probe_separates_a_claimed_create_from_a_discarded_one():
    # The console says it created something and no route can show it: the
    # write may well have worked, so this must not be called a no-op.
    api = FakeAPI()
    api.claim_only = True
    res = tag_audit.probe_endpoint_tag_shapes(api, "site", "s1", "120000")
    assert res["unreadable"]
    assert res["winner"] is None
    assert {r["outcome"] for r in res["results"]} == {"claimed-unreadable"}


def test_a_claim_of_zero_affected_is_still_a_no_op():
    api = FakeAPI()
    api.claim_only = True
    api.claim_response = {"data": {"affected": 0}}
    res = tag_audit.probe_endpoint_tag_shapes(api, "site", "s1", "120000")
    assert not res["unreadable"]
    assert {r["outcome"] for r in res["results"]} == {"no-op"}


def test_probe_keeps_what_the_console_answered():
    api = FakeAPI()
    api.claim_only = True
    api.claim_response = {"data": {"affected": 1}}
    res = tag_audit.probe_endpoint_tag_shapes(api, "site", "s1", "120000")
    assert all("affected" in r["response"] for r in res["results"])
    assert res["probe_keys"] == [f"s1cc-probe-120000-{i}"
                                 for i in range(1, 6)]


def test_probe_finds_a_tag_listed_on_an_alternate_route():
    api = FakeAPI(endpoint_route="/tag-manager")
    scope = tag_audit.scope_filter("site", "s1")
    api.stores = {"data": {"type": "agents", "key": "s1cc-probe-120000-1",
                           "value": "probe"}, "filter": scope}
    res = tag_audit.probe_endpoint_tag_shapes(api, "site", "s1", "120000")
    assert res["winner"] == "data object + filter  (what the restore sends)"
    assert res["found_via"] == "GET /tag-manager"


def test_a_tag_keyed_under_a_different_field_still_counts():
    api = FakeAPI()
    api.endpoint_tags.append({"id": "e9", "tagName": "S1CC-Probe-120000-1"})
    found, where, at_scope = tag_audit.find_endpoint_tag(
        api, "s1cc-probe-120000-1", tag_audit.scope_filter("site", "s1"))
    assert found and at_scope and where == "GET /agents/tags"


def test_probe_flags_a_tag_stored_at_the_wrong_scope():
    api = FakeAPI()
    scope = tag_audit.scope_filter("site", "s1")
    api.stores = {"data": {"type": "agents", "key": "s1cc-probe-120000-1",
                           "value": "probe"}, "filter": scope}
    api.store_at_scope = False  # only the tenant-wide read finds it
    res = tag_audit.probe_endpoint_tag_shapes(api, "site", "s1", "120000")
    assert res["wrong_scope"]
    assert "wrong scope" in res["winner"]


def test_probe_deletes_every_tag_it_created():
    api = FakeAPI()
    scope = tag_audit.scope_filter("site", "s1")
    api.stores = {"data": {"type": "agents", "key": "s1cc-probe-120000-1",
                           "value": "probe"}, "filter": scope}
    res = tag_audit.probe_endpoint_tag_shapes(api, "site", "s1", "120000")
    assert api.deletes
    assert not res["leftovers"]
    assert not [t for t in api.endpoint_tags
                if str(t.get("key", "")).startswith("s1cc-probe")]


def test_probe_names_tags_it_could_not_delete():
    api = FakeAPI()
    scope = tag_audit.scope_filter("site", "s1")
    api.stores = {"data": {"type": "agents", "key": "s1cc-probe-120000-1",
                           "value": "probe"}, "filter": scope}

    def undeletable(method, endpoint, body=None):
        raise S1APIError("no permission to delete", 403)

    api._request = undeletable
    res = tag_audit.probe_endpoint_tag_shapes(api, "site", "s1", "120000")
    assert res["leftovers"]


def test_probe_records_a_rejected_shape_and_keeps_going():
    api = FakeAPI()
    real_post = api._post

    def picky(endpoint, body=None):
        if body.get("filter") is None:
            raise S1APIError("filter required", 400)
        return real_post(endpoint, body)

    api._post = picky
    res = tag_audit.probe_endpoint_tag_shapes(api, "site", "s1", "120000")
    assert any(r["outcome"] == "rejected" for r in res["results"])
    assert len(res["results"]) == len(tag_audit.PROBE_SHAPES)
