import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pages
from pages import BackupPage


class FakeAPI:
    base_url = "https://src.example"

    def get_my_user(self):
        return {"email": "user@example.com"}

    def get_accounts(self):
        return [{"id": "A1", "name": "Arol Group SpA"}]

    def get_sites(self, params=None):
        return []


class FakeTable:
    def __init__(self):
        self.rows = []

    def add_node(self, nid, path, kind):
        self.rows.append((nid, path, kind))

    def set_running(self, nid):
        pass

    def set_done(self, nid, summary):
        pass

    def set_skipped(self, nid, reason):
        pass


class FakeProgress:
    def set(self, value):
        pass


def _fake_page(monkeypatch, acct_id=""):
    page = types.SimpleNamespace()
    page.ptable = FakeTable()
    page.progress = FakeProgress()
    page._acct_id = acct_id
    page._cancelled = False
    page._operation_log = []
    page._last_results = []
    page.after = lambda _delay, fn: fn()
    page._read_node = lambda *a, **k: {"ok": True}
    monkeypatch.setattr(pages, "cli_log", lambda *_a, **_k: None)
    return page


def test_backup_account_filter_ignores_invisible_characters(monkeypatch):
    page = _fake_page(monkeypatch)
    nodes = BackupPage._run_backup(
        page,
        FakeAPI(),
        {"global": False, "accounts": True, "sites": False, "groups": False},
        ["policy"],
        {"account": "Arol\u200b Group SpA", "site": "", "group": ""},
    )
    assert len(nodes) == 1
    assert nodes[0]["path"] == "Arol Group SpA/"


def test_backup_falls_back_to_account_name_when_ticket_id_is_stale(monkeypatch):
    page = _fake_page(monkeypatch, acct_id="STALE")
    nodes = BackupPage._run_backup(
        page,
        FakeAPI(),
        {"global": False, "accounts": True, "sites": False, "groups": False},
        ["policy"],
        {"account": "Arol Group SpA", "site": "", "group": ""},
    )
    assert len(nodes) == 1
    assert nodes[0]["account"]["id"] == "A1"


class FakeAPISites:
    base_url = "https://src.example"

    def get_my_user(self):
        return {"email": "user@example.com"}

    def get_accounts(self):
        return [{"id": "A1", "name": "ThomsonReuters"}]

    def get_sites(self, params=None):
        return [
            {"id": "S1", "name": "HighQ_Servers"},
            {"id": "S2", "name": "Servers"},
            {"id": "S3", "name": "TR-Servers"},
        ]

    def get_groups(self, params=None):
        return []


def _site_backup(monkeypatch, site_filter):
    page = _fake_page(monkeypatch)
    return BackupPage._run_backup(
        page,
        FakeAPISites(),
        {"global": False, "accounts": False, "sites": True, "groups": False},
        ["policy"],
        {"account": "ThomsonReuters", "site": site_filter, "group": ""},
    )


def test_backup_site_filter_prefers_exact_match(monkeypatch):
    # "Servers" must NOT also pull in "HighQ_Servers" / "TR-Servers".
    nodes = _site_backup(monkeypatch, "Servers")
    paths = [n["path"] for n in nodes]
    assert paths == ["ThomsonReuters/Servers"]


def test_backup_site_filter_substring_fallback(monkeypatch):
    # No site is exactly "Serv" -> fall back to substring (all three).
    nodes = _site_backup(monkeypatch, "Serv")
    paths = sorted(n["path"] for n in nodes)
    assert paths == [
        "ThomsonReuters/HighQ_Servers",
        "ThomsonReuters/Servers",
        "ThomsonReuters/TR-Servers",
    ]


def test_backup_site_filter_blank_matches_all(monkeypatch):
    nodes = _site_backup(monkeypatch, "")
    assert len(nodes) == 3


def test_select_by_name_exact_preferred():
    items = [{"name": "HighQ_Servers"}, {"name": "Servers"},
             {"name": "TR-Servers"}]
    key = lambda x: x.get("name", "")
    # exact wins
    assert pages._select_by_name(items, "Servers", key=key) == \
        [{"name": "Servers"}]
    # substring fallback when no exact match
    assert len(pages._select_by_name(items, "Serv", key=key)) == 3
    # blank returns everything
    assert pages._select_by_name(items, "", key=key) == items
    # case / whitespace / zero-width insensitive exact match
    assert pages._select_by_name(items, "  servers ", key=key) == \
        [{"name": "Servers"}]
    assert pages._select_by_name(items, "Servers\u200b", key=key) == \
        [{"name": "Servers"}]
