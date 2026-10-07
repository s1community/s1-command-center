"""The Restore screen: one primary action, controls that only appear when
they apply, and a live "what will be restored" line.

Also: a restore REPORT (or any JSON that isn't a backup) loaded as a backup
used to fail with "'str' object has no attribute 'get'", and auto-load
picked the newest s1*.json in ~/Documents — usually a report.
"""
import json
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pages
from pages import RestorePage

ACCT = "FAO"
REPORT = {"meta": {"scope": "Site: FAO-TEST"}, "nodes": [], "log": [],
          "items": []}


def _backup():
    nodes = [{"type": "account", "path": f"{ACCT}/", "account": {"name": ACCT},
              "data": {},
              "backupMetadata": {"url": "https://fao.sentinelone.net"}}]
    for site, groups in (("FAO-DEFAULT", ["Default Group"]),
                         ("FAO-TEST", ["Default Group", "Servers"])):
        nodes.append({"type": "site", "path": f"{ACCT}/{site}",
                      "site": {"name": site}, "data": {}})
        nodes += [{"type": "group", "path": f"{ACCT}/{site}/{g}",
                   "group": {"name": g}, "data": {}} for g in groups]
    return nodes


# ── what counts as a backup file ───────────────────────────────────────

def test_a_restore_report_is_named_for_what_it_is():
    problem = pages._backup_file_problem(REPORT)
    assert "restore report" in problem and "not a backup" in problem


def test_other_json_is_turned_away_in_plain_words():
    assert "isn't a backup" in pages._backup_file_problem({"a": 1})
    assert "isn't a backup" in pages._backup_file_problem(["x", "y"])


def test_an_empty_backup_says_so():
    assert "empty" in pages._backup_file_problem([])


def test_a_real_backup_has_no_problem():
    assert pages._backup_file_problem(_backup()) == ""


def test_broken_json_gets_a_readable_reason():
    try:
        json.loads("{nope")
    except json.JSONDecodeError as exc:
        assert "isn't valid JSON" in pages._load_error_text(exc)


def _write(tmp_path, name, payload, mtime):
    path = tmp_path / name
    path.write_text(payload if isinstance(payload, str)
                    else json.dumps(payload))
    os.utime(path, (mtime, mtime))
    return str(path)


def test_auto_load_passes_over_a_newer_report(tmp_path):
    backup = _write(tmp_path, "s1-backup-1.json", _backup(), 1000)
    report = _write(tmp_path, "s1-restore-report-2.json", REPORT, 2000)
    assert pages._latest_backup_file([report, backup]) == backup


def test_auto_load_takes_the_newest_backup(tmp_path):
    old = _write(tmp_path, "s1-backup-1.json", _backup(), 1000)
    new = _write(tmp_path, "s1-backup-2.json", _backup(), 2000)
    assert pages._latest_backup_file([old, new]) == new


def test_auto_load_finds_nothing_when_no_file_is_a_backup(tmp_path):
    report = _write(tmp_path, "s1-restore-report-2.json", REPORT, 2000)
    empty = _write(tmp_path, "s1-empty.json", "", 3000)
    assert pages._latest_backup_file(
        [report, empty, str(tmp_path / "gone.json")]) is None


def test_the_backup_card_says_what_the_file_holds():
    text = pages._backup_overview(_backup())
    assert "1 account" in text and "2 sites" in text and "3 groups" in text
    assert "fao.sentinelone.net" in text


# ── starting a restore ─────────────────────────────────────────────────

class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class _Sink:
    def __getattr__(self, _name):
        return lambda *a, **kw: None


class Starter:
    """Just enough of RestorePage to drive _start_restore to the run."""
    _start_restore = RestorePage._start_restore
    _scope_filters = RestorePage._scope_filters

    def __init__(self):
        self.backup_data = _backup()
        self.app = types.SimpleNamespace(
            cfg=types.SimpleNamespace(get_by_role=lambda role: None))
        self._console_var = _Var("DESTINATION")
        self.restore_level_vars = {
            "global": _Var(False), "accounts": _Var(True),
            "sites": _Var(True), "groups": _Var(True)}
        self.restore_acct = _Var("")
        self.restore_site = _Var("FAO-TEST")
        self.restore_group = _Var("")
        self.restore_vars = {"policy": _Var(True)}
        self._snapshot_var = _Var(False)
        self.ptable = _Sink()
        self.progress = _Sink()
        self.account_checked = False
        self.started = False

    def _get_restore_api(self):
        return types.SimpleNamespace(base_url="https://dest.example")

    def _check_account_name_match(self, api):
        self.account_checked = True
        return "ok"

    def _tick_timer(self):
        pass

    def _set_ui_running(self, running):
        self.started = running


def _start(monkeypatch, answers, **kwargs):
    asked = []

    def askyesno(_title, message, **_kw):
        asked.append(message)
        return answers.pop(0) if answers else True

    monkeypatch.setattr(pages.messagebox, "askyesno", askyesno)
    monkeypatch.setattr(pages, "run_async", lambda *a, **kw: None)
    page = Starter()
    page._start_restore(**kwargs)
    return page, asked


def test_an_unattended_restore_still_confirms_once(monkeypatch):
    page, asked = _start(monkeypatch, [True], auto=True, confirm=True)
    assert len(asked) == 1 and "Unattended" in asked[0]
    assert page.account_checked and page.started


def test_cancelling_the_confirmation_writes_nothing(monkeypatch):
    page, asked = _start(monkeypatch, [False], auto=True, confirm=True)
    assert asked and not page.started


def test_resume_does_not_ask_again(monkeypatch):
    # Resume confirms in its own dialog, then starts unattended.
    page, asked = _start(monkeypatch, [], auto=True)
    assert asked == [] and page.started


def test_a_normal_restore_confirms_with_the_scope(monkeypatch):
    page, asked = _start(monkeypatch, [True], auto=False)
    assert len(asked) == 1 and "FAO-TEST" in asked[0]
    assert "Unattended" not in asked[0] and page.started


# ── the screen itself (real widgets) ───────────────────────────────────

def _run_inline(_widget, fn, done=None, err=None):
    """run_async without the thread: a worker thread may only touch Tk
    while mainloop() runs, and tests have no mainloop."""
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
    import customtkinter as ctk
    try:
        root = ctk.CTk()
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


def _visible(widget, page):
    """Managed all the way up to the page (hidden parents hide children)."""
    while widget is not None and widget is not page:
        if not widget.winfo_manager():
            return False
        widget = widget.master
    return True


def _load(page, tmp_path, payload, name="s1-backup-x.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    page._load_file(str(path))
    page.update_idletasks()


def test_before_a_backup_only_loading_one_is_offered(screen):
    assert screen._start_btn.cget("state") == "disabled"
    assert "Load a backup" in screen._scope_summary.cget("text")
    for btn in (screen._stop_btn, screen._skip_btn, screen._export_btn,
                screen._resume_btn):
        assert not _visible(btn, screen)


def test_a_loaded_backup_arms_restore_with_the_node_count(screen, tmp_path):
    _load(screen, tmp_path, _backup())
    assert screen._start_btn.cget("state") == "normal"
    assert "Restore 6 nodes" in screen._start_btn.cget("text")
    screen.restore_site.insert(0, "FAO-TEST")
    screen._update_scope_summary()
    assert "Restore 4 nodes" in screen._start_btn.cget("text")
    assert "FAO-TEST" in screen._scope_summary.cget("text")


def test_a_report_file_explains_itself_and_keeps_restore_off(screen,
                                                             tmp_path):
    _load(screen, tmp_path, REPORT, name="s1-restore-report-x.json")
    assert screen.backup_data is None
    assert "restore report" in screen.info_lbl.cget("text")
    assert screen._start_btn.cget("state") == "disabled"


def test_a_site_not_in_the_backup_is_flagged_before_restore(screen,
                                                             tmp_path):
    _load(screen, tmp_path, _backup())
    screen.restore_site.insert(0, "FAO-TST")
    screen._update_scope_summary()
    assert "FAO-TST" in screen._scope_summary.cget("text")
    assert screen._start_btn.cget("state") == "disabled"


def test_run_controls_show_only_while_running(screen, tmp_path):
    _load(screen, tmp_path, _backup())
    screen._set_ui_running(True)
    assert _visible(screen._stop_btn, screen)
    assert _visible(screen._skip_btn, screen)
    assert not _visible(screen._export_btn, screen)
    screen._set_ui_running(False)
    assert not _visible(screen._stop_btn, screen)
    assert _visible(screen._export_btn, screen)
    assert not _visible(screen._resume_btn, screen)


def test_global_hides_the_name_fields(screen):
    screen.restore_level_vars["global"].set(True)
    assert not _visible(screen.restore_site, screen)
    screen.restore_level_vars["global"].set(False)
    assert _visible(screen.restore_site, screen)


def test_an_account_mismatch_opens_the_rename_tools(screen):
    assert not _visible(screen.mangle_src, screen)
    screen._open_structure_ops_for_rename("FAO", "FAO-NEW")
    assert _visible(screen.mangle_src, screen)
    assert screen.mangle_dst.get() == "FAO-NEW"


def test_reset_returns_to_a_blank_screen(screen, tmp_path):
    _load(screen, tmp_path, _backup())
    screen._set_ui_running(True)
    screen._set_ui_running(False)
    screen.file_entry.delete(0, "end")
    screen.backup_data = None
    screen.reset_view()
    assert screen._start_btn.cget("state") == "disabled"
    assert not _visible(screen._export_btn, screen)


def test_the_next_step_is_the_only_filled_button(screen, tmp_path):
    assert screen._browse_btn.cget("fg_color") == pages.BRAND
    assert screen._start_btn.cget("fg_color") == pages.theme.GHOST
    _load(screen, tmp_path, _backup())
    assert screen._browse_btn.cget("fg_color") == pages.theme.GHOST
    assert screen._start_btn.cget("fg_color") == pages.GREEN
    assert screen._preflight_btn.cget("fg_color") == pages.theme.GHOST
    assert _visible(screen._preflight_btn, screen)


def test_after_a_stopped_run_resume_is_the_next_step(screen, tmp_path):
    _load(screen, tmp_path, _backup())
    screen._set_ui_running(True)
    screen._checkpoint = {"a": "done", "b": "cancelled", "c": "error"}
    screen._set_ui_running(False)
    assert _visible(screen._resume_btn, screen)
    assert "2 left" in screen._resume_btn.cget("text")
    assert screen._start_btn.cget("fg_color") == pages.theme.GHOST
    assert screen._start_btn.cget("state") == "normal"
    assert screen._badge_state["run"] == "warn"


def test_steps_show_done_and_problems_at_a_glance(screen, tmp_path):
    _load(screen, tmp_path, _backup())
    assert screen._badge_state == {"backup": "done", "scope": "done",
                                   "run": "active"}
    screen.restore_site.insert(0, "FAO-TST")
    screen._update_scope_summary()
    assert screen._badge_state["scope"] == "error"
    assert screen._badge_state["run"] == "todo"


def test_untick_an_element_and_the_line_says_so(screen, tmp_path):
    _load(screen, tmp_path, _backup())
    total = len(screen.restore_vars)
    next(iter(screen.restore_vars.values())).set(False)
    screen._update_scope_summary()
    assert f"{total - 1} of {total} elements" in \
        screen._scope_summary.cget("text")
    assert f"elements {total - 1}/{total}" in screen._adv_btn.cget("text")


def test_unattended_is_a_switch_on_the_one_restore_button(screen, tmp_path):
    _load(screen, tmp_path, _backup())
    screen._auto_var.set(True)
    screen._apply_state()
    assert screen._start_btn.cget("text").startswith("⚡")
    assert "Restore 6 nodes" in screen._start_btn.cget("text")


def test_results_tabs_swap_panes_and_survive_the_busy_lock(screen):
    assert _visible(screen.ptable, screen)
    assert not _visible(screen.diff_panel, screen)
    screen._show_results("compare")
    assert _visible(screen.diff_panel, screen)
    assert not _visible(screen.ptable, screen)
    assert all(t._busy_exempt for t in screen._result_tabs.values())


def test_more_options_make_room_and_a_run_brings_progress_back(screen,
                                                               tmp_path):
    _load(screen, tmp_path, _backup())
    screen._toggle_advanced()
    assert _visible(screen.mangle_src, screen)
    assert not _visible(screen.ptable, screen)
    screen._set_ui_running(True)
    assert not screen._advanced_open
    assert _visible(screen.ptable, screen)


def test_buttons_reach_their_handlers(screen):
    assert screen._gap_csv_btn.cget("command") == screen._export_gap_csv
    assert screen._choose_btn.cget("command") == screen._choose_restore_sites
    assert screen._rollback_btn.cget("command") == screen._load_last_snapshot


def test_scope_line_without_names_counts_the_ticked_levels():
    backup = _backup()
    levels = {"global": False, "accounts": False, "sites": True,
              "groups": False}
    scope = pages._restore_scope(backup, levels, {})
    line = pages._describe_restore_scope(scope, len(backup))
    assert line.startswith("the ticked levels") and "2 of 6" in line
