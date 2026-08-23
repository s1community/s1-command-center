"""STAR rule import scope (issue #7).

The STAR Rules page always created rules at the tenant, so an account- or
site-scoped API token got "User …:account can not create rule with higher
scope None:tenant" for every rule and imported nothing. The page now takes
an Account/Site scope, and the import falls back to the one account a
scope-limited token can reach.
"""
import os
import sys
from datetime import datetime, timezone

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("customtkinter")

import pages_extra  # noqa: E402
from s1_api import S1APIError  # noqa: E402

NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)

HIGHER_SCOPE = S1APIError(
    "POST /cloud-detection/rules → 400", 400,
    "Validation Error :: User 1449449408854677414:account can not create "
    "rule with higher scope None:tenant (code 4000010)")


class FakeAPI:
    """Records what scope each create was sent with."""

    def __init__(self, accounts=(), sites=(), refuse_tenant=False):
        self._accounts = list(accounts)
        self._sites = list(sites)
        self.refuse_tenant = refuse_tenant
        self.creates = []

    def get_accounts(self, **kw):
        return list(self._accounts)

    def get_sites(self, params=None, **kw):
        return list(self._sites)

    def get_star_rules(self, scope):
        return []

    def create_star_rule(self, scope, data):
        self.creates.append((dict(scope), data))
        if self.refuse_tenant and "tenant" in scope:
            raise HIGHER_SCOPE
        return {"data": {"id": "1"}}


def _rule(name="AsyncRAT"):
    return {"id": "9", "name": name, "s1ql": 'ProcessName = "x.exe"',
            "severity": "High", "scope": "account", "activeResponse": False}


# ── scope resolution ───────────────────────────────────────────────────

def test_blank_names_mean_the_tenant():
    api = FakeAPI()
    assert pages_extra.resolve_scope_filter(api, "", "") == {"tenant": "true"}


def test_an_account_name_becomes_account_ids():
    api = FakeAPI(accounts=[{"id": "7", "name": "Contoso"}])
    assert pages_extra.resolve_scope_filter(api, "Contoso", "") == {
        "accountIds": "7"}


def test_the_account_name_is_matched_case_insensitively():
    api = FakeAPI(accounts=[{"id": "7", "name": "Contoso"}])
    assert pages_extra.resolve_scope_filter(api, " contoso ", "") == {
        "accountIds": "7"}


def test_a_site_name_wins_over_the_account():
    api = FakeAPI(accounts=[{"id": "7", "name": "Contoso"}],
                  sites=[{"id": "42", "name": "HQ"}])
    assert pages_extra.resolve_scope_filter(api, "Contoso", "HQ") == {
        "siteIds": "42"}


def test_an_unknown_account_names_itself_in_the_error():
    api = FakeAPI(accounts=[{"id": "7", "name": "Contoso"}])
    with pytest.raises(ValueError, match="Fabrikam"):
        pages_extra.resolve_scope_filter(api, "Fabrikam", "")


def test_an_unknown_site_names_itself_in_the_error():
    api = FakeAPI(accounts=[{"id": "7", "name": "Contoso"}], sites=[])
    with pytest.raises(ValueError, match="Warehouse"):
        pages_extra.resolve_scope_filter(api, "Contoso", "Warehouse")


def test_scope_label_reads_back_the_filter():
    assert pages_extra.scope_label({"siteIds": "1"}) == "site scope"
    assert pages_extra.scope_label({"accountIds": "1"}) == "account scope"
    assert pages_extra.scope_label({"tenant": "true"}) == "tenant scope"


# ── importing at a chosen scope ────────────────────────────────────────

def test_rules_are_created_at_the_scope_asked_for():
    api = FakeAPI()
    created, failures, scope = pages_extra.import_star_rules(
        api, [_rule()], {"accountIds": "7"}, NOW)
    assert (created, failures) == (1, [])
    assert api.creates[0][0] == {"accountIds": "7"}
    assert scope == {"accountIds": "7"}


def test_the_rule_is_prepared_before_it_is_sent():
    # Same preparation as a migration restore — no read-only fields.
    api = FakeAPI()
    pages_extra.import_star_rules(api, [_rule()], {"siteIds": "42"}, NOW)
    sent = api.creates[0][1]
    for field in ("id", "scope", "activeResponse"):
        assert field not in sent
    assert sent["name"] == "AsyncRAT"


# ── the reported failure ───────────────────────────────────────────────

def test_a_token_below_the_tenant_imports_into_its_own_account():
    api = FakeAPI(accounts=[{"id": "7", "name": "Contoso"}],
                  refuse_tenant=True)
    created, failures, scope = pages_extra.import_star_rules(
        api, [_rule("AsyncRAT"), _rule("Adaptix C2")], {"tenant": "true"}, NOW)
    assert (created, failures) == (2, [])
    assert scope == {"accountIds": "7"}
    # first attempt at the tenant, then everything at the account
    assert [c[0] for c in api.creates] == [
        {"tenant": "true"}, {"accountIds": "7"}, {"accountIds": "7"}]


def test_several_reachable_accounts_report_the_error_instead_of_guessing():
    api = FakeAPI(accounts=[{"id": "7", "name": "Contoso"},
                            {"id": "8", "name": "Fabrikam"}],
                  refuse_tenant=True)
    created, failures, scope = pages_extra.import_star_rules(
        api, [_rule()], {"tenant": "true"}, NOW)
    assert created == 0
    assert scope == {"tenant": "true"}
    assert "higher scope" in failures[0][1]


def test_the_reason_reaches_the_caller_with_the_rule_name():
    api = FakeAPI(accounts=[], refuse_tenant=True)
    created, failures, _ = pages_extra.import_star_rules(
        api, [_rule("AsyncRAT")], {"tenant": "true"}, NOW)
    assert created == 0
    name, err = failures[0]
    assert name == "AsyncRAT"
    assert "can not create rule with higher scope" in err


def test_an_account_scope_that_is_refused_is_not_retried_elsewhere():
    # Only a tenant request can be "too high"; anything else is a real error.
    class Refuses(FakeAPI):
        def create_star_rule(self, scope, data):
            self.creates.append((dict(scope), data))
            raise S1APIError("POST /cloud-detection/rules → 400", 400,
                             "s1ql: Missing data for required field")

    api = Refuses(accounts=[{"id": "7", "name": "Contoso"}])
    created, failures, scope = pages_extra.import_star_rules(
        api, [_rule()], {"accountIds": "7"}, NOW)
    assert created == 0
    assert len(api.creates) == 1
    assert scope == {"accountIds": "7"}
    assert "Missing data" in failures[0][1]


def test_the_page_reads_its_scope_boxes_for_both_load_and_import():
    import inspect
    for method in (pages_extra.STARRulesPage._load,
                   pages_extra.STARRulesPage._import):
        src = inspect.getsource(method)
        assert "resolve_scope_filter" in src
        assert '{"tenant": "true"}' not in src
