"""Unit tests for the opt-in scope-listing cache on S1API.

A restore resolves every one of its hundreds of nodes against the
accounts/sites/groups listings; without caching that is thousands of
identical round-trips. These tests lock down that the cache is off by
default, memoises per (kind, params), invalidates the right kind on a
create, and never hands back an object a caller can use to corrupt it.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from s1_api import S1API


def _api():
    # __init__ only builds a requests.Session — no network — so this is safe.
    return S1API("https://example.sentinelone.net", "token", verify_ssl=False)


def _counting_fetch():
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return [{"id": calls["n"]}]

    return calls, fetch


# ── default behaviour ───────────────────────────────────────────────────

def test_cache_is_off_by_default():
    api = _api()
    calls, fetch = _counting_fetch()
    api._scope_cached("accounts", None, fetch)
    api._scope_cached("accounts", None, fetch)
    assert calls["n"] == 2  # every call hits the network


# ── memoisation ─────────────────────────────────────────────────────────

def test_enabled_cache_serves_repeat_reads_from_memory():
    api = _api()
    api.enable_scope_cache()
    calls, fetch = _counting_fetch()
    for _ in range(50):
        api._scope_cached("accounts", None, fetch)
    assert calls["n"] == 1


def test_cache_keys_on_params():
    api = _api()
    api.enable_scope_cache()
    calls, fetch = _counting_fetch()
    api._scope_cached("sites", {"accountIds": "1"}, fetch)
    api._scope_cached("sites", {"accountIds": "2"}, fetch)
    api._scope_cached("sites", {"accountIds": "1"}, fetch)
    assert calls["n"] == 2  # one per distinct account, third is a hit


def test_cache_key_is_order_independent():
    api = _api()
    api.enable_scope_cache()
    calls, fetch = _counting_fetch()
    api._scope_cached("groups", {"siteIds": "9", "limit": 200}, fetch)
    api._scope_cached("groups", {"limit": 200, "siteIds": "9"}, fetch)
    assert calls["n"] == 1


def test_different_kinds_do_not_collide():
    api = _api()
    api.enable_scope_cache()
    calls, fetch = _counting_fetch()
    api._scope_cached("accounts", None, fetch)
    api._scope_cached("sites", None, fetch)
    api._scope_cached("groups", None, fetch)
    assert calls["n"] == 3


# ── invalidation ────────────────────────────────────────────────────────

def test_invalidate_one_kind_leaves_the_others():
    api = _api()
    api.enable_scope_cache()
    calls, fetch = _counting_fetch()
    api._scope_cached("accounts", None, fetch)
    api._scope_cached("sites", {"accountIds": "1"}, fetch)
    api.invalidate_scope_cache("accounts")
    api._scope_cached("accounts", None, fetch)          # refetched
    api._scope_cached("sites", {"accountIds": "1"}, fetch)  # still cached
    assert calls["n"] == 3


def test_invalidate_all_kinds():
    api = _api()
    api.enable_scope_cache()
    calls, fetch = _counting_fetch()
    api._scope_cached("accounts", None, fetch)
    api._scope_cached("sites", None, fetch)
    api.invalidate_scope_cache()
    api._scope_cached("accounts", None, fetch)
    api._scope_cached("sites", None, fetch)
    assert calls["n"] == 4


def test_invalidate_is_safe_before_any_reads():
    api = _api()
    api.enable_scope_cache()
    api.invalidate_scope_cache("sites")  # must not raise
    api.invalidate_scope_cache()


def test_disable_clears_and_stops_caching():
    api = _api()
    api.enable_scope_cache()
    calls, fetch = _counting_fetch()
    api._scope_cached("accounts", None, fetch)
    api.disable_scope_cache()
    api._scope_cached("accounts", None, fetch)
    api._scope_cached("accounts", None, fetch)
    assert calls["n"] == 3  # 1 while on, 2 while off (nothing cached)


def test_enable_starts_from_a_clean_slate():
    api = _api()
    api.enable_scope_cache()
    calls, fetch = _counting_fetch()
    api._scope_cached("accounts", None, fetch)
    api.enable_scope_cache()  # re-enable must drop the earlier entry
    api._scope_cached("accounts", None, fetch)
    assert calls["n"] == 2


# ── isolation: a caller mutating the result can't poison the cache ───────

def test_returned_list_is_a_copy():
    api = _api()
    api.enable_scope_cache()
    _, fetch = _counting_fetch()
    first = api._scope_cached("accounts", None, fetch)
    first.append({"id": "injected"})
    second = api._scope_cached("accounts", None, fetch)
    assert len(second) == 1
    assert second[0]["id"] != "injected"


# ── end-to-end through the public methods (patched transport) ────────────

def test_get_accounts_uses_cache_when_enabled(monkeypatch):
    api = _api()
    calls = {"n": 0}

    def fake_get_all(endpoint, params=None, **kw):
        calls["n"] += 1
        return [{"id": "acct", "endpoint": endpoint}]

    monkeypatch.setattr(api, "get_all", fake_get_all)
    api.enable_scope_cache()
    api.get_accounts()
    api.get_accounts()
    assert calls["n"] == 1
    api.invalidate_scope_cache("accounts")
    api.get_accounts()
    assert calls["n"] == 2


# ── account-creation diagnostics ────────────────────────────────────────

def test_any_state_lookup_asks_for_every_state(monkeypatch):
    api = _api()
    seen = {}

    def fake_get_all(endpoint, params=None, **kw):
        seen["endpoint"] = endpoint
        seen["params"] = params
        return []

    monkeypatch.setattr(api, "get_all", fake_get_all)
    api.get_accounts_any_state(name="Acme")
    assert seen["endpoint"] == "/accounts"
    assert seen["params"]["states"] == "active,expired,deleted"
    assert seen["params"]["name"] == "Acme"


def test_name_available_true(monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "_get",
                        lambda ep, params=None: {"data": {"available": True}})
    assert api.account_name_available("Acme") == (True, "")


def test_name_available_false(monkeypatch):
    api = _api()
    monkeypatch.setattr(
        api, "_get", lambda ep, params=None: {"data": {"nameAvailable": False}})
    avail, _ = api.account_name_available("Acme")
    assert avail is False


def test_name_available_surfaces_permission_error(monkeypatch):
    from s1_api import S1APIError

    api = _api()

    def boom(ep, params=None):
        raise S1APIError("nope", 403, "Insufficient permissions")

    monkeypatch.setattr(api, "_get", boom)
    avail, detail = api.account_name_available("Acme")
    assert avail is None
    assert "403" in detail and "Insufficient permissions" in detail


def test_diagnosis_reports_token_identity(monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "get_my_user", lambda: {
        "fullName": "Ran", "email": "ranj@example.com", "scope": "tenant",
        "scopeRoles": [{"roleId": "1", "roleName": "Admin"}]})
    monkeypatch.setattr(
        api, "get_all",
        lambda ep, params=None, **kw: [{"id": "1", "name": "A",
                                        "usageType": "customer"}])
    monkeypatch.setattr(api, "account_name_available", lambda n: (True, ""))
    notes = " | ".join(api.diagnose_account_creation("Acme"))
    assert "ranj@example.com" in notes
    assert "role=Admin" in notes
    assert "scope=tenant" in notes


def test_diagnosis_does_not_claim_non_mssp_from_usage_type(monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "get_my_user", lambda: {})
    monkeypatch.setattr(
        api, "get_all",
        lambda ep, params=None, **kw: [{"id": "1", "name": "A",
                                        "usageType": "customer"}])
    monkeypatch.setattr(api, "account_name_available", lambda n: (True, ""))
    notes = " | ".join(api.diagnose_account_creation("Acme"))
    assert "requires an MSSP deployment" not in notes
    assert "context only" in notes


def test_diagnosis_reports_existing_expired_account(monkeypatch):
    api = _api()
    monkeypatch.setattr(api, "get_my_user", lambda: {})
    monkeypatch.setattr(
        api, "get_all",
        lambda ep, params=None, **kw: [{"id": "9", "name": "Acme",
                                        "usageType": "mssp",
                                        "state": "expired"}])
    monkeypatch.setattr(api, "account_name_available",
                        lambda n: (False, ""))
    notes = " | ".join(api.diagnose_account_creation("Acme"))
    assert "NOT available" in notes
    assert "state=expired" in notes


def test_preflight_fails_when_accounts_needed_but_not_creatable():
    from migtools import evaluate_preflight, preflight_verdict

    checks = evaluate_preflight({
        "accounts_to_create": 64,
        "can_create_accounts": False,
        "account_create_reason": "console usageType is ['customer']",
    })
    acct = [c for c in checks if c.name == "Account creation"]
    assert acct and acct[0].status == "fail"
    assert "64 account(s)" in acct[0].detail
    assert preflight_verdict(checks) == "fail"


def test_preflight_passes_when_creation_allowed():
    from migtools import evaluate_preflight

    checks = evaluate_preflight({
        "accounts_to_create": 3, "can_create_accounts": True})
    acct = [c for c in checks if c.name == "Account creation"]
    assert acct and acct[0].status == "pass"


def test_preflight_ignores_capability_when_nothing_to_create():
    from migtools import evaluate_preflight

    checks = evaluate_preflight({
        "accounts_to_create": 0, "can_create_accounts": False})
    acct = [c for c in checks if c.name == "Account creation"]
    assert acct and acct[0].status == "info"


def test_get_accounts_with_kwargs_bypasses_cache(monkeypatch):
    api = _api()
    calls = {"n": 0}

    def fake_get_all(endpoint, params=None, **kw):
        calls["n"] += 1
        return []

    monkeypatch.setattr(api, "get_all", fake_get_all)
    api.enable_scope_cache()
    api.get_accounts(max_items=10)
    api.get_accounts(max_items=10)
    assert calls["n"] == 2  # kwargs path never touches the cache
