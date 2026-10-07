"""A restore asked for one site must touch that site and nothing else.

FAO (2026-10): Site = FAO-TEST, yet the run restored all of FAO-DEFAULT's
groups. The Site field was only ever compared with SITE nodes; a group was
checked against the Group field alone, so with Group blank every group of
every site went through. Auto Restore, Resume and "Create All" also threw
the fields away entirely, and group ranking re-ordered every site in the
backup.

These tests pin the scope rules on the pure helpers and then drive the
REAL RestorePage._run_restore (same harness technique as
test_restore_ledger.py) to prove nothing outside the scope is resolved,
listed, ranked or written.
"""
import inspect
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pages
from pages import RestorePage

ACCT = "FAO (Food & Agriculture Organization)"
SITES_AND_GROUPS = {"global": False, "accounts": False,
                    "sites": True, "groups": True}
SITES_ONLY = {"global": False, "accounts": False,
              "sites": True, "groups": False}
UI_DEFAULTS = {"global": False, "accounts": True,
               "sites": True, "groups": True}


def _fao_backup():
    """Account, then each site followed by its groups — backup order."""
    nodes = [{"type": "account", "path": f"{ACCT}/",
              "account": {"name": ACCT}, "data": {}}]
    for site, groups in (
            ("FAO-DEFAULT", ["Default Group", "Ultimate_targeted",
                             "Unmanaged"]),
            ("FAO-TEST", ["Default Group", "Servers"]),
            ("FAO-TEST-2", ["Default Group"])):
        nodes.append({"type": "site", "path": f"{ACCT}/{site}",
                      "site": {"name": site}, "data": {}})
        for grp in groups:
            nodes.append({"type": "group", "path": f"{ACCT}/{site}/{grp}",
                          "group": {"name": grp}, "data": {}})
    return nodes


def _two_accounts():
    """FAO plus a second account that a FAO restore must never touch."""
    return _fao_backup() + [
        {"type": "account", "path": "Other/", "account": {"name": "Other"},
         "data": {}},
        {"type": "site", "path": "Other/HQ", "site": {"name": "HQ"},
         "data": {}},
        {"type": "group", "path": "Other/HQ/Default Group",
         "group": {"name": "Default Group"}, "data": {}}]


FAO_TEST = [f"{ACCT}/FAO-TEST", f"{ACCT}/FAO-TEST/Default Group",
            f"{ACCT}/FAO-TEST/Servers"]
FAO_TEST_2 = [f"{ACCT}/FAO-TEST-2", f"{ACCT}/FAO-TEST-2/Default Group"]


def _paths(backup, indices):
    return [backup[i]["path"] for i in indices]


def _scope(filters, levels=SITES_AND_GROUPS, backup=None):
    backup = backup if backup is not None else _fao_backup()
    return backup, pages._restore_scope(backup, levels, filters)


# ── parsing the Site field ─────────────────────────────────────────────

def test_site_field_splits_on_commas():
    assert pages._split_scope_names("FAO-TEST, FAO-TEST-2") == \
        ["FAO-TEST", "FAO-TEST-2"]


def test_quotes_keep_a_comma_inside_one_name_and_repeats_drop_out():
    assert pages._split_scope_names(' "Paris, France" ,Rome,, rome ') == \
        ["Paris, France", "Rome"]


def test_blank_site_field_names_nothing():
    assert pages._split_scope_names("") == []
    assert pages._split_scope_names(" , ") == []


def test_a_list_passes_through_cleaned():
    assert pages._split_scope_names(["A", " ", "a", "B"]) == ["A", "B"]


def test_chooser_output_round_trips_through_the_field():
    names = ["FAO-TEST", "Paris, France", 'Say "hi"']
    assert pages._split_scope_names(pages._join_scope_names(names)) == names


# ── the scope rules ────────────────────────────────────────────────────

def test_one_site_restores_that_site_and_only_its_groups():
    backup, scope = _scope({"account": ACCT, "site": "FAO-TEST",
                            "group": ""})
    assert _paths(backup, scope["indices"]) == FAO_TEST


def test_exact_site_name_does_not_pull_in_a_longer_one():
    backup, scope = _scope({"site": "FAO-TEST"})
    assert not any("FAO-TEST-2" in p
                   for p in _paths(backup, scope["indices"]))


def test_several_sites_restore_each_of_them():
    backup, scope = _scope({"site": "FAO-TEST, FAO-TEST-2"})
    assert _paths(backup, scope["indices"]) == FAO_TEST + FAO_TEST_2
    assert scope["sites"] == ["FAO-TEST", "FAO-TEST-2"]


def test_sites_may_be_given_as_a_list():
    backup, scope = _scope({"site": ["FAO-TEST-2", "FAO-TEST"]})
    assert _paths(backup, scope["indices"]) == FAO_TEST + FAO_TEST_2


def test_group_field_narrows_within_the_chosen_site_only():
    backup, scope = _scope({"site": "FAO-TEST", "group": "Default Group"})
    assert _paths(backup, scope["indices"]) == FAO_TEST[:2]


def test_ranking_sees_the_whole_chosen_site_even_when_groups_narrow():
    _backup, scope = _scope({"site": "FAO-TEST", "group": "Default Group"})
    assert [n["path"] for n in scope["rank_nodes"]] == FAO_TEST[1:]


def test_no_ranking_when_groups_are_not_being_restored():
    _backup, scope = _scope({"site": "FAO-TEST"}, levels=SITES_ONLY)
    assert scope["rank_nodes"] == []


def test_a_named_site_brings_its_own_account_and_no_other():
    backup, scope = _scope({"site": "FAO-TEST"}, levels=UI_DEFAULTS,
                           backup=_two_accounts())
    assert _paths(backup, scope["indices"]) == [f"{ACCT}/"] + FAO_TEST


def test_a_named_group_brings_only_the_site_and_account_holding_it():
    backup, scope = _scope({"group": "Servers"}, levels=UI_DEFAULTS,
                           backup=_two_accounts())
    assert _paths(backup, scope["indices"]) == [
        f"{ACCT}/", f"{ACCT}/FAO-TEST", f"{ACCT}/FAO-TEST/Servers"]
    assert [n["path"] for n in scope["rank_nodes"]] == FAO_TEST[1:]


def test_unticking_accounts_leaves_the_parent_account_out():
    backup, scope = _scope({"site": "FAO-TEST"}, backup=_two_accounts())
    assert _paths(backup, scope["indices"]) == FAO_TEST


def test_blank_fields_restore_every_node_of_the_ticked_levels():
    backup, scope = _scope({"account": "", "site": "", "group": ""})
    assert len(scope["indices"]) == len(backup) - 1     # all but the account


def test_the_global_node_is_never_filtered_by_name():
    backup = [{"type": "global", "path": "/", "data": {}}] + _fao_backup()
    levels = dict(SITES_AND_GROUPS, **{"global": True})
    _b, scope = _scope({"site": "FAO-TEST"}, levels=levels, backup=backup)
    assert scope["indices"][0] == 0


def test_a_site_whose_name_holds_a_comma():
    backup = [{"type": "site", "path": f"Acme/{name}", "site": {"name": name}}
              for name in ("Paris, France", "Paris", "Rome")]
    _b, scope = _scope({"site": "Paris, France"}, levels=SITES_ONLY,
                       backup=backup)
    assert scope["sites"] == ["Paris, France"]          # typed bare: one site
    _b, scope = _scope({"site": '"Paris, France", Rome'}, levels=SITES_ONLY,
                       backup=backup)
    assert scope["sites"] == ["Paris, France", "Rome"]


# ── a name that matches nothing stops the run ──────────────────────────

def test_a_misspelt_site_is_reported_with_the_real_sites():
    backup, scope = _scope({"site": "FAO-TEST, FAO-TSET"})
    assert scope["unmatched"]["site"] == ["FAO-TSET"]
    msg = pages._restore_scope_problem(backup, scope)
    assert "FAO-TSET" in msg
    assert "FAO-DEFAULT" in msg and "FAO-TEST-2" in msg


def test_an_account_not_in_the_backup_selects_nothing_and_says_so():
    backup, scope = _scope({"account": "Someone Else", "site": "FAO-TEST"})
    assert scope["indices"] == []
    assert "Someone Else" in pages._restore_scope_problem(backup, scope)


def test_nothing_ticked_is_reported():
    backup, scope = _scope({}, levels={"global": False, "accounts": False,
                                       "sites": False, "groups": False})
    assert "Nothing to restore" in pages._restore_scope_problem(backup, scope)


def test_a_valid_scope_has_no_problem():
    backup, scope = _scope({"site": "FAO-TEST"})
    assert pages._restore_scope_problem(backup, scope) == ""


def test_scope_line_names_the_sites_and_counts_the_nodes():
    backup, scope = _scope({"site": "FAO-TEST, FAO-TEST-2"})
    line = pages._describe_restore_scope(scope, len(backup))
    assert "FAO-TEST, FAO-TEST-2" in line
    assert f"5 of {len(backup)}" in line


def test_scope_line_names_the_account_restored_along_with_the_site():
    backup, scope = _scope({"site": "FAO-TEST"}, levels=UI_DEFAULTS,
                           backup=_two_accounts())
    line = pages._describe_restore_scope(scope, len(backup))
    assert ACCT in line and "Other" not in line
    assert f"4 of {len(backup)}" in line


# ── the chooser's list comes from the backup file ─────────────────────

def test_backup_sites_lists_every_site_with_its_group_count():
    sites = pages._backup_sites(_fao_backup())
    assert [(s["name"], s["groups"]) for s in sites] == [
        ("FAO-DEFAULT", 3), ("FAO-TEST", 2), ("FAO-TEST-2", 1)]


def test_backup_sites_are_found_through_group_paths_too():
    groups_only = [n for n in _fao_backup() if n["type"] == "group"]
    assert [s["name"] for s in pages._backup_sites(groups_only)] == [
        "FAO-DEFAULT", "FAO-TEST", "FAO-TEST-2"]


def test_backup_sites_follow_the_account_field():
    backup = _fao_backup() + [{"type": "site", "path": "Other/HQ",
                               "site": {"name": "HQ"}}]
    assert [s["name"] for s in pages._backup_sites(backup, "Other")] == ["HQ"]
    assert len(pages._backup_sites(backup, "")) == 4
    assert len(pages._backup_sites(backup, "nobody")) == 4


# ── the destination snapshot honours several sites too ────────────────

class TreeAPI:
    def get_accounts(self):
        return [{"id": "A1", "name": ACCT}]

    def get_sites(self, params=None):
        return [{"id": "S1", "name": "FAO-DEFAULT"},
                {"id": "S2", "name": "FAO-TEST"},
                {"id": "S3", "name": "FAO-TEST-2"}]

    def get_groups(self, params=None):
        return [{"id": f"G-{params['siteIds']}", "name": "Default Group"}]


def test_snapshot_tree_lists_only_the_chosen_sites():
    out = pages._enumerate_tree(TreeAPI(), {"site": "FAO-TEST, FAO-TEST-2"},
                                {"sites": True, "groups": True})
    assert {n["site_name"] for n in out} == {"FAO-TEST", "FAO-TEST-2"}


# ── the real restore loop ──────────────────────────────────────────────

class _Widget:
    def __getattr__(self, _name):
        return lambda *a, **kw: None


class _Table(_Widget):
    _real = inspect.signature(pages.ProgressTable.add_node)

    def __init__(self):
        self.rows = []
        self.done = {}

    def set_done(self, node_id, summary=""):
        self.done[node_id] = summary

    def add_node(self, *args, **kwargs):
        call = self._real.bind(self, *args, **kwargs)
        call.apply_defaults()
        self.rows.append((call.arguments["node_id"], call.arguments["path"],
                          call.arguments["num"]))


class NoopAPI:
    base_url = "https://dest.example"

    def __getattr__(self, _name):
        return lambda *a, **kw: {}


class Runner:
    _run_restore = RestorePage._run_restore
    _ledger_add = RestorePage._ledger_add
    _record_site_element = RestorePage._record_site_element
    _set_skip_label = RestorePage._set_skip_label

    def __init__(self):
        self.ptable = _Table()
        self.progress = _Widget()
        self.log = _Widget()
        self._skip_btn = _Widget()
        self._status_lbl = _Widget()
        self._operation_log = []
        self._item_ledger = []
        self._report_nodes = []
        self._resolve_issues = {}
        self._resolved_site_ids = {}
        self._skip_make_default_ids = set()
        self._checkpoint = {}
        self._cancelled = False
        self._skip_element = False
        self._acct_id = ""
        self._auto_create_accounts = False
        self.resolved = []
        self.ranked = None

    def after(self, _delay, fn=None):
        if fn is not None:
            fn()

    def _resolve_dest_id(self, api, node, log, progress=None):
        self.resolved.append(node["path"])
        return "dest-1"

    def _rerank_groups(self, api, nodes):
        self.ranked = [n["path"] for n in nodes]


def _restore(filters, levels=SITES_AND_GROUPS, runner=None, backup=None):
    runner = runner or Runner()
    runner._run_restore(NoopAPI(), backup or _fao_backup(), [],
                        levels=levels, scope_filters=filters)
    return runner


def test_restoring_one_site_never_resolves_another_sites_groups():
    runner = _restore({"account": ACCT, "site": "FAO-TEST", "group": ""})
    assert runner.resolved == FAO_TEST


def test_other_sites_are_not_even_listed():
    runner = _restore({"site": "FAO-TEST"})
    assert [path for _nid, path, _num in runner.ptable.rows] == FAO_TEST


def test_listed_rows_keep_their_backup_numbers():
    # The Source-vs-Destination dropdown numbers nodes by backup position;
    # the progress rows must keep pointing at the same node.
    backup = _fao_backup()
    want = [next(i for i, n in enumerate(backup) if n["path"] == p) + 1
            for p in FAO_TEST]
    runner = _restore({"site": "FAO-TEST"})
    assert [num for _nid, _path, num in runner.ptable.rows] == want


def test_restoring_a_site_never_lists_another_account():
    runner = _restore({"site": "FAO-TEST"}, levels=UI_DEFAULTS,
                      backup=_two_accounts())
    assert [path for _nid, path, _num in runner.ptable.rows] == \
        [f"{ACCT}/"] + FAO_TEST


def test_create_all_does_not_widen_the_scope():
    # "Create All" in the account dialog used to switch every name filter
    # off for the rest of the run.
    runner = Runner()
    runner._auto_create_accounts = True
    _restore({"site": "FAO-TEST"}, runner=runner)
    assert runner.resolved == FAO_TEST


def test_several_sites_restore_all_of_them_and_nothing_else():
    runner = _restore({"site": "FAO-TEST, FAO-TEST-2"})
    assert runner.resolved == FAO_TEST + FAO_TEST_2


def test_group_ranking_only_touches_the_chosen_site():
    runner = _restore({"site": "FAO-TEST"})
    assert runner.ranked == FAO_TEST[1:]


def test_nodes_finished_before_a_resume_show_as_done():
    # They are restored: listing them as "skipped" made a finished site
    # look untouched in the per-site progress.
    backup = _fao_backup()
    first = next(i for i, n in enumerate(backup) if n["path"] == FAO_TEST[0])
    runner = Runner()
    runner._resume_checkpoint = {first: "done"}
    _restore({"site": "FAO-TEST"}, runner=runner)
    assert runner.ptable.done[f"r-{first}"] == "done in the previous run"
    assert FAO_TEST[0] not in runner.resolved


def test_a_stopped_run_only_leaves_in_scope_nodes_to_resume():
    # Out-of-scope nodes marked "cancelled" would inflate Resume's count
    # and be retried by it.
    runner = Runner()
    runner._cancelled = True
    _restore({"site": "FAO-TEST"}, runner=runner)
    backup = _fao_backup()
    assert sorted(runner._checkpoint) == sorted(
        i for i, n in enumerate(backup) if n["path"] in FAO_TEST)


# ── wiring ─────────────────────────────────────────────────────────────

class _Entry:
    def __init__(self, text):
        self.text = text

    def get(self):
        return self.text


def test_scope_fields_are_ignored_only_while_global_hides_them():
    page = types.SimpleNamespace(restore_acct=_Entry(f" {ACCT} "),
                                 restore_site=_Entry("FAO-TEST, FAO-TEST-2 "),
                                 restore_group=_Entry(""))
    assert RestorePage._scope_filters(page, {"global": False}) == {
        "account": ACCT, "site": "FAO-TEST, FAO-TEST-2", "group": ""}
    assert RestorePage._scope_filters(page, {"global": True}) == {
        "account": "", "site": "", "group": ""}


def test_auto_restore_and_resume_keep_the_scope_fields():
    src = inspect.getsource(RestorePage._start_restore)
    assert "self._scope_filters(levels)" in src
    assert 'scope_filters = {"account": "", "site": "", "group": ""}' \
        not in src, "Auto Restore / Resume must not discard the fields"


def test_the_restore_loop_has_no_filter_bypass():
    assert "_bypass_filters" not in inspect.getsource(
        RestorePage._run_restore)


def test_preview_uses_the_same_scope_as_the_restore():
    assert "_restore_scope(" in inspect.getsource(
        RestorePage._preview_changes)


def test_site_field_has_a_chooser_fed_by_the_backup_file():
    assert "_choose_restore_sites" in inspect.getsource(
        RestorePage._build_scope_card)
    chooser = inspect.getsource(RestorePage._choose_restore_sites)
    assert "_backup_sites(" in chooser
    assert "_join_scope_names(" in chooser
