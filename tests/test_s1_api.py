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
