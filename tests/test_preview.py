"""Tests for the dry-run preview's read-only destination resolver.

_resolve_dest_id_readonly must NEVER create scopes (unlike the restore-path
_resolve_dest_id) — it only matches existing destination scopes by name so the
preview can report 'this whole scope would be created' without side effects.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pages import RestorePage


class FakeAPI:
    base_url = "https://dst.example.net"

    def get_accounts(self):
        return [{"id": "A1", "name": "Acme"}]

    def get_sites(self, params=None):
        return [{"id": "S1", "name": "HQ"}]

    def get_groups(self, params=None):
        return [{"id": "G1", "name": "Servers"}]


# The method uses no instance state, so we can call it unbound with self=None.
resolve = RestorePage._resolve_dest_id_readonly


def test_global_always_resolves_empty():
    assert resolve(None, FakeAPI(), {"type": "global"}) == ("", True)


def test_account_found_and_missing():
    assert resolve(None, FakeAPI(),
                   {"type": "account", "account": {"name": "Acme"}}) == ("A1", True)
    assert resolve(None, FakeAPI(),
                   {"type": "account", "account": {"name": "Ghost"}}) == ("", False)


def test_site_found():
    node = {"type": "site", "account": {"name": "Acme"},
            "site": {"name": "HQ"}}
    assert resolve(None, FakeAPI(), node) == ("S1", True)


def test_site_missing_account_is_not_found():
    node = {"type": "site", "account": {"name": "Ghost"},
            "site": {"name": "HQ"}}
    assert resolve(None, FakeAPI(), node) == ("", False)


def test_group_found_and_missing():
    base = {"type": "group", "account": {"name": "Acme"},
            "site": {"name": "HQ"}}
    assert resolve(None, FakeAPI(), {**base, "group": {"name": "Servers"}}) \
        == ("G1", True)
    assert resolve(None, FakeAPI(), {**base, "group": {"name": "Nope"}}) \
        == ("", False)
