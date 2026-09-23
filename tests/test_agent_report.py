"""Tests for the rich agent-migration reports.

Two things are covered:

1. The pure report builders in agent_migrator (build_live_report /
   build_status_report / build_match_report) shape a run/status/plan into the
   structured dict the exporter renders. They are plain functions on plain
   dicts, so no console or window is needed.
2. export_utils.generate_migration_html turns that dict into a self-contained
   HTML document — with stat cards, badges, an info box, and (crucially) with
   every untrusted value HTML-escaped.

Plus a source guard: the passphrase option must warn that each fetch is
written to the source console's activity log.
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent_migrator as am  # noqa: E402
import export_utils as eu  # noqa: E402


# ── fixtures ─────────────────────────────────────────────────────────────

def _run(verified=True, stopped=False):
    """A finished live run with one moved agent and one failed agent."""
    return {
        "agents": [
            {"id": "a1", "Computer": "WIN-SRV-01", "OS": "Windows",
             "Account": "Acme", "Site": "HQ", "Group": "Servers",
             "Destination": "Acme/HQ/Servers", "Result": "moved",
             "Detail": "Confirmed.", "Agent ID": "a1"},
            {"id": "a2", "Computer": "WIN-SRV-02", "OS": "Windows",
             "Account": "Acme", "Site": "HQ", "Group": "Servers",
             "Destination": "Acme/HQ/Servers", "Result": "failed",
             "Detail": "The console reports the migration as failed.",
             "Agent ID": "a2"},
        ],
        "errors": ["Acme / HQ / Workstations: token missing"],
        "by_group": [{
            "row": {"Account": "Acme", "Site": "HQ", "Group": "Servers",
                    "Destination": "Acme/HQ/Servers"},
            "candidates": 2, "moved": 1, "errors": [],
        }],
        "groups": 1, "sent": 2, "affected": 1, "moved": 1, "pending": 0,
        "failed": 1, "stopped": stopped, "verified": verified,
    }


def _status(passphrase=None):
    row = {c: "" for c in am.AGENT_REPORT_COLUMNS}
    row.update({"Computer Name": "WIN-SRV-01", "Migration Status": "Migrated",
                "Site": "HQ", "Group": "Servers", "Agent ID": "a1",
                "Passphrase": passphrase if passphrase is not None
                else "not fetched"})
    return {
        "counts": {"Migrated": 1, "Pending": 0, "N/A": 0, "Failed": 0},
        "agents": [row],
        "decommissioned": [],
    }


def _plan():
    return {
        "accounts": 1, "ready": 1, "blocked": 1, "done": 0, "agents": 5,
        "empty_groups": 0,
        "rows": [
            {"Account": "Acme", "Site": "HQ", "Group": "Servers",
             "Destination": "Acme/HQ/Servers", "Agents": 5, "Status": "ready",
             "state": "ready", "reason": ""},
            {"Account": "Acme", "Site": "HQ", "Group": "Laptops",
             "Destination": "—", "Agents": 0, "Status": am.NO_MATCH_GROUP,
             "state": "blocked", "reason": "no same-named group"},
        ],
    }


# ── live report builder ──────────────────────────────────────────────────

def test_live_report_has_every_agent_and_failure_sections():
    rep = am.build_live_report(_run(), source="https://src.sentinelone.net",
                               map_path="/tmp/dest.json")
    titles = [s["title"] for s in rep["sections"]]
    assert "Every agent" in titles
    assert any("Did not migrate" in t for t in titles)
    assert any(s["title"] == "Errors" for s in rep["sections"])
    # flat feed drives Excel/CSV/JSON and must carry every agent
    assert rep["flat"]["columns"] == am.LIVE_COLUMNS + ["Agent ID"]
    assert len(rep["flat"]["rows"]) == 2
    # the agent table badges the Result column
    every = next(s for s in rep["sections"] if s["title"] == "Every agent")
    assert "Result" in every["badge_cols"]


def test_live_report_note_reflects_verification_and_stop():
    assert am.build_live_report(_run(verified=True))["note"] is None
    unverified = am.build_live_report(_run(verified=False))["note"]
    assert unverified and unverified["kind"] == "info"
    stopped = am.build_live_report(_run(stopped=True))["note"]
    assert stopped and stopped["kind"] == "warn"


# ── status report builder ────────────────────────────────────────────────

def test_status_report_warns_about_activity_log_when_passphrases_present():
    rep = am.build_status_report(_status(passphrase="s3cr3t-phrase"),
                                 console="https://src.sentinelone.net",
                                 scope="Acme", passphrases=True)
    note = rep["note"]
    assert note and note["kind"] == "danger"
    assert "activity log" in note["text"].lower()
    assert ("Passphrases included", "yes") in rep["info"]
    assert rep["flat"]["columns"] == am.AGENT_REPORT_COLUMNS


def test_status_report_clean_when_no_passphrases():
    rep = am.build_status_report(_status())
    assert rep["note"] is None
    assert ("Passphrases included", "no") in rep["info"]


# ── match report builder ─────────────────────────────────────────────────

def test_match_report_splits_ready_and_blocked():
    rep = am.build_match_report(_plan(), map_path="/tmp/dest.json")
    ready = next(s for s in rep["sections"] if s["title"] == "Will migrate")
    blocked = next(s for s in rep["sections"]
                   if s["title"] == "Will not migrate")
    assert len(ready["rows"]) == 1
    assert len(blocked["rows"]) == 1
    assert "Reason" in blocked["columns"]
    # flat export keeps state + reason for every scope
    assert rep["flat"]["rows"][1]["State"] == "blocked"


# ── HTML generator ───────────────────────────────────────────────────────

def test_html_is_self_contained_with_cards_and_badges():
    html = eu.generate_migration_html(am.build_live_report(_run()))
    assert html.startswith("<!DOCTYPE html>")
    assert "Agent Migration — Live Run" in html
    assert "stat-card" in html and "infobox" in html
    # Result cells are badged
    assert 'class="badge badge-green">moved' in html
    assert 'class="badge badge-red">failed' in html


def test_html_escapes_untrusted_values():
    run = _run()
    run["agents"][0]["Computer"] = "<script>alert(1)</script>"
    html = eu.generate_migration_html(am.build_live_report(run))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_html_renders_passphrase_danger_banner():
    html = eu.generate_migration_html(
        am.build_status_report(_status(passphrase="s3cr3t"), passphrases=True))
    assert 'class="banner danger"' in html
    assert "activity log" in html.lower()


def test_html_handles_empty_report():
    html = eu.generate_migration_html({})
    assert html.startswith("<!DOCTYPE html>")
    assert "</html>" in html


# ── flat CSV writer ──────────────────────────────────────────────────────

def test_flat_csv_writes_header_and_rows(tmp_path):
    path = str(tmp_path / "out.csv")
    n = eu._write_flat_csv(path, ["A", "B"],
                           [{"A": "1", "B": "x"}, {"A": "2", "B": "y"}])
    assert n == 2
    text = open(path, encoding="utf-8-sig").read()
    assert text.splitlines()[0] == "A,B"
    assert "1,x" in text and "2,y" in text


# ── the exporter exists and offers the rich formats ──────────────────────

def test_export_agent_report_is_wired():
    assert hasattr(eu, "export_agent_report")
    # HTML default, plus Excel / CSV / JSON
    src = inspect.getsource(eu.export_agent_report)
    for ext in ('*.html', '*.xlsx', '*.csv', '*.json'):
        assert ext in src
    assert 'defaultextension=".html"' in src


# ── source guard: the passphrase option warns about the activity log ─────

def test_passphrase_option_warns_about_activity_log():
    page = am.AgentMigratorPage
    toggle = inspect.getsource(page._on_passphrase_toggle)
    run = inspect.getsource(page._run_status)
    build = inspect.getsource(page._build_panel_status)
    assert "activity log" in toggle.lower()
    assert "activity log" in run.lower()
    assert "activity log" in build.lower()
    # and the run asks for explicit confirmation before fetching them
    assert "askyesno" in run and "passphrase" in run.lower()
