import json
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_migrator as am
import pages
from pages import RestorePage

UI_DEFAULTS = {"global": False, "accounts": True, "sites": True,
               "groups": True}


def _backup():
    nodes = []
    for acct, sites in (("Acme", {"HQ": ["Servers", "Default Group"],
                                  "Branch": ["Laptops"]}),
                        ("Beta", {"Plant": ["Default Group"]}),
                        ("Gamma", {"Lab": []})):
        nodes.append({"type": "account", "path": f"{acct}/",
                      "account": {"name": acct}, "data": {}})
        for site, groups in sites.items():
            nodes.append({"type": "site", "path": f"{acct}/{site}",
                          "site": {"name": site}, "data": {}})
            nodes += [{"type": "group", "path": f"{acct}/{site}/{g}",
                       "group": {"name": g}, "data": {}} for g in groups]
    nodes[0]["backupMetadata"] = {"url": "https://src.sentinelone.net"}
    return nodes


def _paths(backup, scope):
    return [backup[i]["path"] for i in scope["indices"]]


# ── several names in the Account and Group fields ──────────────────────

def test_several_accounts_restore_each_of_them_and_no_other():
    backup = _backup()
    scope = pages._restore_scope(backup, UI_DEFAULTS,
                                 {"account": "Acme, Gamma"})
    assert _paths(backup, scope) == [
        "Acme/", "Acme/HQ", "Acme/HQ/Servers", "Acme/HQ/Default Group",
        "Acme/Branch", "Acme/Branch/Laptops", "Gamma/", "Gamma/Lab"]
    assert scope["accounts"] == ["Acme", "Gamma"]


def test_several_groups_restore_only_those_with_their_parents():
    backup = _backup()
    scope = pages._restore_scope(backup, UI_DEFAULTS,
                                 {"group": "Servers, Laptops"})
    assert _paths(backup, scope) == [
        "Acme/", "Acme/HQ", "Acme/HQ/Servers", "Acme/Branch",
        "Acme/Branch/Laptops"]


def test_every_account_and_group_that_matches_nothing_is_named():
    backup = _backup()
    scope = pages._restore_scope(backup, UI_DEFAULTS,
                                 {"account": "Acme, Nobody, Noone"})
    msg = pages._restore_scope_problem(backup, scope)
    assert "'Nobody'" in msg and "'Noone'" in msg and "Choose…" in msg
    scope = pages._restore_scope(backup, UI_DEFAULTS,
                                 {"group": "Servers, Nothing"})
    msg = pages._restore_scope_problem(backup, scope)
    assert "'Nothing'" in msg and "Choose…" in msg


def test_an_account_name_with_a_comma_works_typed_or_chosen():
    backup = [{"type": "account", "path": f"{name}/",
               "account": {"name": name}} for name in ("Acme, Inc.", "Beta")]
    typed = pages._restore_scope(backup, UI_DEFAULTS, {"account": "Acme, Inc."})
    assert typed["accounts"] == ["Acme, Inc."]
    chosen = pages._restore_scope(backup, UI_DEFAULTS, {
        "account": pages._join_scope_names(["Acme, Inc.", "Beta"])})
    assert chosen["accounts"] == ["Acme, Inc.", "Beta"]


def test_the_site_list_follows_several_accounts():
    backup = _backup()
    assert [s["name"] for s in pages._backup_sites(backup, "Acme, Beta")] == [
        "HQ", "Branch", "Plant"]
    assert [s["name"] for s in pages._backup_sites(backup, "Beta")] == [
        "Plant"]


def test_the_account_list_comes_from_the_backup_with_counts():
    assert pages._backup_accounts(_backup()) == [
        {"name": "Acme", "sites": 2, "groups": 3},
        {"name": "Beta", "sites": 1, "groups": 1},
        {"name": "Gamma", "sites": 1, "groups": 0}]


def test_the_group_list_follows_the_account_and_site_fields():
    backup = _backup()
    assert pages._backup_groups(backup, "Acme") == [
        {"name": "Servers", "where": "HQ"},
        {"name": "Default Group", "where": "HQ"},
        {"name": "Laptops", "where": "Branch"}]
    assert pages._backup_groups(backup, "", "HQ, Plant") == [
        {"name": "Servers", "where": "Acme / HQ"},
        {"name": "Default Group",
         "where": "in 2 sites: Acme / HQ, Beta / Plant"}]


def test_a_field_that_matches_nothing_does_not_empty_the_group_list():
    names = [g["name"] for g in pages._backup_groups(_backup(), "Nobody")]
    assert names == ["Servers", "Default Group", "Laptops"]


class _Field:
    def __init__(self, text=""):
        self.text = text

    def get(self):
        return self.text

    def delete(self, *_a):
        self.text = ""

    def insert(self, _index, value):
        self.text = value


def test_renames_follow_a_name_inside_an_account_or_group_list():
    page = types.SimpleNamespace(restore_acct=_Field("Acme, Beta"),
                                 restore_site=_Field(""),
                                 restore_group=_Field("Servers, Kiosks"))
    RestorePage._follow_renames(page, [
        {"kind": "account", "from": "Acme", "to": "ACME"},
        {"kind": "group", "from": "ACME/HQ/Servers",
         "to": "ACME/HQ/Server Group"},
        {"kind": "group", "from": "ACME/HQ/Laptops",
         "to": "ACME/HQ/Notebooks"}])
    assert page.restore_acct.text == "ACME, Beta"
    assert page.restore_group.text == "Server Group, Kiosks"


def test_the_destination_snapshot_takes_several_accounts_and_groups():
    class API:
        def get_accounts(self):
            return [{"id": f"A{i}", "name": n}
                    for i, n in enumerate(("Acme", "Beta", "Gamma"))]

        def get_sites(self, params=None):
            return [{"id": f"{params['accountIds']}-S", "name": "HQ"}]

        def get_groups(self, params=None):
            return [{"id": f"{params['siteIds']}-{n}", "name": n}
                    for n in ("Servers", "Kiosks", "Laptops")]

    out = pages._enumerate_tree(
        API(), {"account": "Acme, Gamma", "group": "Servers, Laptops"},
        {"accounts": True, "sites": True, "groups": True})
    assert {n["account_name"] for n in out} == {"Acme", "Gamma"}
    assert sorted({n["name"] for n in out if n["type"] == "group"}) == [
        "Laptops", "Servers"]


# ── the Restore screen ─────────────────────────────────────────────────

def _run_inline(_widget, fn, done=None, err=None):
    try:
        result = fn()
    except Exception as exc:
        if err:
            err(exc)
        return
    if done:
        done(result)


@pytest.fixture
def screen(monkeypatch):
    try:
        root = am.ctk.CTk()
    except Exception as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()
    monkeypatch.setattr(pages, "run_async", _run_inline)
    app = types.SimpleNamespace(
        settings={}, pages={}, source_api=None, dest_api=None,
        cfg=types.SimpleNamespace(get_by_role=lambda role: None),
        set_active_console=lambda *a: None, set_busy=lambda *a, **kw: None,
        set_status=lambda *a: None, log_audit=lambda *a, **kw: None,
        cli_log=lambda *a, **kw: None)
    page = RestorePage(root, app)
    page.pack(fill="both", expand=True)
    root.update_idletasks()
    yield page
    root.destroy()


def _load(page, tmp_path):
    path = tmp_path / "s1-backup-x.json"
    path.write_text(json.dumps(_backup()))
    page._load_file(str(path))
    page.update_idletasks()


def _fake_dialog(monkeypatch, pick):
    opened = []

    class Dialog:
        def __init__(self, master, title, fetch, chosen=(), **kw):
            self.rows = list(fetch("", 51))
            opened.append(dict(kw, title=title, chosen=list(chosen),
                               rows=self.rows))

        def ask(self):
            if pick is None:
                return None
            return [key for key, name, _d in self.rows if name in pick]

    monkeypatch.setattr(am, "_ChoiceDialog", Dialog)
    return opened


def test_every_restore_field_has_a_choose_button(screen):
    assert set(screen._choose_btns) == {"account", "site", "group"}
    assert screen._choose_btns["account"].cget("command") == \
        screen._choose_restore_accounts
    assert screen._choose_btns["group"].cget("command") == \
        screen._choose_restore_groups
    assert screen._choose_btn is screen._choose_btns["site"]
    for btn in screen._choose_btns.values():
        assert btn.cget("text") == "Choose…"


def test_choosing_accounts_narrows_the_restore(screen, tmp_path, monkeypatch):
    _load(screen, tmp_path)
    opened = _fake_dialog(monkeypatch, pick={"Beta", "Gamma"})
    screen._choose_restore_accounts()
    assert screen.restore_acct.get() == "Beta, Gamma"
    assert [r[1] for r in opened[0]["rows"]] == ["Acme", "Beta", "Gamma"]
    assert opened[0]["rows"][0][2] == "2 site(s) · 3 group(s)"
    assert opened[0]["source"] == "this backup"
    assert "Restore 5 nodes" in screen._start_btn.cget("text")


def test_choosing_groups_follows_the_site_field(screen, tmp_path, monkeypatch):
    _load(screen, tmp_path)
    screen.restore_site.insert(0, "HQ, Branch")
    opened = _fake_dialog(monkeypatch, pick={"Laptops", "Servers"})
    screen._choose_restore_groups()
    assert [r[1] for r in opened[0]["rows"]] == [
        "Servers", "Default Group", "Laptops"]
    assert screen.restore_group.get() == "Servers, Laptops"
    assert "Restore 5 nodes" in screen._start_btn.cget("text")


def test_the_choosers_pre_tick_what_the_field_names(screen, tmp_path,
                                                    monkeypatch):
    _load(screen, tmp_path)
    screen.restore_acct.insert(0, "acme")
    screen.restore_group.insert(0, "servers")
    opened = _fake_dialog(monkeypatch, pick=None)
    screen._choose_restore_accounts()
    screen._choose_restore_groups()
    assert opened[0]["chosen"] == ["Acme"]
    assert opened[1]["chosen"] == ["Servers"]
    assert screen.restore_acct.get() == "acme"
    assert screen.restore_group.get() == "servers"


def test_the_site_chooser_still_writes_in_backup_order(screen, tmp_path,
                                                       monkeypatch):
    _load(screen, tmp_path)
    _fake_dialog(monkeypatch, pick={"Plant", "HQ"})
    screen._choose_restore_sites()
    assert screen.restore_site.get() == "HQ, Plant"


def test_choosers_ask_for_a_backup_first(screen, monkeypatch):
    told = []
    monkeypatch.setattr(pages.messagebox, "showinfo",
                        lambda title, _msg, **kw: told.append(title))
    opened = _fake_dialog(monkeypatch, pick=set())
    screen._choose_restore_accounts()
    screen._choose_restore_sites()
    screen._choose_restore_groups()
    assert told == ["No backup loaded"] * 3 and opened == []
