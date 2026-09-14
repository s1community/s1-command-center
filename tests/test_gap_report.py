"""Migration Gap Report — the per-item 'what did NOT migrate' document.

The restore results table only ever carried counts ("43 new"), so a backup
of 45 exclusions that restored 43 gave the operator no way to find the
missing two. RestorePage._run_restore now writes one NAMED row per item to
`self._item_ledger` and export_utils turns that into a tabbed document.

These tests cover both halves:
  * the pure report builder / renderers (grouping, counts, tabs, workbook)
  * source guards proving every restore path that reports a result also
    records ledger rows, and only uses declared statuses.
"""
import ast
import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import export_utils
from export_utils import (GAP_INFO_STATUSES, GAP_MISSING_STATUSES,
                          GAP_RESTORED_STATUSES, GAP_STATUSES,
                          build_gap_report, gap_element_title,
                          gap_report_rows, generate_gap_excel,
                          generate_gap_html)
import pages
from pages import RestorePage


def _row(element, item, status, reason="", node="Acme/Berlin", scope="site",
         kind=""):
    return {"node": node, "scope": scope, "element": element, "kind": kind,
            "item": item, "status": status, "reason": reason}


# ── The headline scenario: 45 backed up, 43 restored ───────────────────

def _forty_five_exclusions():
    ledger = [_row("excl", f"C:\\app{i}.exe", "created", kind="path")
              for i in range(43)]
    ledger.append(_row("excl", "C:\\bad\\one.exe", "failed",
                       "Validation Error :: data: value", kind="path"))
    ledger.append(_row("excl", "C:\\bad\\two.exe", "failed",
                       "Validation Error :: data: value", kind="path"))
    return ledger


def test_45_backed_up_43_restored_names_the_missing_two():
    report = build_gap_report(_forty_five_exclusions())
    (excl,) = report["elements"]
    assert excl["total"] == 45
    assert excl["restored"] == 43
    assert excl["missing"] == 2
    missing = [r["item"] for r in excl["rows"]
               if r["status"] in GAP_MISSING_STATUSES]
    assert missing == ["C:\\bad\\one.exe", "C:\\bad\\two.exe"]


def test_missing_items_are_listed_before_the_ones_that_landed():
    report = build_gap_report(_forty_five_exclusions())
    rows = report["elements"][0]["rows"]
    assert rows[0]["status"] == "failed" and rows[1]["status"] == "failed"


def test_totals_split_restored_from_not_migrated():
    ledger = _forty_five_exclusions() + [
        _row("blocklist", "abc123", "exists"),
        _row("webhooks", "(all webhooks)", "manual", "no API"),
        _row("star", "Rule A", "skipped", "inherited"),
        _row("sched-rep", "(sched-rep)", "not attempted", "not in backup"),
    ]
    tot = build_gap_report(ledger)["totals"]
    assert tot["items"] == 49
    assert tot["created"] == 43 and tot["exists"] == 1
    assert tot["restored"] == 44
    # failed 2 + manual 1 + skipped 1 + not attempted 1
    assert tot["missing"] == 5
    assert (set(GAP_RESTORED_STATUSES) | set(GAP_MISSING_STATUSES)
            | set(GAP_INFO_STATUSES)) == set(GAP_STATUSES)
    # No status may be counted twice.
    assert not (set(GAP_RESTORED_STATUSES) & set(GAP_MISSING_STATUSES))
    assert not (set(GAP_INFO_STATUSES)
                & (set(GAP_RESTORED_STATUSES) | set(GAP_MISSING_STATUSES)))


# ── Grouping / tab behaviour ───────────────────────────────────────────

def test_inherited_items_are_not_counted_as_gaps():
    """The API hands back inherited rules/tags at EVERY scope level. Those
    are restored with the scope that owns them, so counting them here would
    invent thousands of phantom gaps on a large migration and bury the two
    real ones."""
    ledger = ([_row("fw-rules", "Allow RDP", "created")]
              + [_row("fw-rules", f"Acct rule {i}", "inherited",
                      "belongs to 'account' scope") for i in range(40)])
    report = build_gap_report(ledger)
    (fw,) = report["elements"]
    assert fw["missing"] == 0
    assert fw["info"] == 40
    assert fw["total"] == 1        # what this scope actually owned
    assert fw["rowCount"] == 41    # every row is still there to inspect
    assert report["totals"]["missing"] == 0
    assert report["totals"]["items"] == 1


def test_empty_element_is_informational_but_uncaptured_is_a_gap():
    """'the backup held none' and 'the backup never captured it' are
    different problems: the second is how auto-upgrade policies and
    log-collection rules vanished for a whole migration."""
    report = build_gap_report([
        _row("locations", "(locations — nothing restored)", "empty",
             "the backup holds no items of this type for this scope"),
        _row("upgrade-pol", "(upgrade-pol — nothing restored)",
             "not attempted", "NOT CAPTURED by the backup"),
    ])
    by_key = {e["key"]: e for e in report["elements"]}
    assert by_key["locations"]["missing"] == 0
    assert by_key["locations"]["info"] == 1
    assert by_key["upgrade-pol"]["missing"] == 1


def test_one_tab_per_element_in_declared_order():
    ledger = [_row("blocklist", "hash1", "created"),
              _row("excl", "C:\\a", "created"),
              _row("policy", "policy", "created")]
    keys = [e["key"] for e in build_gap_report(ledger)["elements"]]
    # export_utils.GAP_ELEMENT_TITLES declares policy → excl → blocklist.
    assert keys == ["policy", "excl", "blocklist"]


def test_unknown_element_still_gets_a_readable_tab():
    report = build_gap_report([_row("brand-new-thing", "x", "failed", "boom")])
    assert report["elements"][0]["title"] == "Brand New Thing"
    assert gap_element_title("excl") == "Exclusions"


def test_every_restore_label_has_a_human_tab_title():
    """Any label the restore reports should read as English in the tabs."""
    for label in ("excl", "unified-excl", "blocklist", "fw-rules", "dc-rules",
                  "star", "overrides", "ep-tags", "svc-users", "users"):
        assert label not in gap_element_title(label)


def test_empty_ledger_is_harmless():
    report = build_gap_report([])
    assert report["elements"] == []
    assert report["totals"]["missing"] == 0
    # …and the HTML still renders rather than raising.
    assert "Migration Gap Report" in generate_gap_html(report)


def test_builder_does_not_mutate_or_drop_rows():
    ledger = _forty_five_exclusions()
    before = [dict(r) for r in ledger]
    report = build_gap_report(ledger, {"dest_url": "https://x"})
    assert ledger == before
    assert len(gap_report_rows(report)) == 45
    assert report["meta"]["dest_url"] == "https://x"


# ── Renderers ──────────────────────────────────────────────────────────

def test_html_has_a_tab_per_element_and_names_the_failures():
    ledger = _forty_five_exclusions() + [_row("blocklist", "h1", "created")]
    html = generate_gap_html(build_gap_report(ledger))
    assert html.count('class="tab-btn') == 3  # summary + 2 elements
    assert "Exclusions" in html and "Blocklist" in html
    assert "C:\\bad\\one.exe" in html
    assert "2 missing" in html


def test_html_escapes_item_names():
    html = generate_gap_html(build_gap_report(
        [_row("excl", "<script>alert(1)</script>", "failed", "nope")]))
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_excel_writes_one_worksheet_per_element(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    ledger = _forty_five_exclusions() + [
        _row("blocklist", "hash1", "created"),
        _row("fw-rules", "Allow RDP", "skipped", "inherited"),
    ]
    path = tmp_path / "gaps.xlsx"
    generate_gap_excel(str(path), build_gap_report(ledger))
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames[0] == "Summary"
    assert "Exclusions" in wb.sheetnames
    assert "Blocklist" in wb.sheetnames
    assert "Firewall Rules" in wb.sheetnames
    ws = wb["Exclusions"]
    values = [c.value for c in ws["C"]]
    assert "C:\\bad\\one.exe" in values
    assert "C:\\bad\\two.exe" in values


def test_csv_is_flat_with_an_element_column_and_a_yes_no_flag(tmp_path):
    """A CSV has no tabs, so the element has to become a column — and the
    operator must be able to filter to 'what did not migrate' without
    knowing the status vocabulary."""
    ledger = _forty_five_exclusions() + [
        _row("blocklist", "hash1", "created"),
        _row("fw-rules", "Acct rule", "inherited", "belongs to 'account'"),
    ]
    path = tmp_path / "gaps.csv"
    written = export_utils.write_gap_csv(str(path), build_gap_report(ledger))
    assert written == 47

    import csv
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["Element"] == "Exclusions"
    # Missing items lead, exactly like the tabs.
    assert rows[0]["Item"] == "C:\\bad\\one.exe"
    assert rows[0]["Restored"] == "NO"
    assert rows[0]["Reason / Error"].startswith("Validation Error")
    assert {r["Restored"] for r in rows} == {"yes", "NO", "n/a"}
    # Only the two real failures are flagged as not restored.
    assert sum(1 for r in rows if r["Restored"] == "NO") == 2
    assert {r["Element"] for r in rows} == {"Exclusions", "Blocklist",
                                            "Firewall Rules"}


def test_csv_is_written_with_a_bom_so_excel_reads_utf8():
    # Without the BOM Excel on Windows reads the file as cp1252 and mangles
    # every non-ASCII rule name.
    src = inspect.getsource(export_utils.write_gap_csv)
    assert "utf-8-sig" in src and 'newline=""' in src


def test_csv_is_offered_by_the_main_gap_export_dialog():
    src = inspect.getsource(export_utils.export_gap_report)
    assert '"*.csv"' in src and 'ext == ".csv"' in src


def test_restore_page_wires_a_csv_button():
    build = inspect.getsource(RestorePage.__init__)
    assert "self._gap_csv_btn" in build
    assert "self._export_gap_csv" in build
    handler = inspect.getsource(RestorePage._export_gap_csv)
    assert "export_gap_csv" in handler


def test_sheet_names_are_excel_safe_and_unique():
    used = set()
    a = export_utils._sheet_name("Tags/Firewall: [main]", used)
    b = export_utils._sheet_name("Tags/Firewall: [main]", used)
    for bad in "[]:*?/\\":
        assert bad not in a
    assert a != b and len(a) <= 31 and len(b) <= 31
    long = export_utils._sheet_name("x" * 60, used)
    assert len(long) == 31


# ── Source guards: the ledger must not silently lose an element ────────

def _restore_src():
    return inspect.getsource(RestorePage._run_restore)


def _literals(src, prefix):
    """First string literal of every `prefix"..."` call in src."""
    out = set()
    for chunk in src.split(prefix)[1:]:
        chunk = chunk.lstrip()
        if chunk[:1] != '"':
            continue
        out.add(chunk[1:chunk.index('"', 1)])
    return out


def test_shared_restore_helpers_all_record_to_the_ledger():
    src = _restore_src()
    for helper in ("def _r(", "def _r_bulk(", "def _nothing("):
        body = src.split(helper, 1)[1][:3000]
        assert "_rec(" in body, (
            f"{helper.strip('def (')} does not write to the item ledger — "
            f"everything it restores would be invisible in the Gap Report.")


def test_every_reported_element_also_records_named_items():
    """A label that reaches the results table must reach the ledger too.

    Otherwise the summary says "0" / "43 new" and the operator still cannot
    find out WHICH items are missing — the exact gap this report exists to
    close."""
    src = _restore_src()
    recorded = _literals(src, "_rec(")
    # Labels handled by an instrumented helper are covered automatically.
    for prefix in ("_r_bulk(", "_r(", "_nothing("):
        recorded |= _literals(src, prefix)
    reported = _literals(src, "results.append((") | _literals(src,
                                                              "_summarize(")
    missing = sorted(reported - recorded)
    assert not missing, (
        f"these restore results never produce named ledger rows: {missing}. "
        f"Add a _rec(...) call (or route them through _r/_r_bulk/_nothing) "
        f"so the Gap Report can list the items instead of only counting "
        f"them.")


def _ledger_statuses():
    """Every status literal passed to _rec()/_ledger_add() in pages.py."""
    tree = ast.parse(inspect.getsource(pages))
    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "id", None) or getattr(fn, "attr", None)
        idx = {"_rec": 2, "_ledger_add": 4}.get(name)
        if idx is None or len(node.args) <= idx:
            continue
        arg = node.args[idx]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            found.add(arg.value)
    return found


def test_only_declared_statuses_are_recorded():
    used = _ledger_statuses()
    assert used, "no ledger statuses found — did _rec() get renamed?"
    unknown = sorted(used - set(GAP_STATUSES))
    assert not unknown, (
        f"unknown ledger status(es) {unknown}; the Gap Report counts only "
        f"{list(GAP_STATUSES)}, so these rows would be tallied as neither "
        f"restored nor missing.")


def test_restore_json_export_ships_the_ledger():
    src = inspect.getsource(RestorePage._generate_restore_report)
    assert '"items": getattr(self, "_item_ledger"' in src, (
        "the JSON restore report must carry the per-item ledger — it is the "
        "only record of exactly what did not migrate.")
