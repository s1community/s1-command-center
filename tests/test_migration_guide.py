"""The migration guide: the runbook that follows the operator.

The Migration Runbook used to be a page of its own, and a checklist you
have to remember to open gets forgotten. The guide lives where the work
happens instead — the sidebar's MIGRATION panel, a strip above every
migration page, a hand-off the moment a step finishes — and asks before
the two steps that hurt to skip blind. Progress is read from the pages
and kept per source → destination pair, so it survives a restart.
"""
import inspect
import os
import re
import sys
import time
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import migration_guide as mg  # noqa: E402

SRC = "https://src.sentinelone.net"
DST = "https://dst.sentinelone.net"
OTHER = "https://other.sentinelone.net"
T1 = "2026-10-22T10:00:00+00:00"
T2 = "2026-10-22T11:00:00+00:00"


def _read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def _nav_labels():
    nav = _read("app.py").split("nav_migration = [", 1)[1].split("]", 1)[0]
    return re.findall(r'\("([^"]+)",', nav)


# ── a main window, as far as the guide can see it ──────────────────────

def _api(url):
    return types.SimpleNamespace(base_url=url, api_token="SECRET-TOKEN")


def _app(source=SRC, dest=DST):
    backup = types.SimpleNamespace(_timer_running=False,
                                   _console_var=_Var("SOURCE"))
    restore = types.SimpleNamespace(_last_preflight=None, _last_preview=None,
                                    _report_meta={}, _run_mode="idle",
                                    _preflighting=False, _previewing=False)
    validation = types.SimpleNamespace(_results=[], _meta={}, _running=False,
                                       _manifest_exported=None)
    agents = types.SimpleNamespace(_plan=None, _plan_saved_at="",
                                   _report=None, _busy=None,
                                   _plan_stale=lambda: False)
    return types.SimpleNamespace(
        source_api=_api(source) if source else None,
        dest_api=_api(dest) if dest else None,
        _last_backup_path=None, _last_backup_url="", _busy=False,
        pages={"Backup Source": backup,
               "Restore to Dest": restore,
               "Migration Validation": validation,
               "Agent Migration": agents})


def _backed_up(app, path="/tmp/s1-backup-1.json", url=SRC):
    app._last_backup_path, app._last_backup_url = path, url


def _preflighted(app, verdict="pass", at=T1, dest=DST):
    app.pages["Restore to Dest"]._last_preflight = {
        "at": at, "verdict": verdict, "dest": dest, "checks": []}


def _previewed(app, at=T1, dest=DST):
    app.pages["Restore to Dest"]._last_preview = {
        "at": at, "dest": dest, "create": 4, "exists": 2}


def _restored(app, end=T1, dest=DST, **flags):
    app.pages["Restore to Dest"]._report_meta = dict(
        {"dest_url": dest, "dest_console": "DESTINATION", "end_time": end},
        **flags)


def _validated(app, when=T1, dest=DST):
    page = app.pages["Migration Validation"]
    page._results = [{"path": "Acme/", "matched": True, "diffs": 0}]
    page._meta = {"src_url": SRC, "dst_url": dest, "when": when}


def _planned(app):
    app.pages["Agent Migration"]._plan = {"rows": [], "agents": 3}


def _migrated(app):
    app.pages["Agent Migration"]._report = {"moved": 3}


def _manifested(app, at=T2):
    app.pages["Migration Validation"]._manifest_exported = {
        "path": "/tmp/migration-manifest.json", "at": at, "dest": DST}


def _everything(app):
    _backed_up(app)
    _preflighted(app)
    _previewed(app)
    _restored(app)
    _validated(app)
    _planned(app)
    _migrated(app)
    _manifested(app)


RUNNABLE = ("backup", "preflight", "preview", "restore", "validate",
            "agents_matched", "agents_moved")


def _running(app, key, on=True):
    """Start (or end) the work behind a step, flagged the way its page
    flags it while it runs."""
    pages = app.pages
    if key == "backup":
        pages["Backup Source"]._timer_running = on
    elif key == "preflight":
        pages["Restore to Dest"]._preflighting = on
    elif key == "preview":
        pages["Restore to Dest"]._previewing = on
    elif key == "restore":
        page = pages["Restore to Dest"]
        page._run_mode = "running" if on else "done"
        if on:
            page._report_meta = {"dest_url": DST,
                                 "dest_console": "DESTINATION"}
    elif key == "validate":
        page = pages["Migration Validation"]
        page._running = on
        if on:
            page._results, page._meta = [], {}
    else:
        page = pages["Agent Migration"]
        page._busy = ({"agents_matched": "check", "agents_moved": "live"}[key]
                      if on else None)
        if on and key == "agents_matched":
            page._plan = None
        elif on:
            page._report = None


def _guide(tmp_path):
    return mg.Guide(mg.GuideStore(str(tmp_path / "migration_guide.json")))


def _look(guide, app):
    return guide.update(mg.route_of(app), mg.observe(app))


# ── the steps ──────────────────────────────────────────────────────────

def test_the_steps_run_in_migration_order():
    assert mg.STEP_KEYS == (
        "connect", "backup", "preflight", "preview", "restore", "validate",
        "agents_matched", "agents_moved", "manifest")


def test_pre_flight_comes_after_the_backup_it_needs():
    """The old runbook asked for Pre-flight before the backup existed,
    but Pre-flight reads the loaded backup and refuses without one."""
    import pages
    assert "Load a backup file first." in inspect.getsource(
        pages.RestorePage._preflight)
    keys = list(mg.STEP_KEYS)
    assert keys.index("backup") < keys.index("preflight")


def test_every_step_opens_a_page_in_the_migration_nav():
    labels = _nav_labels()
    assert all(step.page in labels for step in mg.STEPS)


def test_the_runbook_page_is_gone():
    assert "Migration Runbook" not in _nav_labels()
    assert "MigrationRunbookPage" not in _read("app.py")
    assert "class MigrationRunbookPage" not in _read("pages.py")


def test_the_sidebar_lists_the_pages_in_the_order_the_work_happens():
    guided = [label for label in _nav_labels() if label in mg.GUIDED_PAGES]
    assert guided == list(mg.GUIDED_PAGES) == [
        "Connections", "Backup Source", "Restore to Dest",
        "Migration Validation", "Agent Migration"]


def test_short_names_fit_the_sidebar_checklist():
    assert all(len(step.short) <= 20 for step in mg.STEPS)


def test_a_migration_is_named_by_its_two_consoles():
    assert mg.route_key("https://SRC.sentinelone.net/",
                        "dst.sentinelone.net") == (
        "src.sentinelone.net → dst.sentinelone.net")
    assert mg.route_key(SRC, "") == "" and mg.route_key("", DST) == ""


# ── what the pages show ────────────────────────────────────────────────

def test_without_both_consoles_the_first_step_is_connecting(tmp_path):
    guide = _guide(tmp_path)
    _look(guide, _app(dest=None))
    assert guide.route == "" and guide.next().key == "connect"


def test_connected_consoles_point_at_the_backup(tmp_path):
    guide = _guide(tmp_path)
    _look(guide, _app())
    assert guide.state("connect") == "done"
    assert guide.next().key == "backup" and guide.done_count() == 1


def test_a_backup_of_the_destination_is_not_the_source_backup(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _backed_up(app, url=DST)
    _look(guide, app)
    assert guide.state("backup") == "todo"
    _backed_up(app, url=SRC)
    _look(guide, app)
    assert guide.state("backup") == "done"


def test_a_failed_pre_flight_needs_a_look(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _backed_up(app)
    _preflighted(app, "fail")
    _look(guide, app)
    assert guide.state("preflight") == "attention"
    assert guide.next().key == "preflight"
    assert "Pre-flight again" in guide.note("preflight")


def test_a_pre_flight_with_warnings_counts_and_says_so(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _preflighted(app, "warn")
    _look(guide, app)
    assert guide.state("preflight") == "done"
    assert "warnings" in guide.note("preflight")


def test_checks_against_another_destination_do_not_count(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _preflighted(app, dest=OTHER)
    _previewed(app, dest=OTHER)
    _restored(app, dest=OTHER)
    _validated(app, dest=OTHER)
    _look(guide, app)
    assert [guide.state(k) for k in ("preflight", "preview", "restore",
                                     "validate")] == ["todo"] * 4


def test_a_restore_counts_once_it_has_finished(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _restored(app, end=None)
    _look(guide, app)
    assert guide.state("restore") == "todo"
    _restored(app)
    _look(guide, app)
    assert guide.state("restore") == "done"


def test_a_stopped_or_failed_restore_points_at_resume(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _restored(app, cancelled=True)
    _look(guide, app)
    assert guide.state("restore") == "attention"
    assert "Resume" in guide.note("restore")
    _restored(app, end=T2, run_failed=True)
    _look(guide, app)
    assert guide.state("restore") == "attention"
    assert "error" in guide.note("restore")


def test_a_stale_agent_plan_does_not_count(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _planned(app)
    app.pages["Agent Migration"]._plan_stale = lambda: True
    _look(guide, app)
    assert guide.state("agents_matched") == "todo"


def test_the_whole_migration_end_to_end(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _everything(app)
    _look(guide, app)
    assert guide.done_count() == len(mg.STEPS)
    assert guide.next() is None and guide.complete()


def test_each_page_gets_a_mark(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _backed_up(app)
    _preflighted(app)
    _look(guide, app)
    assert guide.page_mark("Connections") == ("✓", "done")
    assert guide.page_mark("Restore to Dest") == ("1/3", "next")
    assert guide.page_mark("Agent Migration") == ("", "")
    _preflighted(app, "fail")
    _look(guide, app)
    assert guide.page_mark("Restore to Dest") == ("!", "warn")


# ── remembered per migration ───────────────────────────────────────────

def test_progress_survives_a_restart(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _backed_up(app)
    _preflighted(app)
    _look(guide, app)

    later = _guide(tmp_path)          # a new session: the pages forgot
    _look(later, _app())
    assert later.state("backup") == later.state("preflight") == "done"
    assert later.next().key == "preview"


def test_each_pair_of_consoles_keeps_its_own_progress(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _restored(app)
    _look(guide, app)
    assert guide.state("restore") == "done"

    app.dest_api = _api(OTHER)
    _look(guide, app)
    assert guide.state("restore") == "todo"

    app.dest_api = _api(DST)
    _look(guide, app)
    assert guide.state("restore") == "done"


def test_progress_made_before_both_consoles_connect_is_kept(tmp_path):
    guide, app = _guide(tmp_path), _app(dest=None)
    _look(guide, app)
    guide.mark("backup")
    app.dest_api = _api(DST)
    _look(guide, app)
    assert guide.state("backup") == "done"
    later = _guide(tmp_path)
    _look(later, _app())
    assert later.state("backup") == "done"


def test_a_step_done_by_hand_can_be_undone(tmp_path):
    guide = _guide(tmp_path)
    _look(guide, _app())
    guide.mark("preview")
    assert guide.state("preview") == "done" and guide.how("preview") == \
        "manual"
    guide.mark("preview", False)
    assert guide.state("preview") == "todo"


def test_connecting_cannot_be_ticked_by_hand(tmp_path):
    guide = _guide(tmp_path)
    _look(guide, _app(dest=None))
    guide.mark("connect")
    assert guide.state("connect") == "todo"


def test_marking_a_problem_done_puts_it_to_rest(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _preflighted(app, "fail")
    _look(guide, app)
    guide.mark("preflight")
    assert guide.state("preflight") == "done"
    _look(guide, app)
    assert guide.state("preflight") == "done"
    _preflighted(app, "fail", at=T2)        # a new run fails again
    _look(guide, app)
    assert guide.state("preflight") == "attention"


def test_starting_over_ignores_what_the_pages_still_show(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _backed_up(app)
    _preflighted(app)
    _previewed(app)
    _look(guide, app)
    assert guide.done_count() == 4

    guide.start_over()
    _look(guide, app)
    assert guide.done_count() == 1 and guide.next().key == "backup"

    _backed_up(app, path="/tmp/s1-backup-2.json")     # the next wave
    _look(guide, app)
    assert guide.state("backup") == "done"
    assert guide.state("preflight") == "todo"


def test_a_second_start_over_keeps_the_first_one(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _backed_up(app)
    _look(guide, app)
    guide.start_over()
    _look(guide, app)
    guide.start_over()
    _look(guide, app)
    assert guide.state("backup") == "todo"


def test_a_damaged_progress_file_starts_clean(tmp_path):
    path = tmp_path / "migration_guide.json"
    path.write_text("{not json", encoding="utf-8")
    store = mg.GuideStore(str(path))
    assert store.routes == {}
    guide, app = mg.Guide(store), _app()
    _backed_up(app)
    _look(guide, app)
    assert "src.sentinelone.net → dst.sentinelone.net" in path.read_text(
        encoding="utf-8")


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX modes")
def test_the_progress_file_is_owner_only_and_holds_no_token(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _backed_up(app)
    _look(guide, app)
    path = tmp_path / "migration_guide.json"
    assert os.stat(path).st_mode & 0o077 == 0
    assert "SECRET-TOKEN" not in path.read_text(encoding="utf-8")


# ── hand-offs ──────────────────────────────────────────────────────────

def test_the_first_look_announces_nothing(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _backed_up(app)
    assert _look(guide, app) == []


def test_finishing_a_step_is_announced_once(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _look(guide, app)
    _backed_up(app)
    assert _look(guide, app) == [("done", "backup")]
    assert _look(guide, app) == []


def test_running_a_step_again_is_not_announced(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _backed_up(app)
    _look(guide, app)
    _backed_up(app, path="/tmp/s1-backup-2.json")
    assert _look(guide, app) == []


def test_connecting_the_second_console_is_announced(tmp_path):
    guide, app = _guide(tmp_path), _app(dest=None)
    _look(guide, app)
    app.dest_api = _api(DST)
    assert _look(guide, app) == [("done", "connect")]


def test_switching_to_another_destination_is_quiet(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _look(guide, app)
    _backed_up(app)
    app.dest_api = _api(OTHER)
    assert _look(guide, app) == []


def test_a_problem_is_announced_once(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _look(guide, app)
    _preflighted(app, "fail")
    assert _look(guide, app) == [("attention", "preflight")]
    assert _look(guide, app) == []


# ── a step that is still running ───────────────────────────────────────

@pytest.mark.parametrize("key", RUNNABLE)
def test_a_step_still_running_shows_running_never_done(tmp_path, key):
    guide, app = _guide(tmp_path), _app()
    _look(guide, app)
    _running(app, key)
    assert _look(guide, app) == []
    assert guide.state(key) == "running" and guide.focus().key == key
    assert key not in guide.store.record(guide.route)["steps"]
    later = _guide(tmp_path)
    _look(later, _app())
    assert later.state(key) == "todo"


def test_a_run_that_finishes_is_handed_off_even_the_second_time(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _validated(app)
    _look(guide, app)
    _running(app, "validate")
    assert _look(guide, app) == []
    _running(app, "validate", on=False)
    _validated(app, when=T2)
    assert _look(guide, app) == [("done", "validate")]


def test_a_backup_taken_again_shows_running_not_the_old_one(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _backed_up(app)
    _look(guide, app)
    _running(app, "backup")
    _look(guide, app)
    assert guide.state("backup") == "running"
    assert guide.focus().key == "backup" and guide.next().key == "preflight"
    assert guide.done_count() == 2              # progress doesn't dip


def test_a_run_that_fails_becomes_a_problem_not_a_tick(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _look(guide, app)
    _running(app, "restore")
    _look(guide, app)
    _running(app, "restore", on=False)
    _restored(app, run_failed=True)
    assert _look(guide, app) == [("attention", "restore")]
    assert guide.state("restore") == "attention"


def test_a_stopped_validation_goes_back_to_todo(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _look(guide, app)
    _running(app, "validate")
    _look(guide, app)
    _running(app, "validate", on=False)
    assert _look(guide, app) == []
    assert guide.state("validate") == "todo"


def test_work_on_the_other_console_is_not_this_step_running(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _look(guide, app)
    app.pages["Backup Source"]._console_var = _Var("DESTINATION")
    _running(app, "backup")
    _running(app, "restore")
    app.pages["Restore to Dest"]._report_meta["dest_url"] = SRC
    _look(guide, app)
    assert guide.state("backup") == guide.state("restore") == "todo"


def test_the_page_mark_shows_work_in_progress(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _preflighted(app, "fail")
    _running(app, "preview")
    _look(guide, app)
    assert guide.page_mark("Restore to Dest") == ("…", "run")


def test_a_check_still_running_is_not_missing_from_the_gate(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _preflighted(app)
    _previewed(app)
    _look(guide, app)
    _running(app, "preflight")                  # checking again
    _look(guide, app)
    assert guide.gate_message("restore") == ""


# ── asking before the risky steps ──────────────────────────────────────

def test_restore_asks_when_pre_flight_or_preview_is_missing(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _backed_up(app)
    _look(guide, app)
    both = guide.gate_message("restore")
    assert "Pre-flight" in both and "Preview" in both
    assert guide.gate_step("restore") == "preflight"

    _preflighted(app)
    _look(guide, app)
    one = guide.gate_message("restore")
    assert "Preview" in one and "Pre-flight" not in one
    assert guide.gate_step("restore") == "preview"

    _previewed(app)
    _look(guide, app)
    assert guide.gate_message("restore") == ""


def test_restore_asks_only_once_per_migration(tmp_path):
    guide = _guide(tmp_path)
    _look(guide, _app())
    guide.acknowledge("restore")
    assert guide.gate_message("restore") == ""
    later = _guide(tmp_path)
    _look(later, _app())
    assert later.gate_message("restore") == ""


def test_a_rollback_or_second_restore_is_not_held_up(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _restored(app)
    _look(guide, app)
    assert guide.gate_message("restore") == ""


def test_agents_wait_for_a_validated_destination(tmp_path):
    guide, app = _guide(tmp_path), _app()
    _look(guide, app)
    assert "restored" in guide.gate_message("agents")
    _restored(app)
    _look(guide, app)
    message = guide.gate_message("agents")
    assert "validated" in message and "Run Validation" in message
    _validated(app)
    _look(guide, app)
    assert guide.gate_message("agents") == ""


def test_nothing_is_asked_without_both_consoles(tmp_path):
    guide = _guide(tmp_path)
    _look(guide, _app(dest=None))
    assert guide.gate_message("restore") == guide.gate_message("agents") == ""


# ── wired into the pages ───────────────────────────────────────────────

class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class _Sink:
    def __getattr__(self, _name):
        return lambda *a, **kw: None


class _Gate:
    def __init__(self, answer):
        self.answer, self.asked = answer, []

    def allow(self, gate):
        self.asked.append(gate)
        return self.answer


def _start_restore(monkeypatch, answer, target="DESTINATION", **kwargs):
    import pages

    class Starter:
        _start_restore = pages.RestorePage._start_restore
        _scope_filters = pages.RestorePage._scope_filters

        def __init__(self):
            self.backup_data = [
                {"type": "account", "path": "Acme/",
                 "account": {"name": "Acme"}, "data": {}},
                {"type": "site", "path": "Acme/HQ", "account": {
                    "name": "Acme"}, "site": {"name": "HQ"}, "data": {}}]
            self.app = types.SimpleNamespace(
                cfg=types.SimpleNamespace(get_by_role=lambda role: None),
                guide=_Gate(answer))
            self._console_var = _Var(target)
            self.restore_level_vars = {
                "global": _Var(False), "accounts": _Var(True),
                "sites": _Var(True), "groups": _Var(True)}
            self.restore_acct = _Var("")
            self.restore_site = _Var("")
            self.restore_group = _Var("")
            self.restore_vars = {"policy": _Var(True)}
            self._snapshot_var = _Var(False)
            self.ptable = _Sink()
            self.progress = _Sink()
            self.started = False

        def _get_restore_api(self):
            return types.SimpleNamespace(base_url=DST)

        def _check_account_name_match(self, api):
            return "ok"

        def _tick_timer(self):
            pass

        def _set_ui_running(self, running):
            self.started = running

    confirmed = []
    monkeypatch.setattr(pages.messagebox, "askyesno",
                        lambda *a, **k: confirmed.append(a) or True)
    monkeypatch.setattr(pages, "run_async", lambda *a, **kw: None)
    page = Starter()
    page._start_restore(**kwargs)
    return page, page.app.guide.asked, confirmed


def test_a_restore_asks_the_guide_before_its_confirmation(monkeypatch):
    page, asked, confirmed = _start_restore(monkeypatch, False, auto=False,
                                            confirm=True)
    assert asked == ["restore"] and confirmed == [] and not page.started
    page, asked, confirmed = _start_restore(monkeypatch, True, auto=False,
                                            confirm=True)
    assert asked == ["restore"] and len(confirmed) == 1 and page.started


def test_unattended_resume_and_source_restores_are_never_held(monkeypatch):
    for kwargs in ({"auto": True, "confirm": True}, {"auto": True}):
        page, asked, _ = _start_restore(monkeypatch, False, **kwargs)
        assert asked == [] and page.started
    page, asked, _ = _start_restore(monkeypatch, False, target="SOURCE",
                                    auto=False, confirm=True)
    assert asked == [] and page.started


def test_a_manual_agent_migration_asks_the_guide_first():
    import agent_migrator as am
    src = inspect.getsource(am.AgentMigratorPage._run_live)
    gate = src.index('guide.allow("agents")')
    assert gate < src.index('"Migrate for real"')
    condition = src[src.rindex("if", 0, gate):gate]
    assert "not scheduled" in condition and '"file"' in condition


def test_backups_record_the_console_they_came_from():
    import pages
    src = inspect.getsource(pages.BackupPage._start)
    assert "self.app._last_backup_url" in src


def test_the_manifest_export_is_recorded():
    import pages
    src = inspect.getsource(pages.ValidationPage._export_manifest)
    assert "self._manifest_exported" in src


def test_the_running_flags_the_guide_reads_are_set_by_the_pages():
    """The guide reads these attributes; renaming one would silently
    stop it seeing that work run."""
    import agent_migrator as am
    import pages
    backup = inspect.getsource(pages.BackupPage)
    assert "self._timer_running = True" in backup
    assert 'StringVar(value="SOURCE")' in backup
    restore = inspect.getsource(pages.RestorePage)
    for flag in ('self._run_mode = "running"', "self._preflighting = True",
                 "self._previewing = True", '"dest_url": api.base_url'):
        assert flag in restore
    running = inspect.getsource(pages.ValidationPage._set_running)
    assert "self._running = running" in running
    agents = inspect.getsource(am.AgentMigratorPage)
    assert 'self._busy = "check"' in agents
    assert 'self._busy = "live"' in agents


class _Control:
    def __init__(self, state="normal", shown=True):
        self.state, self.shown = state, shown

    def cget(self, _name):
        return self.state

    def winfo_ismapped(self):
        return self.shown


def test_show_me_picks_the_control_on_screen_and_enabled(tmp_path):
    app = _app()
    page = app.pages["Restore to Dest"]
    page._preflight_btn, page._browse_btn = _Control(shown=False), _Control()
    ctl = mg.GuideController(
        app, mg.GuideStore(str(tmp_path / "migration_guide.json")))
    assert ctl._target("preflight") is page._browse_btn      # no backup yet
    page._preflight_btn.shown = True
    assert ctl._target("preflight") is page._preflight_btn
    page._resume_btn = _Control(shown=False)
    page._start_btn = _Control(state="disabled")
    assert ctl._target("restore") is page._browse_btn


def test_the_app_builds_and_starts_the_guide():
    src = _read("app.py")
    assert "GuideController(self)" in src
    build = src.split("def _build(self):", 1)[1].split("\n    def ", 1)[0]
    for call in ("build_header(", "add_nav_mark(", "build_card(",
                 "build_bar(", "build_toast("):
        assert f"self.guide.{call}" in build
    show = src.split("def _show(self, label):", 1)[1].split("\n    def ", 1)[0]
    assert "self.guide.on_page(label)" in show
    init = src.split("class App(ctk.CTk):", 1)[1].split("\n    def ", 2)[1]
    assert init.index('self.connect("destination")') < init.index(
        "self.guide.start()")


# ── on screen (needs a display) ────────────────────────────────────────

@pytest.fixture
def ui(tmp_path):
    import customtkinter as ctk
    try:
        root = ctk.CTk()
    except Exception as exc:
        pytest.skip(f"Tk unavailable: {exc}")
    root.withdraw()
    app = _app()
    app.after, app.after_cancel = root.after, root.after_cancel
    app.shown = []
    ctl = mg.GuideController(
        app, mg.GuideStore(str(tmp_path / "migration_guide.json")))
    app.guide = ctl

    def show(label):
        app.shown.append(label)
        ctl.on_page(label)

    app._show = show
    side = ctk.CTkFrame(root)
    side.pack(side="left", fill="y")
    ctl.build_header(side)
    for page in mg.GUIDED_PAGES:
        mark = ctk.CTkLabel(side, text="")
        mark.pack()
        ctl.add_nav_mark(page, mark)
    ctl.build_card(side)
    right = ctk.CTkFrame(root)
    right.pack(side="left", fill="both", expand=True)
    content = ctk.CTkFrame(right)
    content.pack(side="top", fill="both", expand=True)
    ctk.CTkLabel(content, text="page").pack()
    ctl.build_bar(right, before=content)
    ctl.build_toast(right, over=content)
    ctl.on_page("Connections")
    ctl.start(interval=0)
    root.update_idletasks()
    yield types.SimpleNamespace(app=app, ctl=ctl, root=root)
    root.destroy()


def _text(widget):
    return widget.cget("text")


def _pump(ui, until, seconds=2.0):
    end = time.monotonic() + seconds
    while not until() and time.monotonic() < end:
        ui.root.update()
        time.sleep(0.005)


def test_the_card_names_the_next_step_and_goes_there(ui):
    card = ui.ctl._card
    assert _text(card["eyebrow"]) == "NEXT · STEP 2 OF 9"
    assert _text(card["title"]) == "Back up the source"
    assert _text(card["go"]) == "Go ▸"
    ui.ctl.go()
    assert ui.app.shown == ["Backup Source"]
    assert _text(card["go"]) == "Show me"


def test_the_sidebar_marks_follow_the_work(ui):
    marks = {page: _text(label) for page, label in ui.ctl._marks.items()}
    assert marks["Connections"] == "✓" and marks["Backup Source"] == "●"
    assert marks["Restore to Dest"] == ""
    assert _text(ui.ctl._count) == "1 of 9"
    _backed_up(ui.app)
    _preflighted(ui.app)
    ui.ctl.refresh()
    assert _text(ui.ctl._marks["Restore to Dest"]) == "1/3"
    assert _text(ui.ctl._count) == "3 of 9"


def test_the_strip_shows_on_migration_pages_only(ui):
    bar = ui.ctl._bar
    ui.ctl.on_page("Backup Source")
    assert bar["frame"].winfo_manager() == "pack"
    assert "click ▶ Start Backup" in _text(bar["text"])
    assert _text(bar["go"]) == "Show me"
    ui.ctl.on_page("Connections")
    assert "on Backup Source" in _text(bar["text"])
    assert _text(bar["go"]) == "Take me there ▸"
    ui.ctl.on_page("Agents")
    assert bar["frame"].winfo_manager() == ""


def test_the_strip_can_be_put_away_until_the_next_step(ui):
    bar = ui.ctl._bar
    ui.ctl.dismiss()
    assert bar["frame"].winfo_manager() == ""
    _backed_up(ui.app)
    ui.ctl.refresh()
    assert bar["frame"].winfo_manager() == "pack"
    assert "pre-flight" in _text(bar["text"])


def test_finishing_a_step_slides_in_the_hand_off(ui):
    toast = ui.ctl._toast
    assert toast["frame"].winfo_manager() == ""
    _backed_up(ui.app)
    ui.ctl.refresh()
    assert toast["frame"].winfo_manager() == "place"
    assert "Backup saved" in _text(toast["head"])
    assert "Run the pre-flight check" in _text(toast["body"])
    assert "on Restore to Dest" in _text(toast["body"])
    ui.ctl._toast_go()
    assert toast["frame"].winfo_manager() == ""
    assert ui.app.shown == ["Restore to Dest"]


def test_the_hand_off_waits_for_a_run_to_finish(ui):
    toast = ui.ctl._toast
    ui.app._busy = True
    _backed_up(ui.app)
    ui.ctl.refresh()
    assert toast["frame"].winfo_manager() == ""
    ui.ctl.go()
    assert ui.app.shown == []                # no page switch mid-run
    ui.app._busy = False
    ui.ctl.refresh()
    assert toast["frame"].winfo_manager() == "place"


def test_marking_done_moves_on_and_start_over_resets(ui, monkeypatch):
    monkeypatch.setattr(mg.messagebox, "askyesno", lambda *a, **k: True)
    ui.ctl.mark_next()
    assert _text(ui.ctl._card["title"]) == "Run the pre-flight check"
    ui.ctl.start_over()
    assert _text(ui.ctl._card["title"]) == "Back up the source"


def test_the_checklist_lists_every_step_and_ticks_by_hand(ui):
    ui.ctl.toggle_list()
    rows = ui.ctl._card["rows"]
    assert [_text(r["name"]) for r in rows] == [s.short for s in mg.STEPS]
    assert _text(rows[0]["glyph"]) == "✓" and _text(rows[1]["glyph"]) == "●"
    assert rows[0]["flip"].winfo_manager() == ""     # connecting is live
    ui.ctl.flip("preview")
    assert _text(rows[3]["glyph"]) == "✓" and _text(rows[3]["flip"]) == \
        "Undo"
    ui.ctl.flip("preview")
    assert _text(rows[3]["glyph"]) == "○"


def test_a_finished_migration_says_so_and_puts_the_strip_away(ui):
    ui.ctl.on_page("Migration Validation")
    _everything(ui.app)
    ui.ctl.refresh()
    assert _text(ui.ctl._card["title"]) == "Migration complete"
    assert ui.ctl._card["again"].winfo_manager() == "grid"
    assert ui.ctl._bar["frame"].winfo_manager() == ""
    assert {_text(m) for m in ui.ctl._marks.values()} == {"✓"}


def test_the_guide_builds_its_widgets_once(ui):
    def count(widget):
        return 1 + sum(count(c) for c in widget.winfo_children())

    ui.ctl.toggle_list()
    before = count(ui.root)
    for i in range(8):
        _backed_up(ui.app, path=f"/tmp/s1-backup-{i}.json")
        _preflighted(ui.app, "fail" if i % 2 else "pass", at=f"t{i}")
        ui.ctl.on_page(mg.GUIDED_PAGES[i % len(mg.GUIDED_PAGES)])
        ui.ctl.refresh()
    assert count(ui.root) == before


def test_an_unchanged_state_redraws_nothing(ui):
    calls = []
    for widget in (ui.ctl._card["title"], ui.ctl._card["hint"],
                   ui.ctl._bar["text"], ui.ctl._count):
        real = widget.configure
        widget.configure = (lambda real=real, **kw: calls.append(kw)
                            or real(**kw))
    for _ in range(5):
        ui.ctl.refresh()
    assert calls == []


def test_the_card_and_strip_say_a_step_is_running(ui):
    card, bar = ui.ctl._card, ui.ctl._bar
    _running(ui.app, "backup")
    ui.ctl.on_page("Backup Source")
    assert _text(card["eyebrow"]) == "RUNNING · STEP 2 OF 9"
    assert card["mark"].winfo_manager() == ""        # nothing to tick
    assert card["go"].winfo_manager() == ""          # already here
    assert card["btns"].winfo_manager() == ""        # no empty band left
    assert _text(bar["badge"]) == "RUNNING · 2/9"
    assert "Start Backup" not in _text(bar["text"])
    assert bar["go"].winfo_manager() == ""
    assert _text(ui.ctl._marks["Backup Source"]) == "…"
    ui.ctl.on_page("Connections")
    assert card["btns"].winfo_manager() == "grid"
    assert card["go"].winfo_manager() == "grid" and _text(card["go"]) == \
        "Go ▸"
    assert "on Backup Source" in _text(bar["text"])
    assert _text(bar["go"]) == "Take me there ▸"
    ui.ctl.go()
    assert ui.app.shown == ["Backup Source"]
    _running(ui.app, "backup", on=False)
    _backed_up(ui.app)
    ui.ctl.refresh()
    assert _text(card["eyebrow"]) == "NEXT · STEP 3 OF 9"
    assert "Backup saved" in _text(ui.ctl._toast["head"])


def test_the_checklist_shows_a_running_step_and_cannot_tick_it(ui):
    ui.ctl.toggle_list()
    row = ui.ctl._card["rows"][mg.STEP_KEYS.index("validate")]
    _running(ui.app, "validate")
    ui.ctl.refresh()
    assert _text(row["glyph"]) == "…" and row["flip"].winfo_manager() == ""


def test_show_me_blinks_a_control_then_puts_it_back(ui):
    import customtkinter as ctk
    button = ctk.CTkButton(ui.root, text="x", border_width=1,
                           border_color=mg.theme.BORDER)
    widths = []
    real = button.configure
    button.configure = (lambda **kw: widths.append(kw.get("border_width"))
                        or real(**kw))
    ui.ctl.flash(button, times=4, every=1)
    _pump(ui, lambda: not ui.ctl._flashing)
    assert widths == [3, 1, 3, 1]
    assert button.cget("border_width") == 1


def test_show_me_leaves_a_control_its_page_restyled_alone(ui):
    import customtkinter as ctk
    button = ctk.CTkButton(ui.root, text="x", border_width=1,
                           border_color=mg.theme.BORDER)
    ui.ctl.flash(button, times=6, every=1)
    button.configure(border_width=2, border_color=mg.theme.GREEN)
    _pump(ui, lambda: not ui.ctl._flashing)
    assert button.cget("border_width") == 2


def test_the_restore_gate_asks_once_and_remembers(ui, monkeypatch):
    answers = [False, True]
    asked = []
    monkeypatch.setattr(mg.messagebox, "askyesno",
                        lambda *a, **k: asked.append(a) or answers.pop(0))
    _backed_up(ui.app)
    ui.ctl.refresh()
    assert ui.ctl.allow("restore") is False
    assert ui.ctl.allow("restore") is True
    assert ui.ctl.allow("restore") is True
    assert len(asked) == 2
