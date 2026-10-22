"""Restore-time account-name guard.

If NONE of the backup's account names exist on the destination console, the
operator most likely forgot to Mangle Rename the account (Structure
Operations), and a restore would silently create a brand-new account instead of
landing on the intended one. `_check_account_name_match` must:
  * return "abort" and open the backup-vs-destination comparison in that case,
  * but NOT nag when a name matches, when the destination has no accounts, or
    for global-only backups.

The method only touches a few instance attributes, so (like test_preview.py)
we drive it with a minimal fake `self` — no Tk display required.
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pages
from pages import RestorePage

check = RestorePage._check_account_name_match


class FakeAPI:
    base_url = "https://dst.example.net"

    def __init__(self, names):
        self._names = names

    def get_accounts(self):
        return [{"id": i, "name": n} for i, n in enumerate(self._names)]


def _fake_self(backup):
    """Minimal stand-in for a RestorePage — only what the guard reads."""
    s = types.SimpleNamespace()
    s.backup_data = backup
    s._console_var = types.SimpleNamespace(get=lambda: "DESTINATION")
    s._redirected = None
    s._compared = None
    s._open_structure_ops_for_rename = (
        lambda src, dst="": setattr(s, "_redirected", (src, dst)))
    s._compare_with_destination = (
        lambda api=None: setattr(s, "_compared", api))
    return s


def test_matching_account_does_not_nag():
    s = _fake_self([{"type": "account", "account": {"name": "Acme"}}])
    assert check(s, FakeAPI(["Acme"])) == "ok"
    assert s._redirected is None


def test_empty_destination_does_not_nag():
    s = _fake_self([{"type": "account", "account": {"name": "Acme"}}])
    assert check(s, FakeAPI([])) == "ok"


def test_empty_destination_is_flagged_for_the_confirmation():
    s = _fake_self([{"type": "account", "account": {"name": "Acme"}}])
    check(s, FakeAPI([]))
    assert s._dest_empty is True
    check(s, FakeAPI(["Acme"]))
    assert s._dest_empty is False


def test_global_only_backup_does_not_nag():
    s = _fake_self([{"type": "global"}])
    assert check(s, FakeAPI(["Acme"])) == "ok"


def test_mismatch_continue(monkeypatch):
    monkeypatch.setattr(pages.messagebox, "askyesnocancel",
                        lambda *a, **k: False)
    s = _fake_self([{"type": "account", "account": {"name": "Acme"}}])
    assert check(s, FakeAPI(["Other"])) == "ok"
    assert s._redirected is None and s._compared is None


def test_mismatch_yes_opens_the_comparison(monkeypatch):
    monkeypatch.setattr(pages.messagebox, "askyesnocancel",
                        lambda *a, **k: True)
    s = _fake_self([{"type": "account", "account": {"name": "Acme"}}])
    api = FakeAPI(["Other"])
    assert check(s, api) == "abort"
    # the same console: the comparison doesn't ask for the direction again
    assert s._compared is api


def test_mismatch_yes_with_several_destination_accounts(monkeypatch):
    monkeypatch.setattr(pages.messagebox, "askyesnocancel",
                        lambda *a, **k: True)
    s = _fake_self([{"type": "account", "account": {"name": "Acme"}}])
    api = FakeAPI(["X", "Y"])
    assert check(s, api) == "abort"
    assert s._compared is api


def test_mismatch_cancel(monkeypatch):
    monkeypatch.setattr(pages.messagebox, "askyesnocancel",
                        lambda *a, **k: None)
    s = _fake_self([{"type": "account", "account": {"name": "Acme"}}])
    assert check(s, FakeAPI(["Other"])) == "abort"
    assert s._redirected is None and s._compared is None


def test_site_node_keys_off_account_name(monkeypatch):
    # A site node carries account.name too; a matching account means no nag.
    monkeypatch.setattr(pages.messagebox, "askyesnocancel",
                        lambda *a, **k: False)
    s = _fake_self([{"type": "site", "account": {"name": "Acme"},
                     "site": {"name": "HQ"}}])
    assert check(s, FakeAPI(["Acme"])) == "ok"
