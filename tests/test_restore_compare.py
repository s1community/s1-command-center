"""Restore: compare the backup with the destination, rename to match.

`RestoreComparison` decides every account, site and group the way the
restore's exact-name resolver will, and `rename_in_backup` makes the same
edit Rename in the backup makes. The window and the Restore screen are
driven with a fake console that fails on anything but a read.
"""
import copy
import json
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pages  # noqa: E402
import restore_compare as rc  # noqa: E402
from pages import RestorePage  # noqa: E402


def acct(name):
    return {"type": "account", "path": f"{name}/", "account": {"name": name},
            "data": {}}


def site(a, s, default=False, data=None):
    return {"type": "site", "path": f"{a}/{s}", "account": {"name": a},
            "site": {"name": s, "isDefault": default}, "data": data or {}}


def group(a, s, g):
    return {"type": "group", "path": f"{a}/{s}/{g}", "account": {"name": a},
            "site": {"name": s}, "group": {"name": g}, "data": {}}


BACKUP = [
    {"type": "global", "path": "/", "data": {}},
    acct("Acme"),
    site("Acme", "HQ", default=True,
         data={"restrictions": [{"value": "a"}, {"value": "b"}]}),
    group("Acme", "HQ", "Servers"),
    group("Acme", "HQ", "Laptops"),
    site("Acme", "Branch Office"),
    group("Acme", "Branch Office", "Kiosks"),
]
A, HQ, BR = ("Acme",), ("Acme", "HQ"), ("Acme", "Branch Office")
SRV, LAP = ("Acme", "HQ", "Servers"), ("Acme", "HQ", "Laptops")
KIO = ("Acme", "Branch Office", "Kiosks")


def dest(accounts=None, held=None):
    """{account: {site: [groups]}} — or {account: None} for an account whose
    sites nobody has read. Each account's first site is its default."""
    out = {"accounts": [], "held": dict(held or {}), "sites": {}}
    for i, (name, sites) in enumerate((accounts or {}).items()):
        aid = f"a{i}"
        out["accounts"].append({"id": aid, "name": name})
        if sites is not None:
            out["sites"][aid] = [
                {"id": f"{aid}s{j}", "name": s, "isDefault": j == 0,
                 "groups": [{"id": f"{aid}s{j}g{k}", "name": g}
                            for k, g in enumerate(gs)]}
                for j, (s, gs) in enumerate(sites.items())]
    return out


def compare(backup=None, indices=None, d=None, **kw):
    backup = BACKUP if backup is None else backup
    idx = range(len(backup)) if indices is None else indices
    return rc.RestoreComparison(backup, idx, d or dest(),
                                items=pages._node_item_count, **kw)


# ── what the restore does with each scope ──────────────────────────────

def test_exact_names_are_restored_into_what_is_there():
    cmp = compare(d=dest({"Acme": {"HQ": ["Servers", "Laptops"],
                                   "Branch Office": ["Kiosks"]}}))
    assert {cmp.state(k) for k in cmp.nodes} == {"same"}
    assert cmp.dest_text(SRV) == "✓ exists"
    assert "restores the backup's settings into it" in cmp.reason(HQ)
    assert cmp.items_text(HQ) == "2" and cmp.items_text(SRV) == "0"
    assert rc.describe(cmp, "DESTINATION") == (
        "Compared with DESTINATION: 6 exist · 0 will be created.", "ok")


def test_what_is_missing_is_created_from_the_backup():
    cmp = compare(d=dest({"Acme": {"HQ": ["Default Group"]}}))
    assert cmp.state(A) == cmp.state(HQ) == "same"
    assert cmp.state(SRV) == "new" and cmp.state(BR) == "new"
    assert "creates it from the backup file" in cmp.reason(SRV)
    assert cmp.state(KIO) == "create"
    assert "created inside it from the backup file" in cmp.reason(KIO)
    assert cmp.dest_text(KIO) == "+ will be created"
    assert cmp.created() == {"account": 0, "site": 1, "group": 3}
    line, tone = rc.describe(cmp, "DESTINATION")
    assert line == "Compared with DESTINATION: 2 exist · 4 will be created."


def test_a_new_account_creates_everything_inside_it():
    cmp = compare(d=dest({"Other": {"Default site": []}}))
    assert cmp.state(A) == "new"
    assert {cmp.state(k) for k in (HQ, SRV, LAP, BR, KIO)} == {"create"}
    assert "default site of its own" in cmp.reason(HQ)
    assert cmp.nothing_there and not cmp.dest_empty
    line, tone = rc.describe(cmp, "DESTINATION")
    assert line.startswith("Nothing in this restore is on the DESTINATION "
                           "console yet — it will create all of it from the "
                           "backup file")
    assert line.endswith(": 1 account, 2 sites, 3 groups.") and tone == "info"


def test_an_empty_destination_restores_everything_from_the_backup():
    cmp = compare(d=dest({}))
    assert cmp.dest_empty
    assert {cmp.state(k) for k in cmp.nodes} == {"create"}
    assert "has no accounts yet" in cmp.reason(A)
    assert cmp.candidates(A) == []
    assert rc.describe(cmp, "DESTINATION") == (
        "The DESTINATION console has no accounts yet — this restore will "
        "create everything from the backup file: 1 account, 2 sites, "
        "3 groups.", "info")


def test_another_case_is_a_near_match_and_a_rename_fixes_it():
    cmp = compare(d=dest({"ACME": {"HQ": ["Servers", "Laptops"]}}))
    assert cmp.state(A) == "near"
    assert cmp.dest_text(A) == "≈ “ACME” · other case"
    assert "would try to create “Acme” beside it" in cmp.reason(A)
    assert cmp.state(HQ) == "create"          # as it stands: a new account
    assert cmp.choose(A, "acme")              # typed: the real name is used
    assert cmp.choices == {A: "ACME"} and not cmp.typed(A)
    assert cmp.state(A) == "chosen" and cmp.dest_text(A) == "→ “ACME”"
    assert cmp.state(HQ) == cmp.state(SRV) == "same"
    assert cmp.state(BR) == "new"
    assert cmp.renames() == [{"kind": "account", "path": ["Acme"],
                              "new": "ACME"}]


def test_an_inactive_account_holding_the_name_skips_everything_under_it():
    cmp = compare(d=dest({"Other": {}}, held={"Acme": "expired"}))
    assert cmp.state(A) == "blocked"
    assert cmp.dest_text(A) == "✕ name held (expired)"
    assert "it is expired" in cmp.reason(A)
    assert cmp.state(HQ) == cmp.state(SRV) == "blocked"
    assert "won't be on the destination" in cmp.reason(HQ)
    assert cmp.fix_at(SRV) == A
    assert cmp.can_rename(A) and not cmp.can_rename(HQ)
    assert not cmp.choose(HQ, "Elsewhere", allow_unknown=True)
    assert cmp.choose(A, "Other")
    assert cmp.state(HQ) == "create"          # "Other" has no sites yet
    assert "has no sites yet" in cmp.reason(HQ)


def test_scopes_shown_only_for_context_are_not_created():
    idx = [i for i, n in enumerate(BACKUP) if n["type"] in ("site", "group")]
    cmp = compare(indices=idx, d=dest({"Other": {}}))
    assert cmp.state(A) == "blocked"
    assert "Accounts isn't ticked in step 2" in cmp.reason(A)
    assert cmp.state(HQ) == cmp.state(KIO) == "blocked"
    assert cmp.items_text(A) == "—"
    cmp = compare(indices=idx, d=dest({"Acme": {"HQ": ["Servers"]}}))
    assert cmp.state(A) == "same" and "isn't restored itself" in cmp.reason(A)
    assert cmp.state(HQ) == "same" and cmp.state(LAP) == "new"


def test_a_backup_without_account_records_says_so():
    backup = [site("Acme", "HQ"), group("Acme", "HQ", "Servers")]
    cmp = compare(backup=backup, d=dest({"Other": {}}))
    assert cmp.state(A) == "blocked"
    assert "holds no account record" in cmp.reason(A)


def test_candidates_show_what_already_restores_into_each():
    cmp = compare(d=dest({"Acme": {"HQ": ["Servers", "Laptops"],
                                   "Branch": ["Kiosks"]}}))
    cands = cmp.candidates(BR)
    assert [c["name"] for c in cands] == ["Branch", "HQ"]
    assert cands[0]["taken_by"] == "" and cands[1]["taken_by"] == "HQ"
    assert not cmp.choose(BR, "HQ")           # two backup sites in one
    assert cmp.check(BR, "hq") == ("taken", "HQ")
    assert cmp.choose(BR, "Branch")
    assert cmp.state(BR) == "chosen" and cmp.state(KIO) == "same"
    assert "Renamed to “Branch” in the backup" in cmp.reason(BR)
    assert cmp.candidates(HQ)[0]["chosen_for"] == ""
    assert {c["name"]: c["chosen_for"] for c in cmp.candidates(HQ)} == {
        "HQ": "", "Branch": "Branch Office"}


def test_a_typed_name_is_created_under_the_new_name():
    cmp = compare(d=dest({"Acme": {"Main": []}}))
    assert not cmp.choose(BR, "Remote")       # not on the destination
    assert cmp.check(BR, "Remote") == ("unknown", "")
    assert cmp.choose(BR, "  Remote   Office ", allow_unknown=True)
    assert cmp.choices[BR] == "Remote Office" and cmp.typed(BR)
    assert cmp.dest_text(BR) == "→ “Remote Office” · new name"
    assert cmp.state(KIO) == "create"
    assert cmp.check(BR, "Branch Office") == ("self", "")
    assert cmp.check(BR, "a/b")[0] == "bad"
    assert cmp.check(BR, "hq") == ("taken", "HQ")   # the backup's own HQ
    assert not cmp.choose(BR, "HQ", allow_unknown=True)


def test_scopes_outside_the_restore_still_hold_their_names():
    scope = pages._restore_scope(BACKUP, None, {"site": "Branch Office"})
    cmp = compare(indices=scope["indices"],
                  d=dest({"Acme": {"HQ": [], "Main": []}}))
    assert HQ not in cmp.nodes and BR in cmp.nodes
    cands = {c["name"]: c for c in cmp.candidates(BR)}
    assert cands["HQ"]["taken_by"] == "HQ" and not cands["HQ"]["scoped"]
    assert not cmp.choose(BR, "HQ")
    assert cmp.choose(BR, "Main")


def test_renaming_a_parent_resets_the_renames_under_it():
    cmp = compare(d=dest({"ACME": {"HQ": [], "Branch": []}, "Acme2": {}}))
    assert cmp.choose(A, "ACME") and cmp.choose(BR, "Branch")
    assert cmp.choose(A, "Acme2")
    assert cmp.choices == {A: "Acme2"}
    cmp.unchoose(A)
    assert cmp.choices == {} and cmp.state(A) == "near"


def test_the_ticket_account_id_steers_accounts_and_sites_not_groups():
    d = dest({"Customer Prod": {"HQ": ["Servers"]}})
    cmp = compare(d=d, account_id="a0")
    assert cmp.state(A) == "near"
    assert cmp.dest_text(A) == "≈ “Customer Prod” · by ticket ID"
    assert "ticket's account ID (a0)" in cmp.reason(A)
    assert cmp.state(HQ) == "same"
    assert cmp.state(SRV) == "blocked" and cmp.fix_at(SRV) == A
    assert "Groups look their account up by name" in cmp.reason(SRV)
    assert not cmp.can_rename(SRV)
    assert [c["name"] for c in cmp.candidates(A)] == ["Customer Prod"]
    assert cmp.choose(A, "Customer Prod")
    assert cmp.state(A) == "chosen" and cmp.state(SRV) == "same"
    missing = compare(d=d, account_id="nope")
    assert missing.id_missing and missing.state(A) == "new"


def test_a_rename_into_an_unread_account_waits_for_its_read():
    cmp = compare(d=dest({"Elsewhere": None}))
    assert cmp.state(A) == "new" and cmp.unread() == []
    assert cmp.choose(A, "Elsewhere")
    assert cmp.state(HQ) == "waiting" and cmp.dest_text(HQ) == "· reading…"
    assert cmp.unread() == [{"id": "a0", "name": "Elsewhere"}]
    assert "Reading what the destination account “Elsewhere” holds" in \
        cmp.reason(HQ)
    cmp.add_account("a0", error="HTTP 403: forbidden")
    assert cmp.dest_text(HQ) == "· couldn't read"
    assert "HTTP 403: forbidden" in cmp.reason(HQ) and cmp.unread() == []
    cmp.add_account("a0", sites=[{"id": "s", "name": "HQ", "isDefault": True,
                                  "groups": [{"id": "g", "name": "Servers"}]}])
    assert cmp.state(HQ) == cmp.state(SRV) == "same"
    assert cmp.state(LAP) == "new"


def test_filters_and_search():
    cmp = compare(d=dest({"Acme": {"HQ": ["Servers"], "Main": []}}))
    assert [k for k, _d in cmp.visible("fix")] == [A, HQ, LAP, BR]
    assert [k for k, _d in cmp.visible("all", "kiosk")] == [A, BR, KIO]
    assert [k for k, _d in cmp.visible("all", "", collapsed={HQ})] == [
        A, HQ, BR, KIO]
    assert cmp.choose(BR, "Main")
    assert [k for k, _d in cmp.visible("done")] == [A, BR]
    assert [k for k, _d in cmp.visible("all", "main")] == [A, BR, KIO]
    assert [d for _k, d in cmp.visible("all")] == [0, 1, 2, 2, 1, 2]


def test_the_default_site_question_is_explained_before_the_restore():
    cmp = compare(d=dest({"Acme": {"Default site": []}}))
    assert "restore it over “Default site”" in cmp.reason(HQ)
    assert "put it on “Default site” instead" in cmp.reason(BR)
    assert "Pick “Default site” here" in cmp.reason(BR)
    taken = compare(d=dest({"Acme": {"HQ": []}}))
    assert "Answer No there: “HQ” is where the backup site “HQ” restores." \
        in taken.reason(BR)
    assert "Pick “HQ”" not in taken.reason(BR)


# ── the renames, applied ───────────────────────────────────────────────

class _Entry:
    def __init__(self, text):
        self.text = text

    def get(self):
        return self.text


def _mangle(backup, source, target, monkeypatch):
    monkeypatch.setattr(pages, "cli_log", lambda *a, **k: None)
    fake = types.SimpleNamespace(
        backup_data=backup, mangle_src=_Entry(source),
        mangle_dst=_Entry(target),
        mangle_status=types.SimpleNamespace(configure=lambda **k: None),
        _update_scope_summary=lambda: None)
    RestorePage._mangle_rename(fake)
    return backup


@pytest.mark.parametrize("path,new,source,target", [
    (["Acme"], "ACME", "Acme", "ACME"),
    (["Acme", "Branch Office"], "Branch", "Acme/Branch Office",
     "Acme/Branch"),
    (["Acme", "HQ", "Servers"], "Servers 2", "Acme/HQ/Servers",
     "Acme/HQ/Servers 2"),
])
def test_a_rename_edits_the_backup_like_rename_in_the_backup(
        path, new, source, target, monkeypatch):
    ours = copy.deepcopy(BACKUP)
    kind = rc.KINDS[len(path) - 1]
    done = rc.rename_in_backup(ours, [{"kind": kind, "path": path,
                                       "new": new}])
    assert done[0]["from"] == source and done[0]["to"] == target
    assert ours == _mangle(copy.deepcopy(BACKUP), source, target, monkeypatch)


def test_renames_go_parents_first():
    backup = copy.deepcopy(BACKUP)
    done = rc.rename_in_backup(backup, [
        {"kind": "site", "path": ["Acme", "Branch Office"], "new": "Branch"},
        {"kind": "account", "path": ["Acme"], "new": "ACME"}])
    assert done == [
        {"kind": "account", "from": "Acme", "to": "ACME", "count": 6},
        {"kind": "site", "from": "ACME/Branch Office", "to": "ACME/Branch",
         "count": 2}]
    assert [n["path"] for n in backup] == [
        "/", "ACME/", "ACME/HQ", "ACME/HQ/Servers", "ACME/HQ/Laptops",
        "ACME/Branch", "ACME/Branch/Kiosks"]
    scope = pages._restore_scope(backup, None,
                                 {"account": "ACME", "site": "Branch"})
    assert scope["indices"] == [0, 1, 5, 6]
    assert pages._node_scope_names(backup[6]) == ("ACME", "Branch", "Kiosks")


def test_the_comparison_after_the_renames_is_all_matched():
    d = dest({"ACME": {"HQ": ["Servers", "Laptops"], "Branch": ["Kiosks"]}})
    cmp = compare(d=d)
    assert cmp.choose(A, "ACME") and cmp.choose(BR, "Branch")
    backup = copy.deepcopy(BACKUP)
    rc.rename_in_backup(backup, cmp.renames())
    again = compare(backup=backup, d=d)
    assert {again.state(k) for k in again.nodes} == {"same"}


# ── reading the destination ────────────────────────────────────────────

class FakeAPI:
    """A destination console that answers reads and refuses anything
    else — a comparison must never write."""

    base_url = "https://dst.example.net"

    def __init__(self, accounts=(), sites=None, groups=None, held=None):
        self._accounts = list(accounts)
        self._sites = sites or {}
        self._groups = groups or {}
        self._held = held or {}
        self.calls = []

    def get_accounts(self):
        self.calls.append(("accounts",))
        return list(self._accounts)

    def get_sites(self, params=None):
        self.calls.append(("sites", params["accountIds"]))
        return list(self._sites.get(str(params["accountIds"]), []))

    def get_groups(self, params=None):
        self.calls.append(("groups", str(params["siteIds"])))
        return list(self._groups.get(str(params["siteIds"]), []))

    def get_accounts_any_state(self, name=None):
        self.calls.append(("any", name))
        return list(self._held.get(name, []))

    def __getattr__(self, name):
        raise AssertionError(f"the comparison called {name}()")


def test_only_accounts_a_backup_account_can_land_in_are_read():
    api = FakeAPI(
        accounts=[{"id": 1, "name": "ACME"}, {"id": 2, "name": "Other"}],
        sites={"1": [{"id": 10, "name": "HQ", "isDefault": True},
                     {"id": 11, "name": "Old", "state": "expired"}]},
        groups={"10": [{"id": 100, "name": "Servers"}]},
        held={"Gone": [{"name": "Gone", "state": "deleted"}]})
    d = rc.read_destination(api, ["Acme", "Gone"])
    assert d["accounts"] == [{"id": "1", "name": "ACME"},
                             {"id": "2", "name": "Other"}]
    assert d["held"] == {"Gone": "deleted"}
    assert d["sites"] == {"1": [{"id": "10", "name": "HQ", "isDefault": True,
                                 "groups": [{"id": "100",
                                             "name": "Servers"}]}]}
    assert ("sites", "2") not in api.calls and ("groups", "11") not in api.calls


def test_the_ticket_account_is_read_whatever_its_name():
    api = FakeAPI(accounts=[{"id": 7, "name": "Customer Prod"}],
                  sites={"7": []})
    d = rc.read_destination(api, ["Acme"], account_id="7")
    assert list(d["sites"]) == ["7"]


def test_an_empty_destination_reads_no_sites():
    api = FakeAPI()
    d = rc.read_destination(api, ["Acme"])
    assert d == {"accounts": [], "held": {}, "sites": {}}
    assert api.calls == [("accounts",), ("any", "Acme")]


def test_the_restores_accounts_in_backup_order():
    assert rc.backup_accounts(BACKUP, range(len(BACKUP))) == ["Acme"]
    assert rc.backup_accounts(BACKUP, [0]) == []


# ── the window ─────────────────────────────────────────────────────────

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
def root():
    import customtkinter as ctk
    try:
        top = ctk.CTk()
    except Exception as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    top.withdraw()
    yield top
    top.destroy()


def _open(root, cmp, **kw):
    got = []
    dlg = rc.RestoreCompareDialog(root, cmp, got.append, **kw)
    dlg.update_idletasks()
    return dlg, got


def test_the_window_opens_on_what_needs_a_look(root):
    cmp = compare(d=dest({"ACME": {"HQ": ["Servers", "Laptops"],
                                   "Branch": ["Kiosks"]}}))
    dlg, got = _open(root, cmp)
    assert dlg._filter.get() == "Needs a look" and dlg._selected == A
    assert dlg._d_state.cget("text").startswith("≈")
    assert dlg._d_kind.cget("text") == "BACKUP ACCOUNT"
    assert dlg._apply_btn.cget("state") == "disabled"
    dlg._pick = next(c for c in dlg._cands if c["name"] == "ACME")
    dlg._use()
    assert cmp.choices == {A: "ACME"} and dlg._selected == BR
    assert dlg._apply_btn.cget("text") == "Rename 1 scope in the backup"
    assert "1 renamed" in dlg._counts.cget("text")
    dlg._apply()
    assert got == [[{"kind": "account", "path": ["Acme"], "new": "ACME"}]]


def test_an_empty_destination_says_the_backup_is_restored_as_is(root):
    dlg, _got = _open(root, compare(d=dest({})))
    text = dlg._intro_lbl.cget("text")
    assert text.startswith("The destination console has no accounts yet")
    assert "1 account, 2 sites, 3 groups" in text
    assert dlg._filter.get() == "All" and len(dlg.tree._records) == 6


def test_a_skipped_scope_points_at_what_to_fix(root):
    cmp = compare(d=dest({"Other": {}}, held={"Acme": "expired"}))
    dlg, _got = _open(root, cmp)
    dlg._select(SRV)
    assert not dlg._pick_box.winfo_manager()
    assert dlg._goto_btn.winfo_manager()
    assert dlg._goto_btn.cget("text") == "Show the account"
    dlg._goto_parent()
    assert dlg._selected == A and dlg._pick_box.winfo_manager()


def test_a_skipped_scope_with_nothing_to_pick_says_what_helps(root):
    held = compare(d=dest({}, held={"Acme": "expired"}))
    dlg, _got = _open(root, held)
    dlg._select(A)
    assert dlg._c_title.cget("text") == "Rename it before it is created"
    assert dlg._c_note.cget("text").startswith("Type a new name above")
    dlg.destroy()
    idx = [i for i, n in enumerate(BACKUP) if n["type"] in ("site", "group")]
    dlg, _got = _open(root, compare(indices=idx, d=dest({})))
    dlg._select(A)
    assert dlg._c_title.cget("text") == \
        "No destination account to restore it into"
    assert dlg._c_note.cget("text").endswith("tick Accounts in step 2.")


def test_a_typed_name_needs_its_own_button(root):
    cmp = compare(d=dest({"Acme": {"Main": []}}))
    dlg, _got = _open(root, cmp)
    dlg._select(BR)
    dlg._c_search.insert(0, "Remote")
    dlg._filter_candidates()
    assert dlg._typed_btn.winfo_manager()
    assert dlg._typed_btn.cget("text") == "Rename to “Remote”"
    assert "will create it under that name" in dlg._c_note.cget("text")
    dlg._use_typed()
    assert cmp.choices == {BR: "Remote"}


def test_a_rename_into_an_unread_account_reads_it(root, monkeypatch):
    monkeypatch.setattr(rc, "run_async", _run_inline)
    reads = []

    def loader(account):
        reads.append(account["name"])
        return [{"id": "s", "name": "HQ", "isDefault": True, "groups": []}]

    cmp = compare(d=dest({"Elsewhere": None}))
    dlg, _got = _open(root, cmp, loader=loader)
    dlg._select(A)
    dlg._pick = dlg._cands[0]
    dlg._use()
    assert reads == ["Elsewhere"]
    assert cmp.state(HQ) == "same" and cmp.state(BR) == "new"


# ── the Restore screen ─────────────────────────────────────────────────

@pytest.fixture
def screen(monkeypatch):
    import customtkinter as ctk
    try:
        top = ctk.CTk()
    except Exception as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    top.withdraw()
    monkeypatch.setattr(pages, "run_async", _run_inline)
    monkeypatch.setattr(pages, "cli_log", lambda *a, **k: None)
    app = types.SimpleNamespace(
        settings={}, pages={}, source_api=None, dest_api=None,
        cfg=types.SimpleNamespace(get_by_role=lambda role: None),
        set_active_console=lambda *a: None, set_busy=lambda *a, **kw: None,
        set_status=lambda *a: None, log_audit=lambda *a, **kw: None,
        cli_log=lambda *a, **kw: None)
    page = RestorePage(top, app)
    page.pack(fill="both", expand=True)
    top.update_idletasks()
    yield page
    top.destroy()


@pytest.fixture
def opened(monkeypatch):
    seen = []
    monkeypatch.setattr(
        rc, "RestoreCompareDialog",
        lambda parent, cmp, on_done, **kw: seen.append((cmp, on_done, kw)))
    return seen


def _load(page, tmp_path, payload=None):
    path = tmp_path / "s1-backup-x.json"
    path.write_text(json.dumps(BACKUP if payload is None else payload))
    page._load_file(str(path))
    page.update_idletasks()


def _console():
    return FakeAPI(accounts=[{"id": 1, "name": "Acme"}],
                   sites={"1": [{"id": 10, "name": "HQ", "isDefault": True}]},
                   groups={"10": [{"id": 100, "name": "Servers"}]})


def test_compare_reads_the_destination_and_opens_the_window(screen, tmp_path,
                                                            opened):
    assert not screen._compare_row.winfo_manager()
    _load(screen, tmp_path)
    assert screen._compare_btn.cget("state") == "normal"
    screen.app.dest_api = _console()
    screen._compare_with_destination()
    cmp, on_done, kw = opened[0]
    assert kw["console"] == "DESTINATION" and on_done == screen._after_compare
    assert cmp.state(SRV) == "same" and cmp.state(LAP) == "new"
    assert screen._compare_lbl.cget("text") == (
        "Compared with DESTINATION: 3 exist · 3 will be created.")
    assert screen._compare_btn.cget("state") == "normal"


def test_applied_renames_edit_the_backup_and_keep_the_fields(screen, tmp_path):
    _load(screen, tmp_path)
    screen.restore_site.insert(0, "HQ, Branch Office")
    screen._update_scope_summary()
    screen._after_compare([{"kind": "site", "path": ["Acme", "Branch Office"],
                            "new": "Branch"}])
    assert screen.restore_site.get() == "HQ, Branch"
    assert screen.backup_data[5]["path"] == "Acme/Branch"
    assert screen.backup_data[5]["site"]["name"] == "Branch"
    assert screen.backup_data[6]["path"] == "Acme/Branch/Kiosks"
    assert screen._renames[-1]["from"] == "Acme/Branch Office"
    assert screen._renames[-1]["to"] == "Acme/Branch"
    assert screen._compare_lbl.cget("text").startswith(
        "✓  Renamed 1 scope in the backup (2 nodes)")
    assert screen._start_btn.cget("state") == "normal"
    assert "Restore 6 nodes" in screen._start_btn.cget("text")


def test_an_empty_destination_is_announced_on_the_screen(screen, tmp_path,
                                                        opened):
    _load(screen, tmp_path)
    screen.app.dest_api = FakeAPI()
    screen._compare_with_destination()
    assert screen._compare_lbl.cget("text").startswith(
        "The DESTINATION console has no accounts yet — this restore will "
        "create everything from the backup file")
    assert opened and opened[0][0].dest_empty


def test_a_failed_read_is_not_mistaken_for_an_empty_destination(
        screen, tmp_path, opened):
    class Broken(FakeAPI):
        def get_accounts(self):
            raise RuntimeError("HTTP 401: token expired")

    _load(screen, tmp_path)
    screen.app.dest_api = Broken()
    screen._compare_with_destination()
    text = screen._compare_lbl.cget("text")
    assert text.startswith("✕  Couldn't read the DESTINATION console")
    assert "token expired" in text and "no accounts" not in text
    assert not opened and screen._compare_btn.cget("state") == "normal"


def test_a_changed_scope_marks_the_comparison_stale(screen, tmp_path, opened):
    _load(screen, tmp_path)
    screen.app.dest_api = _console()
    screen._compare_with_destination()
    screen.restore_site.insert(0, "HQ")
    screen._update_scope_summary()
    assert "scope changed since the last comparison" in \
        screen._compare_lbl.cget("text")


def test_a_global_only_restore_has_nothing_to_compare(screen, tmp_path,
                                                      opened):
    _load(screen, tmp_path)
    for level in ("accounts", "sites", "groups"):
        screen.restore_level_vars[level].set(False)
    screen.restore_level_vars["global"].set(True)
    screen._update_scope_summary()
    api = screen.app.dest_api = FakeAPI()
    screen._compare_with_destination()
    assert screen._compare_lbl.cget("text").startswith(
        "Only global settings are in this restore")
    assert api.calls == [] and not opened


def test_a_new_backup_clears_the_last_comparison(screen, tmp_path, opened):
    _load(screen, tmp_path)
    screen.app.dest_api = _console()
    screen._compare_with_destination()
    _load(screen, tmp_path)
    assert screen._compare_lbl.cget("text") == ""
