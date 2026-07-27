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
