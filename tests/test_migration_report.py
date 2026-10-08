import ast
import inspect
import json
import os
import re
import sys
import textwrap
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import migration_report as mr
from migration_report import (build_migration_report,
                              render_migration_report_html)

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
TABS = ["overview", "backup", "restore", "failures", "landed", "gaps",
        "readiness", "next", "log", "about"]


def _row(element, item, status, reason="", node="Acme/Berlin", scope="site",
         kind=""):
    return {"node": node, "scope": scope, "element": element, "kind": kind,
            "item": item, "status": status, "reason": reason}


def _meta(**extra):
    meta = {"source_url": "https://src.example.net",
            "dest_url": "https://dst.example.net",
            "dest_console": "Prod EU", "customer": "Acme Corp",
            "elements": ["excl", "star"], "scope": "All nodes",
            "start_time": "2026-10-08T09:00:00+00:00",
            "end_time": "2026-10-08T09:30:00+00:00",
            "app_version": "2.7.0"}
    meta.update(extra)
    return meta


def _run(ledger=None, nodes=None, log=None, **meta):
    return {"meta": _meta(**meta), "nodes": nodes or [],
            "ledger": ledger or [], "log": log or []}


def _explain(element, error, code):
    if "Validation Error" in error:
        return {"what": "Exclusion value rejected", "why": "Bad path.",
                "fix": "Edit the path.", "severity": "error"}
    if "expiration" in error:
        return {"what": "STAR expiration out of range", "why": "Too far.",
                "fix": "Shorten it.", "severity": "warning"}
    return {"what": f"Unrecognised error from '{element}'", "why": "",
            "fix": "", "severity": "error"}


def _mixed_ledger():
    rows = [_row("excl", f"C:\\ok{i}.exe", "created", kind="path")
            for i in range(8)]
    rows.append(_row("excl", "C:\\bad.exe", "failed",
                     "Validation Error :: data: value", kind="path"))
    rows.append(_row("policy", "policy", "exists"))
    rows.append(_row("star", "<script>alert(1)</script>", "failed",
                     "→ 400 expiration date must be within the next 6 months",
                     node="Acme/Berlin/Servers", scope="group"))
    rows.append(_row("tags-fw", "corp", "inherited",
                     node="Acme/Berlin/Servers", scope="group"))
    rows.append(_row("star", "Manual rule", "manual", "no public API",
                     node="Acme/Berlin/Servers", scope="group"))
    return rows


def _progress():
    return [
        {"path": "Acme", "type": "account", "status": "done", "num": 1},
        {"path": "Acme/Berlin", "type": "site", "status": "done",
         "detail": "8 created", "num": 2},
        {"path": "Acme/Berlin/Servers", "type": "group", "status": "done",
         "num": 3},
        {"path": "Acme/Paris", "type": "site", "status": "pending", "num": 4},
    ]


def _backup_nodes():
    meta = {"url": "https://src.example.net", "backupVersion": "gui-1.0",
            "systemInformation": {"release": "24.1"},
            "run": {"started": "2026-10-07T08:00:00+00:00",
                    "finished": "2026-10-07T08:05:00+00:00",
                    "seconds": 300.0, "toolVersion": "2.7.0",
                    "elements": ["star", "exclusions"], "cancelled": False,
                    "nodesPlanned": 3, "nodesSaved": 2,
                    "failedNodes": [{"path": "Acme/Tokyo", "type": "site",
                                     "error": "timeout"}],
                    "runBy": {"fullName": "Ran", "email": "ran@example.net"}}}
    return [
        {"type": "account", "path": "Acme", "backupMetadata": meta,
         "data": {"star": [{"name": "s1"}, {"name": "s2"}]},
         "backupResults": {"STAR rules": 2, "Exclusions": "N/A (403)"}},
        {"type": "site", "path": "Acme/Berlin",
         "data": {"exclusions": {"path": [{"value": "/a"}]}},
         "backupResults": {"STAR rules": "ERR: 500", "Exclusions": 1,
                           "Firewall": "No API"}},
    ]


def _summarize(data):
    out = []
    if data.get("star"):
        out.append(("star_rules", len(data["star"]), []))
    paths = (data.get("exclusions") or {}).get("path") or []
    if paths:
        out.append(("excl/path", len(paths), []))
    out.append(("firewall_config", 1, []))
    return out


def _cat_label(cat):
    return {"star_rules": "STAR custom detection rules",
            "excl/path": "Exclusions · path",
            "firewall_config": "Firewall config (present?)"}.get(cat, cat)


def _validation(when):
    return {"meta": {"when": when, "src_url": "https://src.example.net",
                     "dst_url": "https://dst.example.net"},
            "results": [
                {"path": "Acme", "type": "account", "matched": True,
                 "diffs": 0, "rows": []},
                {"path": "Acme/Berlin", "type": "site", "matched": True,
                 "diffs": 1, "rows": [
                     {"cat": "star_rules", "status": "diff", "src": 2,
                      "dst": 1, "missing": ["s2"], "extra": [],
                      "what": "Missing rule", "why": "", "fix": ""}]},
                {"path": "Acme/Paris", "type": "site", "matched": False},
            ]}


def _build(**kwargs):
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("explain", _explain)
    runs = kwargs.pop("runs", None) or [_run(_mixed_ledger())]
    return build_migration_report(runs, **kwargs)


def test_items_scopes_and_outcomes_add_up():
    report = _build(progress=_progress())
    k = report["kpis"]
    assert (k["items"], k["created"], k["exists"], k["failed"],
            k["manual"]) == (12, 8, 1, 2, 1)
    assert (k["restored"], k["missing"], k["success_rate"]) == (9, 3, 75.0)
    outcomes = {n["path"]: n["outcome"] for n in report["restore"]["nodes"]}
    assert outcomes == {"Acme": "restored", "Acme/Berlin": "partial",
                        "Acme/Berlin/Servers": "partial",
                        "Acme/Paris": "not run"}
    sites = {c["title"]: c for c in report["restore"]["sites"]}
    assert [g["name"] for g in sites["Berlin"]["groups"]] == ["Servers"]
    assert sites["Paris"]["outcome"] == "not run"


def test_verdict_follows_the_worst_thing_that_happened():
    clean = [_row("excl", "C:\\a.exe", "created")]
    assert _build(runs=[_run(clean)])["verdict"]["key"] == "success"
    assert _build()["verdict"]["key"] == "warnings"
    assert _build(progress=_progress())["verdict"]["key"] == "stopped"
    assert _build(runs=[_run(clean, cancelled=True)])["verdict"]["key"] == \
        "stopped"
    failed = _build(runs=[_run(clean, run_failed=True,
                               error="token expired")])
    assert failed["verdict"]["key"] == "failed"
    assert "token expired" in failed["verdict"]["detail"]


def test_resume_keeps_finished_scopes_and_replaces_retried_ones():
    first = _run(
        [_row("excl", "a", "created", node="Acme/Berlin"),
         _row("excl", "b", "failed", "boom", node="Acme/Paris")],
        nodes=[{"path": "Acme/Berlin", "type": "site", "status": "done",
                "failed_items": []},
               {"path": "Acme/Paris", "type": "site", "status": "error",
                "failed_items": [{"element": "excl", "name": "b",
                                  "error": "boom"}]}],
        cancelled=True, end_time="2026-10-08T09:10:00+00:00")
    second = _run(
        [_row("excl", "b", "created", node="Acme/Paris")],
        nodes=[{"path": "Acme/Paris", "type": "site", "status": "done",
                "failed_items": []}],
        resumed=True, start_time="2026-10-08T10:00:00+00:00",
        end_time="2026-10-08T10:05:00+00:00")
    report = _build(runs=[first, second])
    k = report["kpis"]
    assert (k["created"], k["failed"]) == (2, 0)
    assert report["failures"]["total"] == 0
    assert [r["outcome"] for r in report["restore"]["runs"]] == [
        "stopped", "completed"]
    assert k["active_seconds"] == 15 * 60
    assert report["verdict"]["key"] == "success"


def test_failures_are_grouped_by_cause_and_not_double_counted():
    nodes = [{"path": "Acme/Berlin", "type": "site", "status": "done",
              "failed_items": [
                  {"element": "excl", "name": "C:\\bad.exe",
                   "error": "Validation Error :: data: value"},
                  {"element": "excl", "name": "C:\\worse.exe",
                   "error": "Validation Error :: data: value"}]}]
    report = _build(runs=[_run(_mixed_ledger(), nodes=nodes)])
    fails = report["failures"]
    assert fails["total"] == 3
    by_what = {g["what"]: g for g in fails["groups"]}
    assert by_what["Exclusion value rejected"]["count"] == 2
    assert by_what["STAR expiration out of range"]["severity"] == "warning"
    assert fails["groups"][0]["severity"] == "error"


def test_a_scope_that_could_not_be_created_is_explained():
    ledger = [_row("(node)", "Acme/Paris", "failed",
                   "Accounts.create forbidden", node="Acme/Paris")]
    report = _build(runs=[_run(ledger)])
    (group,) = report["failures"]["groups"]
    assert group["what"] == "Scope could not be created on the destination"
    assert report["failures"]["scopes"] == 1
    assert any("could not be created" in r["title"]
               for r in report["recommendations"])
    assert {n["path"]: n["outcome"] for n in report["restore"]["nodes"]} == \
        {"Acme/Paris": "failed"}


def test_progress_states_map_to_scope_outcomes():
    progress = [
        {"path": "A/s1", "type": "site", "status": "running"},
        {"path": "A/s2", "type": "site", "status": "skipped",
         "detail": "Cancelled by user"},
        {"path": "A/s3", "type": "site", "status": "skipped",
         "detail": "Site deleted on source"},
        {"path": "A/s4", "type": "site", "status": "error", "detail": "boom"},
    ]
    report = _build(runs=[_run([])], progress=progress)
    assert [n["outcome"] for n in report["restore"]["nodes"]] == [
        "interrupted", "not run", "skipped", "failed"]
    assert report["kpis"]["nodes_failed"] == 2


def test_failed_scopes_without_item_rows_are_still_called_out():
    progress = [{"path": "A/s1", "type": "site", "status": "done"},
                {"path": "A/s2", "type": "site", "status": "error",
                 "detail": "boom"}]
    report = _build(runs=[_run([_row("excl", "x", "created", node="A/s1")])],
                    progress=progress)
    assert report["verdict"]["key"] == "warnings"
    assert "1 scope(s) failed" in report["verdict"]["detail"]
    assert "0 of" not in report["verdict"]["detail"]
    assert any(r["tab"] == "restore" and "failed or were interrupted"
               in r["title"] for r in report["recommendations"])


def test_backup_tab_uses_the_run_record_reads_and_inventory():
    report = _build(backup=_backup_nodes(), summarize=_summarize,
                    cat_label=_cat_label,
                    backup_file={"name": "acme.json", "path": "/tmp/a.json",
                                 "size": 2048, "sha256": "ab" * 32})
    b = report["backup"]
    assert b["has_run_record"] and b["seconds"] == 300.0
    assert b["by"] == "Ran <ran@example.net>"
    assert b["console_version"] == "release 24.1"
    assert b["item_total"] == 3
    inventory = {e["label"]: e for e in b["inventory"]}
    assert inventory["STAR custom detection rules"]["items"] == 2
    assert inventory["Firewall config"]["presence"] is True
    reads = b["reads"]
    assert (reads["errors"], reads["denied"]) == (1, 1)
    assert reads["unsupported"] == ["Firewall"]
    assert b["failed_nodes"][0]["path"] == "Acme/Tokyo"
    assert any("failed to back up" in r["title"]
               for r in report["recommendations"])


def test_an_old_backup_without_a_run_record_is_flagged():
    nodes = [{"type": "site", "path": "Acme/Berlin",
              "backupMetadata": {"url": "https://src.example.net"},
              "data": {}}]
    report = _build(backup=nodes)
    assert report["backup"]["has_run_record"] is False
    assert "Older backup file" in render_migration_report_html(report)


def test_validation_summary_and_staleness():
    fresh = _build(validation=_validation("2026-10-08T11:00:00+00:00"))
    v = fresh["validation"]
    assert (v["nodes"], v["identical"], v["differing"]) == (3, 1, 1)
    assert v["missing_nodes"] == [{"path": "Acme/Paris", "type": "site"}]
    assert v["diffs"][0]["missing"] == ["s2"] and not v["stale"]
    stale = _build(validation=_validation("2026-10-08T08:00:00+00:00"))
    assert stale["validation"]["stale"]
    assert _build(validation={"results": []})["validation"] is None


def test_a_clean_validated_migration_has_nothing_to_fix():
    validation = {"meta": {"when": "2026-10-08T11:00:00+00:00"},
                  "results": [{"path": "Acme/Berlin", "type": "site",
                               "matched": True, "diffs": 0, "rows": []}]}
    report = _build(runs=[_run([_row("excl", "C:\\a.exe", "created")])],
                    validation=validation,
                    preflight={"at": "2026-10-08T08:50:00+00:00",
                               "verdict": "pass", "checks": []})
    recs = report["recommendations"]
    assert recs[0]["title"] == "Nothing to fix"
    assert all(r["priority"] in ("low", "info") for r in recs)


def test_an_unfinished_restore_is_told_to_resume_first():
    first = _build(progress=_progress())["recommendations"][0]
    assert first["priority"] == "high" and "Resume" in first["title"]


def test_timeline_is_chronological():
    report = _build(backup=_backup_nodes(),
                    preview={"at": "2026-10-08T08:30:00+00:00",
                             "create": 5, "exists": 1})
    moments = [mr.parse_when(e["at"]) for e in report["timeline"]]
    assert moments == sorted(moments)
    assert report["timeline"][0]["title"] == "Backup started"
    assert report["timeline"][-1]["title"] == "This report generated"


def test_log_lines_are_classified_split_by_run_and_capped(monkeypatch):
    log = ["Starting restore", "✓ Acme done", "⚠ tag left out",
           "✗ STAR failed", "Item ERROR here"]
    report = _build(runs=[_run([], log=log)])
    assert [line["level"] for line in report["log"]] == [
        "info", "ok", "warn", "error", "error"]
    two = _build(runs=[_run([], log=["a"]), _run([], log=["b"])])
    assert [line["text"] for line in two["log"]] == [
        "═══ Run 1 ═══", "a", "═══ Run 2 ═══", "b"]
    monkeypatch.setattr(mr, "LOG_LINE_CAP", 3)
    capped = _build(runs=[_run([], log=log)])
    assert len(capped["log"]) == 3 and capped["log_total"] == 5


def test_large_item_lists_are_capped(monkeypatch):
    monkeypatch.setattr(mr, "SUCCESS_ROW_CAP", 5)
    ledger = [_row("excl", f"x{i}", "created") for i in range(20)]
    report = _build(runs=[_run(ledger)])
    assert len(report["successes"]["rows"]) == 5
    assert report["successes"]["row_total"] == 20
    assert "Showing the first 5 of 20 items" in \
        render_migration_report_html(report)


def test_model_is_json_serialisable():
    report = _build(backup=_backup_nodes(), summarize=_summarize,
                    cat_label=_cat_label, progress=_progress(),
                    validation=_validation("2026-10-08T11:00:00+00:00"),
                    preflight={"at": "2026-10-08T08:50:00+00:00",
                               "verdict": "warn",
                               "checks": [{"name": "Token", "status": "pass",
                                           "detail": "ok"}]},
                    preview={"at": "2026-10-08T08:30:00+00:00", "create": 5,
                             "exists": 1, "missing": 1, "nodes": 4,
                             "per_element": [{"label": "Firewall (present?)",
                                              "create": 1, "exists": 0}]})
    json.dumps(report)
    assert report["readiness"]["preview"]["per_element"][0]["label"] == \
        "Firewall"


def test_render_has_one_panel_per_tab():
    html = render_migration_report_html(_build(progress=_progress()))
    assert re.findall(r'data-tab="([a-z]+)"', html) == TABS
    for tab in TABS:
        assert f'id="tab-{tab}"' in html
    with_validation = render_migration_report_html(
        _build(validation=_validation("2026-10-08T11:00:00+00:00")))
    assert 'data-tab="validation"' in with_validation


def test_item_names_and_errors_are_escaped():
    html = render_migration_report_html(_build())
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_report_is_self_contained():
    html = render_migration_report_html(
        _build(backup=_backup_nodes(), progress=_progress()))
    assert not re.search(r"<(script|link|img|iframe)\b[^>]*\b(src|href)=",
                         html)
    assert '<table class="data-table">' in html


def test_every_in_page_link_has_a_target():
    html = render_migration_report_html(
        _build(progress=_progress(), backup=_backup_nodes(),
               backup_file={"name": "a.json", "sha256": "cd" * 32}))
    opens = set(re.findall(r'data-open="([^"]+)"', html))
    copies = set(re.findall(r'data-copy="([^"]+)"', html))
    assert opens and copies
    for target in opens | copies:
        assert f'id="{target}"' in html, target
    for tab in set(re.findall(r'data-goto="([^"]+)"', html)):
        assert f'id="tab-{tab}"' in html, tab


def test_an_empty_restore_still_renders():
    report = build_migration_report([], now=NOW)
    html = render_migration_report_html(report)
    assert html.startswith("<!DOCTYPE html>")
    assert html.rstrip().endswith("</html>")
    assert "No failures" in html and "No backup in this report" in html


def test_real_explainer_and_summariser_plug_in():
    from pages import _cat_label as real_label
    from pages import _summarize_node_payload, explain_error
    ledger = _mixed_ledger() + [
        _row("(node)", "Acme/Paris", "failed",
             "Accounts.create → 403 forbidden", node="Acme/Paris")]
    report = build_migration_report(
        [_run(ledger)], backup=_backup_nodes(), explain=explain_error,
        summarize=_summarize_node_payload, cat_label=real_label, now=NOW)
    assert report["failures"]["total"] == 3
    assert any(e["key"] == "star_rules" and e["items"] == 2
               for e in report["backup"]["inventory"])
    assert report["failures"]["scopes"] == 1
    node_group = next(g for g in report["failures"]["groups"]
                      if any(i["element"] == "(node)" for i in g["items"]))
    assert not node_group["what"].startswith("Unrecognised")
    render_migration_report_html(report)


def test_restore_screen_passes_only_inputs_the_model_accepts():
    import pages
    source = textwrap.dedent(
        inspect.getsource(pages.RestorePage._full_report_inputs))
    returns = [n.value for n in ast.walk(ast.parse(source))
               if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)]
    keys = {k.value for k in returns[-1].keys}
    params = set(inspect.signature(build_migration_report).parameters)
    assert "runs" in keys and keys <= params
    assert params - keys == {"explain", "summarize", "cat_label", "now"}
    export = inspect.getsource(pages.RestorePage._export_full_report)
    for wiring in ("explain=explain_error",
                   "summarize=_summarize_node_payload",
                   "cat_label=_cat_label",
                   "render_migration_report_html(report)"):
        assert wiring in export
