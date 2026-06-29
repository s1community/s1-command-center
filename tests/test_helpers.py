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
    explain_error,
    _is_exists_error,
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
