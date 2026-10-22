import inspect
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_migrator as am
import pages
from pages import BackupPage


class TreeAPI:
    base_url = "https://src.example"

    def __init__(self, tree):
        self.accounts, self.sites, self.groups, self.calls = [], [], [], []
        for a_i, (aname, sites) in enumerate(tree.items(), 1):
            aid = f"A{a_i}"
            self.accounts.append({"id": aid, "name": aname})
            for s_i, (sname, groups) in enumerate(sites.items(), 1):
                sid = f"{aid}S{s_i}"
                self.sites.append({"id": sid, "name": sname, "accountId": aid,
                                   "accountName": aname, "state": "active"})
                for g_i, gname in enumerate(groups, 1):
                    self.groups.append({"id": f"{sid}G{g_i}", "name": gname,
                                        "siteId": sid})

    @staticmethod
    def _ids(value):
        return str(value).split(",")

    def get_my_user(self):
        return {"email": "user@example.com"}

    def get_accounts(self):
        self.calls.append(("get_accounts",))
        return [dict(a) for a in self.accounts]

    def get_account_by_id(self, account_id):
        self.calls.append(("get_account_by_id", account_id))
        return next((dict(a) for a in self.accounts if a["id"] == account_id),
                    None)

    def get_sites(self, params=None):
        params = dict(params or {})
        self.calls.append(("get_sites", params))
        rows = self.sites
        if params.get("accountIds"):
            rows = [s for s in rows
                    if s["accountId"] in self._ids(params["accountIds"])]
        if params.get("siteIds"):
            rows = [s for s in rows if s["id"] in self._ids(params["siteIds"])]
        return [dict(s) for s in rows]

    def get_groups(self, params=None, limit=200, max_items=0):
        params = dict(params or {})
        self.calls.append(("get_groups", params, max_items))
        rows = self.groups
        if params.get("siteIds"):
            rows = [g for g in rows
                    if g["siteId"] in self._ids(params["siteIds"])]
        if params.get("accountIds"):
            owned = {s["id"] for s in self.sites
                     if s["accountId"] in self._ids(params["accountIds"])}
            rows = [g for g in rows if g["siteId"] in owned]
        if params.get("query"):
            rows = [g for g in rows
                    if params["query"].lower() in g["name"].lower()]
        rows = [dict(g) for g in rows]
        return rows[:max_items] if max_items else rows

    def search_accounts(self, query="", limit=50):
        self.calls.append(("search_accounts", query, limit))
        return [dict(a) for a in self.accounts
                if query.lower() in a["name"].lower()][:limit]

    def search_sites(self, query="", account_ids="", limit=50, states=""):
        self.calls.append(("search_sites", query, account_ids, limit, states))
        rows = self.sites
        if account_ids:
            rows = [s for s in rows if s["accountId"] in self._ids(account_ids)]
        if query:
            rows = [s for s in rows if query.lower() in s["name"].lower()]
        return [dict(s) for s in rows][:limit]


class _Table:
    def __getattr__(self, _name):
        return lambda *a, **kw: None


def _backup(monkeypatch, api, levels, account="", site="", group=""):
    logged = []
    page = types.SimpleNamespace(
        ptable=_Table(), progress=_Table(), _acct_id="", _cancelled=False,
        _operation_log=[], _last_results=[], after=lambda _d, fn: fn(),
        _read_node=lambda *a, **kw: {})
    monkeypatch.setattr(pages, "cli_log",
                        lambda msg, *a, **kw: logged.append(msg))
    lv = {"global": False, "accounts": "accounts" in levels,
          "sites": "sites" in levels, "groups": "groups" in levels}
    nodes = BackupPage._run_backup(
        page, api, lv, ["policy"],
        {"account": account, "site": site, "group": group})
    return [n["path"] for n in nodes], logged


# ── the backup reads what the fields name ──────────────────────────────

def test_the_account_field_takes_several_names(monkeypatch):
    api = TreeAPI({"Acme": {}, "Beta": {}, "Gamma": {}})
    paths, _ = _backup(monkeypatch, api, "accounts", account="Acme, Gamma")
    assert paths == ["Acme/", "Gamma/"]


def test_several_site_names_pick_exactly_those_sites(monkeypatch):
    api = TreeAPI({"TR": {"HighQ_Servers": [], "Servers": [],
                          "TR-Servers": []}})
    paths, _ = _backup(monkeypatch, api, "sites", site="Servers, TR-Servers")
    assert paths == ["TR/Servers", "TR/TR-Servers"]


def test_a_site_name_found_anywhere_matches_exactly_everywhere(monkeypatch):
    api = TreeAPI({"Acme": {"Servers": []}, "Beta": {"TR-Servers": []}})
    paths, _ = _backup(monkeypatch, api, "sites", site="Servers")
    assert paths == ["Acme/Servers"]


def test_a_group_name_does_not_pull_look_alikes_from_other_sites(monkeypatch):
    api = TreeAPI({"Acme": {"HQ": ["Servers", "Workstations"],
                            "Branch": ["Linux Servers"]}})
    paths, _ = _backup(monkeypatch, api, "groups", group="Servers")
    assert paths == ["Acme/HQ/Servers"]


def test_a_name_found_nowhere_still_matches_as_a_substring(monkeypatch):
    api = TreeAPI({"Acme": {"HQ": ["Servers", "Workstations"],
                            "Branch": ["Linux Servers"]}})
    paths, _ = _backup(monkeypatch, api, "groups", group="Serv")
    assert sorted(paths) == ["Acme/Branch/Linux Servers", "Acme/HQ/Servers"]


def test_names_that_match_nothing_are_reported(monkeypatch):
    api = TreeAPI({"Acme": {"HQ": ["Servers"]}, "Beta": {}})
    paths, logged = _backup(monkeypatch, api, "accounts sites groups",
                            account="Acme, Nobody", site="HQ, Nowhere",
                            group="Servers, Nothing")
    assert paths == ["Acme/", "Acme/HQ", "Acme/HQ/Servers"]
    for name in ("Nobody", "Nowhere", "Nothing"):
        assert any(name in line for line in logged), name


def test_the_backup_lists_each_scope_once(monkeypatch):
    api = TreeAPI({"Acme": {"HQ": ["Servers"], "Branch": ["Laptops"]},
                   "Beta": {"Plant": ["Kiosks"]}})
    _backup(monkeypatch, api, "accounts sites groups")
    kinds = [c[0] for c in api.calls]
    assert kinds.count("get_sites") == 2
    assert kinds.count("get_groups") == 3


def test_star_export_takes_several_names(monkeypatch):
    class StarAPI:
        def get_accounts(self):
            return [{"id": "A1", "name": "Acme"}, {"id": "A2", "name": "Beta"},
                    {"id": "A3", "name": "Gamma"}]

        def get_star_rules(self, scope):
            aid = scope["accountIds"][0]
            return [{"id": f"{aid}-{s}", "siteName": s}
                    for s in ("HQ", "Branch", "Lab")]

    monkeypatch.setattr(pages, "cli_log", lambda *a, **kw: None)
    rules = pages._collect_star_rules(StarAPI(), "Acme, Gamma", "HQ, Lab")
    assert sorted(r["id"] for r in rules) == ["A1-HQ", "A1-Lab",
                                              "A3-HQ", "A3-Lab"]


def test_every_reader_of_the_backup_fields_takes_several_names():
    for fn in (BackupPage._run_backup, pages._collect_star_rules):
        assert "_select_by_name(" not in inspect.getsource(fn), fn.__name__


def test_name_filter_blank_keeps_everything():
    ok, missing = pages._name_filter(["A", ""], "  ")
    assert ok("A") and ok("") and missing == []


def test_name_filter_judges_a_name_across_the_whole_level():
    ok, missing = pages._name_filter(
        ["Servers", "Linux Servers", "TR-Servers"], "servers")
    assert ok("Servers") and not ok("Linux Servers") and missing == []


def test_name_filter_falls_back_to_substring_and_reports_misses():
    ok, missing = pages._name_filter(["Servers", "Linux Servers"],
                                     "Serv, Nope")
    assert ok("Servers") and ok("Linux Servers") and missing == ["Nope"]


def test_a_comma_inside_a_real_name_needs_no_quotes():
    ok, _ = pages._name_filter(["Paris, France", "Rome"], "Paris, France")
    assert ok("Paris, France") and not ok("Rome")


# ── what each Choose… dialog lists ─────────────────────────────────────

def test_accounts_come_from_one_bounded_console_search():
    api = TreeAPI({"Acme": {}, "Beta": {}})
    fetch, _ = pages._scope_chooser(api, "account")
    rows = fetch("", 51)
    assert list(rows) == [("acme", "Acme", "id A1"), ("beta", "Beta", "id A2")]
    assert api.calls == [("search_accounts", "", 51)]
    assert rows.more is False


def test_a_full_account_page_says_there_is_more():
    api = TreeAPI({f"Tenant {i:02}": {} for i in range(60)})
    fetch, _ = pages._scope_chooser(api, "account")
    rows = fetch("", 51)
    assert len(rows) == 51 and rows.more is True


def test_the_site_list_follows_the_account_field():
    api = TreeAPI({"Acme": {"HQ": [], "Branch": []}, "Beta": {"Plant": []}})
    fetch, _ = pages._scope_chooser(api, "site", account="acme")
    rows = fetch("", 51)
    assert [r[1] for r in rows] == ["Branch", "HQ"]
    assert [c for c in api.calls if c[0] == "search_sites"] == [
        ("search_sites", "", "A1", 200, "active")]


def test_a_site_name_several_accounts_share_is_one_row_naming_them():
    api = TreeAPI({"Acme": {"Default site": []},
                   "Beta": {"Default site": []}})
    fetch, _ = pages._scope_chooser(api, "site")
    assert list(fetch("", 51)) == [
        ("default site", "Default site", "in 2 accounts: Acme, Beta")]


def test_an_account_field_that_matches_nothing_says_so():
    api = TreeAPI({"Acme": {"HQ": []}})
    fetch, _ = pages._scope_chooser(api, "site", account="Nope")
    with pytest.raises(ValueError, match="Account Name"):
        fetch("", 51)


def test_the_ticket_account_id_scopes_the_site_list():
    api = TreeAPI({"Acme": {"HQ": []}, "Beta": {"Plant": []}})
    fetch, _ = pages._scope_chooser(api, "site", acct_id="A2")
    assert [r[1] for r in fetch("", 51)] == ["Plant"]
    assert not [c for c in api.calls if c[0] == "search_accounts"]


def test_the_group_list_follows_the_site_field():
    api = TreeAPI({"Acme": {"HQ": ["Servers"], "Branch": ["Laptops"]},
                   "Beta": {"HQ": ["Kiosks"]}})
    fetch, _ = pages._scope_chooser(api, "group", site="HQ")
    assert list(fetch("", 51)) == [("kiosks", "Kiosks", "Beta / HQ"),
                                   ("servers", "Servers", "Acme / HQ")]
    reads = [c for c in api.calls if c[0] == "get_groups"]
    assert len(reads) == 1 and reads[0][2] == 200
    assert set(reads[0][1]["siteIds"].split(",")) == {"A1S1", "A2S1"}
    assert not [c for c in api.calls if c[0] == "get_sites"]


def test_a_site_field_that_matches_nothing_says_so():
    api = TreeAPI({"Acme": {"HQ": ["Servers"]}})
    fetch, _ = pages._scope_chooser(api, "group", site="Nowhere")
    with pytest.raises(ValueError, match="Site Name"):
        fetch("", 51)


def test_group_rows_name_their_sites_when_no_site_is_chosen():
    api = TreeAPI({"Acme": {"HQ": ["Servers"], "Branch": ["Default Group"]},
                   "Beta": {"Plant": ["Default Group"]}})
    fetch, _ = pages._scope_chooser(api, "group")
    assert list(fetch("", 51)) == [
        ("default group", "Default Group",
         "in 2 sites: Acme / Branch, Beta / Plant"),
        ("servers", "Servers", "Acme / HQ")]
    lookups = [c for c in api.calls if c[0] == "get_sites"]
    assert len(lookups) == 1 and "siteIds" in lookups[0][1]


def test_the_group_search_is_done_by_the_console():
    api = TreeAPI({"Acme": {"HQ": ["Servers", "Laptops"]}})
    fetch, _ = pages._scope_chooser(api, "group", account="Acme")
    assert list(fetch("serv", 51)) == [("servers", "Servers", "HQ")]
    read = [c for c in api.calls if c[0] == "get_groups"][-1]
    assert read[1]["query"] == "serv" and read[1]["accountIds"] == "A1"


def test_long_id_lists_go_in_batches():
    tree = {f"East {i:03}": {f"E{i:03}": []} for i in range(150)}
    tree.update({f"West {i:03}": {f"W{i:03}": []} for i in range(150)})
    api = TreeAPI(tree)
    fetch, _ = pages._scope_chooser(api, "site", account="East, West")
    fetch("", 51)
    batches = [c[2] for c in api.calls if c[0] == "search_sites"]
    assert len(batches) == 3
    assert all(len(b.split(",")) <= 100 for b in batches)
    assert sum(len(b.split(",")) for b in batches) == 300


def test_a_full_page_says_there_may_be_more_even_when_names_repeat():
    api = TreeAPI({f"Tenant {i:03}": {"Default site": []} for i in range(250)})
    fetch, _ = pages._scope_chooser(api, "site")
    rows = fetch("", 51)
    assert [r[1] for r in rows] == ["Default site"] and rows.more is True


def test_the_chooser_keeps_the_console_spelling():
    api = TreeAPI({"Acme": {"HQ": []}})
    fetch, spelling = pages._scope_chooser(api, "site")
    fetch("hq", 51)
    assert spelling["hq"] == "HQ"


def test_the_dialog_says_there_is_more_when_the_fetch_says_so(monkeypatch):
    try:
        root = am.ctk.CTk()
    except Exception as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()
    monkeypatch.setattr(am._ChoiceDialog, "_spawn",
                        lambda self, work, done, failed: done(work()))

    def fetch(query, limit):
        rows = pages._Choices([("default site", "Default site", "")])
        rows.more = True
        return rows

    dlg = am._ChoiceDialog(root, "Pick", fetch)
    dlg.withdraw()
    try:
        dlg._search_now()
        assert dlg._more is True
        assert dlg._status.cget("text").startswith("Showing the first 1.")
    finally:
        root.destroy()


# ── the Backup page ────────────────────────────────────────────────────

@pytest.fixture
def backup_page(monkeypatch):
    try:
        root = am.ctk.CTk()
    except Exception as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()
    monkeypatch.setattr(BackupPage, "_load_schedule", lambda self: None)
    monkeypatch.setattr(pages, "cli_log", lambda *a, **kw: None)
    app = types.SimpleNamespace(
        source_api=None, dest_api=None,
        profiles=types.SimpleNamespace(names=lambda: []),
        cfg=types.SimpleNamespace(get_by_role=lambda role: None),
        set_active_console=lambda *a: None, set_busy=lambda *a, **kw: None,
        cli_log=lambda *a, **kw: None)
    page = BackupPage(root, app)
    page.pack(fill="both", expand=True)
    root.update_idletasks()
    yield page
    root.destroy()


def _fake_dialog(monkeypatch, pick):
    opened = []

    class Dialog:
        def __init__(self, master, title, fetch, chosen=(), **kw):
            opened.append(dict(kw, title=title, chosen=list(chosen)))
            self.rows = list(fetch("", 51))

        def ask(self):
            if pick is None:
                return None
            return [key for key, name, _d in self.rows if name in pick]

    monkeypatch.setattr(am, "_ChoiceDialog", Dialog)
    return opened


def test_every_field_has_a_choose_button_that_hides_with_global(backup_page):
    for kind in ("account", "site", "group"):
        btn = backup_page._choose_btns[kind]
        assert btn.cget("text") == "Choose…"
        assert btn in backup_page._scope_widgets
        assert btn.winfo_manager() == "grid"
    backup_page.level_vars["global"].set(True)
    assert not any(b.winfo_manager()
                   for b in backup_page._choose_btns.values())


def test_choose_without_a_connection_explains_instead(backup_page,
                                                      monkeypatch):
    warned = []
    monkeypatch.setattr(pages.messagebox, "showwarning",
                        lambda _t, msg, **kw: warned.append(msg))
    opened = _fake_dialog(monkeypatch, pick=set())
    backup_page._choose_scope("account")
    assert opened == []
    assert "SOURCE" in warned[0] and "Connections" in warned[0]


def test_choose_writes_the_ticked_names_as_the_console_spells_them(
        backup_page, monkeypatch):
    backup_page.app.source_api = TreeAPI(
        {"Acme": {"HQ": ["Servers"], "Branch": []}, "Beta": {"Plant": []}})
    backup_page.acct_filter.insert(0, "acme")
    opened = _fake_dialog(monkeypatch, pick={"Acme"})
    backup_page._choose_scope("account")
    assert backup_page.acct_filter.get() == "Acme"
    assert opened[0]["chosen"] == ["acme"] and opened[0]["noun"] == "account"
    opened = _fake_dialog(monkeypatch, pick={"HQ", "Branch"})
    backup_page._choose_scope("site")
    assert backup_page.site_filter.get() == "Branch, HQ"
    assert opened[0]["source"] == "the source console"


def test_choose_reads_the_console_the_backup_reads(backup_page, monkeypatch):
    backup_page.app.source_api = TreeAPI({"Source Co": {}})
    backup_page.app.dest_api = TreeAPI({"Dest Co": {}})
    backup_page._console_var.set("DESTINATION")
    opened = _fake_dialog(monkeypatch, pick={"Dest Co"})
    backup_page._choose_scope("account")
    assert backup_page.acct_filter.get() == "Dest Co"
    assert opened[0]["source"] == "the destination console"


def test_choosing_other_accounts_drops_the_ticket_account_id(backup_page,
                                                             monkeypatch):
    backup_page.app.source_api = TreeAPI({"Acme": {}, "Beta": {}})
    backup_page.acct_filter.insert(0, "Acme")
    backup_page._acct_id = "A1"
    _fake_dialog(monkeypatch, pick={"Acme"})
    backup_page._choose_scope("account")
    assert backup_page._acct_id == "A1"
    _fake_dialog(monkeypatch, pick={"Beta"})
    backup_page._choose_scope("account")
    assert backup_page.acct_filter.get() == "Beta"
    assert backup_page._acct_id == ""


def test_cancel_leaves_the_field_alone_and_none_ticked_clears_it(
        backup_page, monkeypatch):
    backup_page.app.source_api = TreeAPI({"Acme": {"HQ": []}})
    backup_page.site_filter.insert(0, "HQ")
    _fake_dialog(monkeypatch, pick=None)
    backup_page._choose_scope("site")
    assert backup_page.site_filter.get() == "HQ"
    _fake_dialog(monkeypatch, pick=set())
    backup_page._choose_scope("site")
    assert backup_page.site_filter.get() == ""
