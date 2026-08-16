"""Unit tests for the SentinelOne API client (s1_api.py).

These exercise the auth-header heuristic, the structured-error extraction,
and the retry/backoff branching in ``S1API._request`` — all without touching
the network (the requests Session is replaced with a fake).
"""
import sys
import types
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import s1_api
from s1_api import S1API, S1APIError, _auth_header


# ── _auth_header ────────────────────────────────────────────────────────

def test_auth_header_jwt_uses_bearer():
    jwt = "aaa.bbb.ccc"
    assert _auth_header(jwt) == f"Bearer {jwt}"


def test_auth_header_api_token_uses_apitoken():
    tok = "plain_api_token_value_1234567890"
    assert _auth_header(tok) == f"ApiToken {tok}"


def test_auth_header_strips_before_matching():
    # leading/trailing whitespace must not defeat the JWT detection
    assert _auth_header("  aaa.bbb.ccc  ").startswith("Bearer ")


# ── fakes ───────────────────────────────────────────────────────────────

class FakeResp:
    def __init__(self, status_code, json_body=None, text="", headers=None):
        self.status_code = status_code
        self._json = json_body
        self.text = text
        self.headers = headers or {}

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeSession:
    """Records calls and replays a queued list of responses (or raises)."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.headers = {}
        self.verify = True

    def request(self, method, url, params=None, json=None, timeout=None):
        self.calls.append((method, url, params, json))
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def mount(self, *a, **k):
        pass


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Make backoff instant so tests don't actually wait."""
    monkeypatch.setattr(s1_api._time, "sleep", lambda *_a, **_k: None)


def _client(responses):
    api = S1API("https://example.sentinelone.net", "tok")
    api.session = FakeSession(responses)
    return api


def test_client_requests_uncompressed_json():
    api = S1API("https://example.sentinelone.net", "tok")
    assert api.session.headers["Accept-Encoding"] == "identity"


def test_content_decoding_error_is_wrapped_with_endpoint():
    err = s1_api.requests.exceptions.ContentDecodingError(
        "Error -3 while decompressing data: incorrect header check")
    api = _client([err, err, err, err])
    with pytest.raises(S1APIError) as exc:
        api._request("GET", "/accounts")
    assert "GET /accounts failed after 4 attempts" in str(exc.value)
    assert "response decoding failed" in exc.value.detail
    assert "incorrect header check" in exc.value.detail


# ── _request happy path ─────────────────────────────────────────────────

def test_request_returns_json_on_200():
    api = _client([FakeResp(200, {"data": [1, 2, 3]})])
    assert api._request("GET", "/sites") == {"data": [1, 2, 3]}


def test_request_accepts_201():
    api = _client([FakeResp(201, {"data": {"id": "x"}})])
    assert api._request("POST", "/sites", body={}) == {"data": {"id": "x"}}


# ── _request error handling ─────────────────────────────────────────────

def test_4xx_raises_immediately_without_retry():
    api = _client([FakeResp(400, {"errors": [{"title": "Bad", "code": 4000010}]})])
    with pytest.raises(S1APIError) as ei:
        api._request("POST", "/sites", body={})
    assert ei.value.status_code == 400
    # exactly one attempt — 4xx must not be retried
    assert len(api.session.calls) == 1
    assert "Bad" in ei.value.detail and "4000010" in ei.value.detail


def test_error_detail_concatenates_multiple_errors():
    body = {"errors": [
        {"title": "First", "detail": "d1", "code": 1},
        {"title": "Second"},
    ]}
    api = _client([FakeResp(422, body)])
    with pytest.raises(S1APIError) as ei:
        api._request("GET", "/x")
    assert "First :: d1 (code 1)" in ei.value.detail
    assert "Second" in ei.value.detail


def test_5xx_retries_then_succeeds():
    api = _client([FakeResp(500, {}), FakeResp(200, {"data": "ok"})])
    assert api._request("GET", "/x") == {"data": "ok"}
    assert len(api.session.calls) == 2


def test_429_retries_and_honors_retry_after(monkeypatch):
    slept = []
    monkeypatch.setattr(s1_api._time, "sleep", lambda s: slept.append(s))
    api = _client([
        FakeResp(429, {}, headers={"Retry-After": "2"}),
        FakeResp(200, {"data": "ok"}),
    ])
    assert api._request("GET", "/x") == {"data": "ok"}
    assert 2 in slept  # honored the Retry-After header


def test_5xx_exhausts_retries_and_raises():
    api = _client([FakeResp(503, {}) for _ in range(4)])
    with pytest.raises(S1APIError) as ei:
        api._request("GET", "/x", retries=4)
    assert ei.value.status_code == 503
    assert len(api.session.calls) == 4


def test_connection_error_retries_then_raises():
    import requests
    api = _client([requests.exceptions.ConnectionError("boom")] * 4)
    with pytest.raises(S1APIError) as ei:
        api._request("GET", "/x", retries=4)
    # connection failures surface as status_code 0 after exhausting retries
    assert ei.value.status_code == 0
    assert len(api.session.calls) == 4


def test_connection_error_recovers_on_retry():
    import requests
    api = _client([
        requests.exceptions.ConnectionError("boom"),
        FakeResp(200, {"data": "recovered"}),
    ])
    assert api._request("GET", "/x") == {"data": "recovered"}


def test_non_json_error_body_falls_back_to_text():
    api = _client([FakeResp(400, json_body=None, text="plain text error")])
    with pytest.raises(S1APIError) as ei:
        api._request("GET", "/x")
    assert ei.value.detail == "plain text error"


def test_get_roles_passes_account_scope():
    api = _client([FakeResp(200, {"data": [{"id": "r1", "name": "Custom"}]})])
    roles = api.get_roles(params={"accountIds": "A1"})
    assert roles == [{"id": "r1", "name": "Custom"}]
    _method, url, params, _json = api.session.calls[0]
    assert url.endswith("/rbac/roles")
    assert params["accountIds"] == "A1"


def test_get_roles_no_params_still_works():
    api = _client([FakeResp(200, {"data": []})])
    assert api.get_roles() == []


def test_get_role_hits_definition_endpoint_with_scope():
    api = _client([FakeResp(200, {"data": {"id": "r1", "name": "Custom",
                                           "permissions": [{"id": "p"}]}})])
    role = api.get_role("r1", params={"accountIds": "A1"})
    assert role["permissions"] == [{"id": "p"}]
    _method, url, params, _json = api.session.calls[0]
    assert url.endswith("/rbac/role/r1")
    assert params["accountIds"] == "A1"


def test_create_role_posts_data_envelope():
    api = _client([FakeResp(201, {"data": {"id": "new"}})])
    api.create_role({"name": "Custom", "pages": []})
    method, url, _params, body = api.session.calls[0]
    assert method == "POST"
    assert url.endswith("/rbac/role")
    # No scope filter passed → bare data envelope.
    assert body == {"data": {"name": "Custom", "pages": []}}


def test_create_role_includes_scope_filter():
    api = _client([FakeResp(201, {"data": {"id": "new"}})])
    api.create_role({"name": "Custom"}, {"accountIds": ["DEST"]})
    _method, url, _params, body = api.session.calls[0]
    assert url.endswith("/rbac/role")
    # S1 requires a top-level `filter`; scope must not be inside `data`.
    assert body == {"data": {"name": "Custom"},
                    "filter": {"accountIds": ["DEST"]}}


def test_get_role_template_hits_rbac_role_with_scope():
    api = _client([FakeResp(200, {"data": {"pages": [{"id": "p"}]}})])
    tmpl = api.get_role_template(params={"accountIds": "A1"})
    assert tmpl == {"pages": [{"id": "p"}]}
    _method, url, params, _json = api.session.calls[0]
    assert url.endswith("/rbac/role")
    assert params["accountIds"] == "A1"


# ── tags ────────────────────────────────────────────────────────────────
# Endpoint ("unified") tags are a different API from the named /tags objects.
# The old code called a non-existent /endpoint-tags route, so endpoint tags
# were silently never backed up and never restored (Joshua Tooley, 2026-08).

def test_get_tags_passes_type_and_scope():
    api = _client([FakeResp(200, {"data": [{"id": "t1", "name": "Servers"}]})])
    tags = api.get_tags("firewall", {"siteIds": ["S1"]})
    assert tags == [{"id": "t1", "name": "Servers"}]
    method, url, params, _body = api.session.calls[0]
    assert method == "GET" and url.endswith("/tags")
    assert params["type"] == "firewall" and params["siteIds"] == ["S1"]


def test_create_tag_uses_filter_data_envelope():
    api = _client([FakeResp(201, {"data": {"id": "new"}})])
    api.create_tag({"siteIds": ["S1"]}, {"name": "Servers", "type": "firewall"})
    method, url, _params, body = api.session.calls[0]
    assert method == "POST" and url.endswith("/tags")
    assert body == {"filter": {"siteIds": ["S1"]},
                    "data": {"name": "Servers", "type": "firewall"}}


def test_get_endpoint_tags_hits_agents_tags():
    api = _client([FakeResp(200, {"data": [{"id": "e1", "key": "Dept"}]})])
    assert api.get_endpoint_tags({"siteIds": ["S1"]}) == \
        [{"id": "e1", "key": "Dept"}]
    method, url, params, _body = api.session.calls[0]
    assert method == "GET" and url.endswith("/agents/tags")
    assert params["siteIds"] == ["S1"]


def test_create_endpoint_tag_posts_tag_manager_with_scope():
    api = _client([FakeResp(201, {"data": {"id": "new"}})])
    api.create_endpoint_tag({"key": "Dept", "type": "endpoints"},
                            {"siteIds": ["S1"]})
    method, url, _params, body = api.session.calls[0]
    assert method == "POST" and url.endswith("/tag-manager")
    assert body == {"data": {"key": "Dept", "type": "endpoints"},
                    "filter": {"siteIds": ["S1"]}}


def test_create_endpoint_tag_without_scope_omits_filter():
    api = _client([FakeResp(201, {"data": {"id": "new"}})])
    api.create_endpoint_tag({"key": "Dept", "type": "endpoints"})
    _method, _url, _params, body = api.session.calls[0]
    assert body == {"data": {"key": "Dept", "type": "endpoints"}}


# ── POST /tag-manager: a 2xx is not proof of a create ────────────────────
# The beijerrefab restore (2026-08-13) reported ~150 endpoint tags created
# with zero errors against a console that ended up with none: the route
# answers 200 to a body it does not store.

def _ep_tag(api):
    return api.create_endpoint_tag({"key": "Dept", "type": "endpoints"},
                                   {"siteIds": ["S1"]})


_NOT_THERE = FakeResp(200, {"data": []})       # read-back: no such tag


def _posts(api):
    return [c for c in api.session.calls if c[0] == "POST"]


def test_empty_2xx_is_not_counted_as_a_created_tag():
    api = _client([FakeResp(200, {"data": {}}), _NOT_THERE,
                   FakeResp(200, {"data": {}}), _NOT_THERE,
                   FakeResp(200, {"data": {}}), _NOT_THERE])
    with pytest.raises(S1APIError) as exc:
        _ep_tag(api)
    assert "created nothing" in str(exc.value)
    # every supported shape was tried, each one confirmed absent first
    assert len(_posts(api)) == 3


def test_affected_zero_is_not_counted_as_a_created_tag():
    api = _client([FakeResp(200, {"data": {"affected": 0}}), _NOT_THERE] * 3)
    with pytest.raises(S1APIError):
        _ep_tag(api)


def test_affected_count_counts_as_a_created_tag():
    api = _client([FakeResp(200, {"data": {"affected": 1}})])
    assert _ep_tag(api) == {"data": {"affected": 1}}
    assert len(api.session.calls) == 1


def test_create_endpoint_tag_falls_back_to_the_shape_that_stores():
    api = _client([FakeResp(200, {"data": {}}), _NOT_THERE,
                   FakeResp(200, {"data": [{"id": "new"}]})])
    assert _ep_tag(api) == {"data": [{"id": "new"}]}
    _m, _u, _p, body = _posts(api)[1]
    assert body == {"data": [{"key": "Dept", "type": "endpoints"}],
                    "filter": {"siteIds": ["S1"]}}


def test_a_create_the_console_stored_but_did_not_echo_is_accepted():
    # If the tag IS there afterwards, the empty response was just terse —
    # sending the next shape at it would create a second copy.
    api = _client([FakeResp(200, {}),
                   FakeResp(200, {"data": [{"id": "e1", "key": "Dept"}]})])
    _ep_tag(api)
    assert len(_posts(api)) == 1
    _m, _u, params, _b = api.session.calls[1]
    assert params["key__contains"] == "Dept"
    assert params["siteIds"] == ["S1"]


def test_unconfirmable_create_is_never_retried():
    # Read-back failed, so whether the tag was stored is unknown. Retrying
    # would risk duplicating it — raise instead.
    api = _client([FakeResp(200, {}), FakeResp(400, {})])
    with pytest.raises(S1APIError) as exc:
        _ep_tag(api)
    assert "could not confirm" in str(exc.value)
    assert len(_posts(api)) == 1


def test_create_endpoint_tag_tries_next_shape_when_one_is_rejected():
    api = _client([FakeResp(400, {"errors": [{"detail": "unknown field"}]}),
                   FakeResp(201, {"data": {"id": "new"}})])
    assert _ep_tag(api) == {"data": {"id": "new"}}


def test_create_endpoint_tag_surfaces_already_exists_immediately():
    # 409 is a real answer about this tag — it must not be retried as a
    # shape problem, so the restore can report it as "exists", not "new".
    api = _client([FakeResp(409, {"errors": [{"detail": "Already Exists"}]})])
    with pytest.raises(S1APIError) as exc:
        _ep_tag(api)
    assert exc.value.status_code == 409
    assert len(api.session.calls) == 1


# ── throttle telemetry ───────────────────────────────────────────────────

def test_throttle_counter_increments_on_429():
    api = _client([
        FakeResp(429, {}, headers={"Retry-After": "1"}),
        FakeResp(200, {"data": "ok"}),
    ])
    assert api.throttle_stats() == {"events": 0, "wait_seconds": 0.0}
    api._request("GET", "/x")
    assert api.throttle_stats()["events"] == 1
    assert api.throttle_stats()["wait_seconds"] >= 1.0


def test_throttle_callback_fires_with_info():
    seen = []
    api = _client([
        FakeResp(429, {}, headers={"Retry-After": "1"}),
        FakeResp(200, {"data": "ok"}),
    ])
    api.on_throttle = lambda info: seen.append(info)
    api._request("GET", "/sites")
    assert len(seen) == 1
    assert seen[0]["endpoint"] == "/sites"
    assert seen[0]["events"] == 1


def test_5xx_does_not_count_as_throttle():
    api = _client([FakeResp(500, {}), FakeResp(200, {"data": "ok"})])
    api._request("GET", "/x")
    assert api.throttle_stats()["events"] == 0  # only 429 counts


def test_throttle_callback_errors_are_swallowed():
    api = _client([
        FakeResp(429, {}, headers={"Retry-After": "1"}),
        FakeResp(200, {"data": "ok"}),
    ])
    api.on_throttle = lambda info: 1 / 0  # must not break the request
    assert api._request("GET", "/x") == {"data": "ok"}
