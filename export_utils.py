"""
Export utilities — generates beautiful HTML and Excel reports from table data.
"""
import csv
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime
from tkinter import filedialog, messagebox
from typing import Optional

from app import cli_log


# ═══════════════════════════════════════════════════════════════════════
#  HTML Report
# ═══════════════════════════════════════════════════════════════════════

_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
    background: #0d0d1a; color: #e0e0e0; padding: 40px;
}
.header {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    border-radius: 16px; padding: 32px 40px; margin-bottom: 32px;
    border: 1px solid #2d2d44;
}
.header h1 { font-size: 28px; color: #fff; margin-bottom: 4px; }
.header .subtitle { color: #888; font-size: 14px; }
.header .meta { color: #666; font-size: 12px; margin-top: 12px; }
.stats {
    display: flex; gap: 16px; margin-bottom: 28px; flex-wrap: wrap;
}
.stat-card {
    background: #1a1a2e; border: 1px solid #2d2d44; border-radius: 12px;
    padding: 20px 28px; min-width: 160px;
}
.stat-card .label { font-size: 12px; color: #888; text-transform: uppercase;
    letter-spacing: 1px; margin-bottom: 4px; }
.stat-card .value { font-size: 28px; font-weight: 700; color: #00b894; }
.stat-card .value.accent { color: #e94560; }
.stat-card .value.warn { color: #fdcb6e; }
table {
    width: 100%; border-collapse: collapse; background: #1a1a2e;
    border-radius: 12px; overflow: hidden; border: 1px solid #2d2d44;
}
thead th {
    background: #16213e; color: #aaa; font-size: 11px;
    text-transform: uppercase; letter-spacing: 1px; padding: 14px 16px;
    text-align: left; border-bottom: 2px solid #2d2d44;
    position: sticky; top: 0;
}
tbody td {
    padding: 10px 16px; border-bottom: 1px solid #222238;
    font-size: 13px; max-width: 300px; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap;
}
tbody tr:hover { background: #222238; }
tbody tr:nth-child(even) { background: #151528; }
.badge {
    display: inline-block; padding: 2px 10px; border-radius: 12px;
    font-size: 11px; font-weight: 600;
}
.badge-green { background: #00b89422; color: #00b894; }
.badge-red { background: #e9456022; color: #e94560; }
.badge-yellow { background: #fdcb6e22; color: #fdcb6e; }
.badge-blue { background: #0984e322; color: #74b9ff; }
.footer {
    text-align: center; color: #444; font-size: 11px;
    margin-top: 32px; padding-top: 16px; border-top: 1px solid #222;
}
.value.blue { color: #74b9ff; }
.value.muted { color: #888; }
.infobox {
    background: #1a1a2e; border: 1px solid #2d2d44; border-radius: 12px;
    padding: 20px 28px; margin-bottom: 24px;
}
.infobox table { border: none; background: transparent; }
.infobox td {
    border: none; padding: 4px 16px 4px 0; font-size: 13px; white-space: nowrap;
}
.infobox td.k { color: #888; }
.infobox td.v { color: #e0e0e0; }
.banner {
    border-radius: 12px; padding: 14px 20px; margin-bottom: 24px;
    font-size: 14px; border: 1px solid; line-height: 1.5;
}
.banner.info { background: #0984e314; border-color: #0984e355; color: #74b9ff; }
.banner.warn { background: #fdcb6e14; border-color: #fdcb6e55; color: #fdcb6e; }
.banner.danger { background: #e9456014; border-color: #e9456055; color: #ff6b81; }
.rep-h2 { color: #fff; margin: 28px 0 12px; font-size: 18px; }
.tbl-tools { display: flex; align-items: center; gap: 12px; margin: 0 0 8px; }
.tbl-search {
    background: #12122a; border: 1px solid #2d2d44; border-radius: 8px;
    color: #e0e0e0; font-size: 13px; padding: 8px 12px; width: 280px;
    outline: none;
}
.tbl-search:focus { border-color: #0984e3; }
.tbl-search::placeholder { color: #555; }
.tbl-count { color: #666; font-size: 12px; }
thead th.sortable { cursor: pointer; user-select: none; white-space: nowrap; }
thead th.sortable:hover { color: #fff; }
thead th.sortable::after { content: " ↕"; opacity: .25; font-size: 10px; }
thead th.sortable[aria-sort="ascending"]::after { content: " ↑"; opacity: .9; }
thead th.sortable[aria-sort="descending"]::after { content: " ↓"; opacity: .9; }
tr.no-match td { color: #666; text-align: center; font-style: italic; }
"""


# Embedded once per report. Vanilla JS, no external assets, so the file stays
# self-contained and works from disk (file://). Adds a filter box and
# click-to-sort to every data table.
_REPORT_JS = """
<script>
(function () {
  function norm(s) { return (s || "").toLowerCase(); }
  function dataRows(body) {
    return Array.prototype.filter.call(body.rows, function (r) {
      return !r.classList.contains("no-match");
    });
  }

  // Per-table filter box.
  document.querySelectorAll(".tbl-search").forEach(function (inp) {
    var tbl = document.getElementById(inp.dataset.for);
    if (!tbl || !tbl.tBodies.length) return;
    var body = tbl.tBodies[0];
    var cnt = document.getElementById("cnt-" + inp.dataset.for);
    var nm = body.querySelector("tr.no-match");
    var total = dataRows(body).length;
    inp.placeholder = "Filter " + total + " rows\u2026";
    if (cnt) cnt.textContent = total + " rows";
    inp.addEventListener("input", function () {
      var q = norm(inp.value), shown = 0;
      dataRows(body).forEach(function (r) {
        var hit = norm(r.textContent).indexOf(q) !== -1;
        r.style.display = hit ? "" : "none";
        if (hit) shown++;
      });
      if (cnt) cnt.textContent = (shown === total)
        ? total + " rows" : shown + " of " + total;
      if (nm) nm.style.display = shown === 0 ? "" : "none";
    });
  });

  // Click-to-sort headers.
  document.querySelectorAll("table.data-table").forEach(function (tbl) {
    if (!tbl.tBodies.length) return;
    var body = tbl.tBodies[0];
    tbl.querySelectorAll("thead th").forEach(function (th, idx) {
      th.classList.add("sortable");
      th.addEventListener("click", function () {
        var asc = th.getAttribute("data-asc") !== "true";
        tbl.querySelectorAll("thead th").forEach(function (o) {
          o.removeAttribute("data-asc"); o.removeAttribute("aria-sort");
        });
        th.setAttribute("data-asc", asc ? "true" : "false");
        th.setAttribute("aria-sort", asc ? "ascending" : "descending");
        var rows = dataRows(body);
        function val(r) {
          return r.cells[idx] ? r.cells[idx].textContent.trim() : "";
        }
        var numeric = rows.every(function (r) {
          var t = val(r).replace(/[,%$]/g, "");
          return t === "" || !isNaN(parseFloat(t));
        });
        rows.sort(function (a, b) {
          var x = val(a), y = val(b);
          if (numeric) {
            return (asc ? 1 : -1) *
              ((parseFloat(x.replace(/[,%$]/g, "")) || 0) -
               (parseFloat(y.replace(/[,%$]/g, "")) || 0));
          }
          return (asc ? 1 : -1) *
            x.localeCompare(y, undefined, { numeric: true });
        });
        rows.forEach(function (r) { body.appendChild(r); });
        var nm = body.querySelector("tr.no-match");
        if (nm) body.appendChild(nm);
      });
    });
  });

  // Auto-bootstrap: any data table rendered WITHOUT a server-side toolbar
  // (the restore & validation reports) gets a filter box + no-match row.
  document.querySelectorAll("table.data-table").forEach(function (tbl) {
    if (!tbl.tBodies.length) return;
    var prev = tbl.previousElementSibling;
    if (prev && prev.classList.contains("tbl-tools")) return;
    var body = tbl.tBodies[0];
    var rows = dataRows(body);
    if (rows.length < 2) return;
    var ncol = tbl.tHead ? tbl.tHead.rows[0].cells.length
                         : (rows[0] ? rows[0].cells.length : 1);
    var tools = document.createElement("div");
    tools.className = "tbl-tools";
    var inp = document.createElement("input");
    inp.className = "tbl-search"; inp.type = "search";
    inp.placeholder = "Filter " + rows.length + " rows\u2026";
    inp.setAttribute("aria-label", "Filter rows");
    var cnt = document.createElement("span");
    cnt.className = "tbl-count"; cnt.textContent = rows.length + " rows";
    tools.appendChild(inp); tools.appendChild(cnt);
    tbl.parentNode.insertBefore(tools, tbl);
    var nmr = document.createElement("tr");
    nmr.className = "no-match";
    var td = document.createElement("td");
    td.colSpan = ncol; td.textContent = "No matching rows.";
    nmr.appendChild(td); nmr.style.display = "none";
    body.appendChild(nmr);
    var total = rows.length;
    inp.addEventListener("input", function () {
      var q = norm(inp.value), shown = 0;
      dataRows(body).forEach(function (r) {
        var hit = norm(r.textContent).indexOf(q) !== -1;
        r.style.display = hit ? "" : "none";
        if (hit) shown++;
      });
      cnt.textContent = (shown === total) ? total + " rows"
                                          : shown + " of " + total;
      nmr.style.display = shown === 0 ? "" : "none";
    });
  });
})();
</script>
"""

# Fields that get badge styling
_BADGE_MAP = {
    "true": "badge-green", "false": "badge-red",
    "active": "badge-green", "infected": "badge-red",
    "mitigated": "badge-green", "not_mitigated": "badge-red",
    "suspicious": "badge-yellow", "malicious": "badge-red",
    "critical": "badge-red", "high": "badge-red",
    "medium": "badge-yellow", "low": "badge-blue",
    "finished": "badge-green", "running": "badge-yellow",
    "enabled": "badge-green", "disabled": "badge-red",
    # Agent-migration outcomes.
    "moved": "badge-green", "migrated": "badge-green",
    "pending": "badge-yellow", "queued": "badge-blue",
    "sending": "badge-blue", "failed": "badge-red",
    "decommissioned": "badge-yellow",
}


def _badge(val: str) -> str:
    v = str(val).lower().strip()
    cls = _BADGE_MAP.get(v, "")
    if cls:
        return f'<span class="badge {cls}">{val}</span>'
    return str(val)


def _cell(val) -> str:
    if isinstance(val, (dict, list)):
        return json.dumps(val, default=str)[:120]
    s = str(val)
    return s[:200] if len(s) > 200 else s


def generate_html(title: str, columns: list[str], rows: list[dict],
                  stats: Optional[list[dict]] = None,
                  subtitle: str = "") -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    stats_html = ""
    if stats:
        cards = ""
        for s in stats:
            cls = s.get("class", "")
            cards += (f'<div class="stat-card"><div class="label">{s["label"]}</div>'
                      f'<div class="value {cls}">{s["value"]}</div></div>')
        stats_html = f'<div class="stats">{cards}</div>'

    # Table
    th = "".join(f"<th>{c}</th>" for c in columns)
    tr_list = []
    for row in rows:
        tds = "".join(f"<td>{_badge(_cell(row.get(c, '')))}</td>" for c in columns)
        tr_list.append(f"<tr>{tds}</tr>")
    tbody = "\n".join(tr_list)

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{title} — S1 Command Center Report</title>
<style>{_CSS}</style></head><body>
<div class="header">
  <h1>{title}</h1>
  <div class="subtitle">{subtitle or 'S1 Command Center Report'}</div>
  <div class="meta">Generated {now} &bull; {len(rows)} records</div>
</div>
{stats_html}
<table><thead><tr>{th}</tr></thead><tbody>{tbody}</tbody></table>
<div class="footer">S1 Command Center &bull; Made by Ran Jacobi &bull; Generated {now}</div>
</body></html>"""


# ═══════════════════════════════════════════════════════════════════════
#  Backup redaction (safe-to-share copies)
# ═══════════════════════════════════════════════════════════════════════

REDACTED = "***REDACTED***"

# A key is treated as secret if its name contains any of these (case-insensitive).
# Backups embed real secrets in the settings blocks — SMTP relay passwords, AD
# bind credentials, syslog tokens, SSO client secrets / private keys, webhook
# auth headers — so a backup JSON shared on a ticket or chat is a credential
# leak. Redaction produces a sanitised COPY for sharing; the working backup
# used for restore is never modified.
_SECRET_KEY_PARTS = (
    "password", "passwd", "passphrase", "secret", "token", "apikey",
    "api_key", "privatekey", "private_key", "clientsecret", "client_secret",
    "bindpassword", "bind_password", "credential", "authorization", "bearer",
)


def _is_secret_key(key) -> bool:
    k = str(key).lower().replace("-", "").replace("_", "")
    return any(p.replace("_", "") in k for p in _SECRET_KEY_PARTS)


def _redact_obj(obj, counter):
    """Recursively return a redacted deep copy, counting masked values."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _is_secret_key(k) and v not in (None, "", [], {}):
                out[k] = REDACTED
                counter[0] += 1
            else:
                out[k] = _redact_obj(v, counter)
        return out
    if isinstance(obj, list):
        return [_redact_obj(i, counter) for i in obj]
    return obj


def count_backup_secrets(nodes) -> int:
    """How many secret values a backup contains (0 = safe to share as-is)."""
    counter = [0]
    _redact_obj(nodes or [], counter)
    return counter[0]


def redact_backup(nodes):
    """Return (redacted_copy, count) — a deep copy of the backup with every
    secret-looking value masked. Input is not mutated."""
    counter = [0]
    redacted = _redact_obj(nodes or [], counter)
    return redacted, counter[0]


# ═══════════════════════════════════════════════════════════════════════
#  Migration Manifest (for the PSO ticket-closing workflow)
# ═══════════════════════════════════════════════════════════════════════

def build_migration_manifest(meta: dict, results: list[dict]) -> dict:
    """Turn a Migration Validation result set (meta + results, the structure
    produced by ValidationPage._run_validation) into a structured, portable
    manifest of what was migrated and how it verified.

    Pure function — no GUI/network. Safe to unit-test."""
    meta = meta or {}
    results = results or []

    n = len(results)
    missing = sum(1 for r in results if not r.get("matched"))
    with_diffs = sum(1 for r in results
                     if r.get("matched") and r.get("diffs", 0) > 0)
    identical = n - missing - with_diffs
    total_diffs = sum(r.get("diffs", 0) for r in results if r.get("matched"))

    if n == 0:
        status = "incomplete"
    elif missing == 0 and with_diffs == 0:
        status = "verified"
    else:
        status = "differences"

    nodes = []
    for r in results:
        if not r.get("matched"):
            outcome = "missing"
            diffs = []
        elif r.get("diffs", 0) == 0:
            outcome = "identical"
            diffs = []
        else:
            outcome = "differences"
            diffs = [
                {
                    "element": x.get("cat"),
                    "src": x.get("src"),
                    "dst": x.get("dst"),
                    "missing": x.get("missing", []),
                    "extra": x.get("extra", []),
                }
                for x in r.get("rows", []) if x.get("status") == "diff"
            ]
        nodes.append({
            "type": r.get("type"),
            "path": r.get("path"),
            "result": outcome,
            "differences": diffs,
        })

    return {
        "tool": "S1 Command Center",
        "kind": "migration-manifest",
        "version": 1,
        "generatedAt": meta.get("when"),
        "source": meta.get("src_url"),
        "destination": meta.get("dst_url"),
        "levels": meta.get("levels", []),
        "scope": {
            "source": meta.get("src_filters", {}),
            "destination": meta.get("dst_filters", {}),
        },
        "summary": {
            "nodesCompared": n,
            "identical": identical,
            "withDifferences": with_diffs,
            "missingOnDestination": missing,
            "totalDifferences": total_diffs,
            "status": status,
        },
        "nodes": nodes,
    }


def manifest_to_pso_comment(manifest: dict) -> str:
    """Render a migration manifest as a Markdown comment ready for the PSO
    Jira ticket-closing workflow ('done with PSO-XXX'). Mirrors the agreed
    Migration Summary template so the comment can be posted as-is."""
    m = manifest or {}
    s = m.get("summary", {})
    when = (m.get("generatedAt") or "")[:10] or "—"
    status = s.get("status")

    if status == "verified":
        headline = "Migration completed successfully ✅"
        status_line = "All settings transferred and verified."
    elif status == "differences":
        headline = "Migration completed — review needed ⚠️"
        status_line = (
            f"{s.get('totalDifferences', 0)} difference(s) across "
            f"{s.get('withDifferences', 0)} node(s); "
            f"{s.get('missingOnDestination', 0)} scope(s) missing on "
            f"destination. See details below.")
    else:
        headline = "Migration validation incomplete"
        status_line = "No nodes were compared — re-run validation."

    src_scope = (m.get("scope", {}).get("source") or {})
    scope_txt = (f"account: {src_scope.get('account') or 'all'} · "
                 f"site: {src_scope.get('site') or 'all'}")
    levels = ", ".join(m.get("levels", [])) or "—"

    lines = [
        headline,
        "",
        "**Migration Summary**",
        f"- **Source:** {m.get('source') or '?'}",
        f"- **Destination:** {m.get('destination') or '?'}",
        f"- **Completed:** {when}",
        f"- **Scope:** levels [{levels}] · {scope_txt}",
        f"- **Validation:** {s.get('nodesCompared', 0)} node(s) compared — "
        f"{s.get('identical', 0)} identical, "
        f"{s.get('withDifferences', 0)} with differences, "
        f"{s.get('missingOnDestination', 0)} missing on destination",
        f"- **Status:** {status_line}",
    ]

    # Per-node difference detail (only when there is something to flag).
    flagged = [nd for nd in m.get("nodes", [])
               if nd.get("result") in ("differences", "missing")]
    if flagged:
        lines += ["", "**Items needing attention**"]
        for nd in flagged:
            if nd.get("result") == "missing":
                lines.append(
                    f"- `{nd.get('path')}` — scope missing on destination "
                    f"(renamed or not created)")
                continue
            for d in nd.get("differences", []):
                detail = []
                if d.get("missing"):
                    miss = d["missing"]
                    shown = ", ".join(miss[:8])
                    if len(miss) > 8:
                        shown += f" (+{len(miss) - 8} more)"
                    detail.append(f"missing: {shown}")
                if d.get("extra"):
                    detail.append(f"{len(d['extra'])} extra on dest")
                tail = f" ({'; '.join(detail)})" if detail else ""
                lines.append(
                    f"- `{nd.get('path')}` / {d.get('element')}: "
                    f"{d.get('src')} → {d.get('dst')}{tail}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
#  Excel Report (via openpyxl)
# ═══════════════════════════════════════════════════════════════════════

def generate_excel(path: str, title: str, columns: list[str],
                   rows: list[dict]):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]

    # Colors
    header_fill = PatternFill(start_color="1a1a2e", end_color="1a1a2e",
                              fill_type="solid")
    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Segoe UI", size=10, color="333333")
    alt_fill = PatternFill(start_color="F5F6FA", end_color="F5F6FA",
                           fill_type="solid")
    border = Border(
        bottom=Side(style="thin", color="E0E0E0"))

    # Title row
    ws.merge_cells(start_row=1, start_column=1,
                   end_row=1, end_column=max(len(columns), 1))
    cell = ws.cell(row=1, column=1, value=f"{title} — S1 Command Center Report")
    cell.font = Font(name="Segoe UI", size=14, bold=True, color="1a1a2e")
    cell.alignment = Alignment(horizontal="left")

    ws.merge_cells(start_row=2, start_column=1,
                   end_row=2, end_column=max(len(columns), 1))
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cell2 = ws.cell(row=2, column=1,
                    value=f"Generated {now}  •  {len(rows)} records")
    cell2.font = Font(name="Segoe UI", size=9, color="888888")

    # Header row
    for j, col in enumerate(columns, 1):
        c = ws.cell(row=4, column=j, value=col)
        c.font = header_font
        c.fill = header_fill
        c.alignment = Alignment(horizontal="left")

    # Data rows
    for i, row in enumerate(rows):
        r = i + 5
        fill = alt_fill if i % 2 == 0 else None
        for j, col in enumerate(columns, 1):
            val = row.get(col, "")
            if isinstance(val, (dict, list)):
                val = json.dumps(val, default=str)
            c = ws.cell(row=r, column=j, value=val)
            c.font = data_font
            c.border = border
            if fill:
                c.fill = fill

    # Auto-width
    for j, col in enumerate(columns, 1):
        max_len = len(col)
        for i, row in enumerate(rows[:200]):
            val = str(row.get(col, ""))
            max_len = max(max_len, min(len(val), 50))
        ws.column_dimensions[ws.cell(row=4, column=j).column_letter].width = \
            max_len + 4

    ws.freeze_panes = "A5"
    ws.auto_filter.ref = f"A4:{ws.cell(row=4, column=len(columns)).column_letter}4"
    wb.save(path)


# ═══════════════════════════════════════════════════════════════════════
#  STAR (custom detection) rules — detailed Excel workbook
# ═══════════════════════════════════════════════════════════════════════

_XL_FONT = "Segoe UI"
# Excel rejects most C0 control characters and caps a cell at 32,767 chars.
_XL_ILLEGAL_RE = re.compile(r"[\000-\010\013\014\016-\037]")
_XL_MAX_CHARS = 32000

# (header, rule key, column width, kind)
STAR_COLUMNS = [
    ("Rule Name",          "name",              38, "text"),
    ("Description",        "description",       46, "wrap"),
    ("Status",             "status",            12, "status"),
    ("Severity",           "severity",          11, "severity"),
    ("Scope",              "scope",             10, "scope"),
    ("Scope Path",         "scopeName",         34, "text"),
    ("Account",            "accountName",       22, "text"),
    ("Site",               "siteName",          22, "text"),
    ("Query Type",         "queryType",         13, "text"),
    ("Query Language",     "queryLang",         14, "text"),
    ("Detection Query",    "s1ql",              70, "wrap"),
    ("Treat as Threat",    "treatAsThreat",     15, "text"),
    ("Network Quarantine", "networkQuarantine", 18, "bool"),
    ("Active Response",    "activeResponse",    24, "wrap"),
    ("Expiration Mode",    "expirationMode",    15, "text"),
    ("Expires",            "expiration",        17, "date"),
    ("Expired",            "expired",           9,  "bool"),
    ("Alerts Generated",   "generatedAlerts",   15, "num"),
    ("Last Alert",         "lastAlertTime",     17, "date"),
    ("Created",            "createdAt",         17, "date"),
    ("Created By",         "creator",           20, "text"),
    ("Last Updated",       "updatedAt",         17, "date"),
    ("Updated By",         "updater",           20, "text"),
    ("Rule ID",            "id",                22, "text"),
]

# value -> (fill, font colour)
_STAR_SEVERITY_STYLE = {
    "critical":      ("FFE0E0", "B02020"),
    "high":          ("FFEBDC", "C2560A"),
    "medium":        ("FFF6DC", "9C6F00"),
    "low":           ("E6F0FB", "1B5FA8"),
    "suspicious":    ("FFF6DC", "9C6F00"),
    "info":          ("EFEFF4", "55556A"),
    "informational": ("EFEFF4", "55556A"),
}
_STAR_STATUS_STYLE = {
    "active":   ("E3F7EC", "1B7F4F"),
    "draft":    ("EDEDF2", "555566"),
    "disabled": ("FDEAE7", "B02020"),
}
_STAR_SCOPE_STYLE = {
    "global":  ("EDE6F8", "5B34B0"),
    "tenant":  ("EDE6F8", "5B34B0"),
    "account": ("E2F0FD", "13599C"),
    "site":    ("E6F5E9", "27702F"),
    "group":   ("FFF0DC", "A85B00"),
}

_STAR_SCOPE_ORDER = {"global": 0, "tenant": 0, "account": 1, "site": 2,
                     "group": 3}


def _xl_safe(value):
    """Strip characters Excel refuses and cap the cell length."""
    if not isinstance(value, str):
        return value
    value = _XL_ILLEGAL_RE.sub("", value)
    if len(value) > _XL_MAX_CHARS:
        value = value[:_XL_MAX_CHARS] + "… (truncated)"
    return value


def _fmt_dt(val) -> str:
    """'2024-01-31T09:15:00.000000Z' -> '2024-01-31 09:15'."""
    if not val:
        return ""
    s = str(val)
    try:
        return datetime.fromisoformat(
            s.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return s[:19].replace("T", " ")


def _fmt_active_response(val) -> str:
    """Render activeResponse — a plain on/off flag on some consoles, an object
    of individual actions on others."""
    if val is None or val == "":
        return ""
    if isinstance(val, bool):
        return "Yes" if val else "No"
    if isinstance(val, dict):
        on = [k for k, v in val.items() if v is True]
        if on:
            return ", ".join(on)
        kept = {k: v for k, v in val.items()
                if v not in (None, False, "", [], {})}
        return json.dumps(kept, default=str) if kept else "No"
    return str(val)


def _star_cell(rule: dict, key: str, kind: str):
    val = rule.get(key)
    if key == "activeResponse":
        return _fmt_active_response(val)
    if kind == "date":
        return _fmt_dt(val)
    if kind == "bool":
        if val is None:
            return ""
        return "Yes" if val else "No"
    if kind == "num":
        return val if isinstance(val, (int, float)) else (val or 0)
    if isinstance(val, (dict, list)):
        return _xl_safe(json.dumps(val, default=str))
    if val is None:
        return ""
    return _xl_safe(str(val))


def _star_sort_key(r: dict):
    return (
        str(r.get("accountName") or "").lower(),
        _STAR_SCOPE_ORDER.get(str(r.get("scope") or "").lower(), 9),
        str(r.get("siteName") or "").lower(),
        str(r.get("name") or "").lower(),
    )


def count_star_scope_duplicates(rules) -> int:
    """How many SITE-scoped rules share a name with an account rule in the
    same account. Surfaced on the summary sheet because that is the signature
    of the pre-2.1.9 restore bug that copied account rules to every site."""
    acct = {(str(r.get("accountId") or ""), r.get("name"))
            for r in (rules or [])
            if str(r.get("scope") or "").lower() == "account"}
    return sum(1 for r in (rules or [])
               if str(r.get("scope") or "").lower() == "site"
               and (str(r.get("accountId") or ""), r.get("name")) in acct)


def generate_star_rules_excel(path: str, rules: list,
                              meta: Optional[dict] = None) -> int:
    """Write a polished, filterable workbook of STAR custom detection rules.

    'Summary'    — headline totals plus breakdowns by scope, status, severity
                   and account.
    'STAR Rules' — every rule with all customer-relevant fields, frozen
                   header, auto-filter and colour-coded scope/status/severity
                   so it is readable without any further formatting work.

    Returns the number of rules written."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    meta = meta or {}
    rules = sorted(rules or [], key=_star_sort_key)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    ink = "1A1A2E"
    row_border = Border(bottom=Side(style="thin", color="E3E3EC"))
    head_border = Border(bottom=Side(style="medium", color=ink))

    wb = Workbook()

    # ── Sheet 1: Summary ────────────────────────────────────────────────
    s = wb.active
    s.title = "Summary"
    s.sheet_view.showGridLines = False
    for col, width in (("A", 3), ("B", 38), ("C", 14), ("D", 12)):
        s.column_dimensions[col].width = width

    t = s.cell(row=2, column=2, value="STAR Custom Detection Rules")
    t.font = Font(name=_XL_FONT, size=18, bold=True, color=ink)
    sub = s.cell(row=3, column=2, value="S1 Command Center export")
    sub.font = Font(name=_XL_FONT, size=10, color="8A8A9A")

    r = 5
    for label, value in (
        ("Console", meta.get("console") or "—"),
        ("Account filter", meta.get("account_filter") or "(all accounts)"),
        ("Site filter", meta.get("site_filter") or "(all sites)"),
        ("Generated", now),
        ("Total rules", len(rules)),
    ):
        lc = s.cell(row=r, column=2, value=label)
        lc.font = Font(name=_XL_FONT, size=10, color="8A8A9A")
        vc = s.cell(row=r, column=3, value=value)
        vc.font = Font(name=_XL_FONT, size=10, bold=True, color=ink)
        r += 1

    dupes = count_star_scope_duplicates(rules)
    dl = s.cell(row=r, column=2,
                value="Site rules duplicating an account rule")
    dl.font = Font(name=_XL_FONT, size=10, color="8A8A9A")
    dv = s.cell(row=r, column=3, value=dupes)
    dv.font = Font(name=_XL_FONT, size=10, bold=True,
                   color="B02020" if dupes else "1B7F4F")
    r += 2

    def _breakdown(row, heading, counter, style_map=None):
        for col, text in ((2, heading), (3, "Count")):
            h = s.cell(row=row, column=col, value=text)
            h.font = Font(name=_XL_FONT, size=11, bold=True, color=ink)
            h.border = head_border
        row += 1
        total = sum(counter.values()) or 1
        for label, count in counter.most_common():
            lc = s.cell(row=row, column=2, value=str(label or "—"))
            lc.font = Font(name=_XL_FONT, size=10, color="333344")
            lc.border = row_border
            cc = s.cell(row=row, column=3, value=count)
            cc.font = Font(name=_XL_FONT, size=10, bold=True, color="333344")
            cc.border = row_border
            pc = s.cell(row=row, column=4, value=count / total)
            pc.number_format = "0.0%"
            pc.font = Font(name=_XL_FONT, size=10, color="8A8A9A")
            pc.border = row_border
            sty = style_map.get(str(label or "").lower()) if style_map else None
            if sty:
                lc.fill = PatternFill("solid", start_color=sty[0],
                                      end_color=sty[0])
                lc.font = Font(name=_XL_FONT, size=10, bold=True,
                               color=sty[1])
            row += 1
        return row + 1

    r = _breakdown(r, "By scope",
                   Counter(str(x.get("scope") or "—").lower() for x in rules),
                   _STAR_SCOPE_STYLE)
    r = _breakdown(r, "By status",
                   Counter(str(x.get("status") or "—") for x in rules),
                   _STAR_STATUS_STYLE)
    r = _breakdown(r, "By severity",
                   Counter(str(x.get("severity") or "—") for x in rules),
                   _STAR_SEVERITY_STYLE)
    r = _breakdown(r, "By account",
                   Counter(str(x.get("accountName") or "—") for x in rules))

    # ── Sheet 2: the rules ──────────────────────────────────────────────
    ws = wb.create_sheet("STAR Rules")
    ws.sheet_view.showGridLines = False
    last_col = get_column_letter(len(STAR_COLUMNS))

    ws.merge_cells(f"A1:{last_col}1")
    tc = ws.cell(row=1, column=1, value="STAR Custom Detection Rules")
    tc.font = Font(name=_XL_FONT, size=15, bold=True, color=ink)
    tc.alignment = Alignment(horizontal="left", vertical="center")
    ws.row_dimensions[1].height = 26

    ws.merge_cells(f"A2:{last_col}2")
    sc = ws.cell(row=2, column=1,
                 value=f"{meta.get('console') or 'console'}  •  "
                       f"{len(rules)} rule(s)  •  generated {now}")
    sc.font = Font(name=_XL_FONT, size=9, color="8A8A9A")

    header_fill = PatternFill("solid", start_color=ink, end_color=ink)
    for j, (title, _key, width, _kind) in enumerate(STAR_COLUMNS, 1):
        c = ws.cell(row=4, column=j, value=title)
        c.font = Font(name=_XL_FONT, size=10, bold=True, color="FFFFFF")
        c.fill = header_fill
        c.alignment = Alignment(horizontal="left", vertical="center",
                                wrap_text=True)
        ws.column_dimensions[get_column_letter(j)].width = width
    ws.row_dimensions[4].height = 26

    alt = PatternFill("solid", start_color="F7F8FC", end_color="F7F8FC")
    for i, rule in enumerate(rules):
        row = i + 5
        banded = (i % 2 == 1)
        for j, (_title, key, _w, kind) in enumerate(STAR_COLUMNS, 1):
            c = ws.cell(row=row, column=j, value=_star_cell(rule, key, kind))
            c.font = Font(name=_XL_FONT, size=10, color="2C2C3A")
            c.border = row_border
            c.alignment = Alignment(horizontal="left", vertical="top",
                                    wrap_text=(kind == "wrap"))
            if banded:
                c.fill = alt
            if kind == "num":
                c.alignment = Alignment(horizontal="right", vertical="top")
            sty = None
            if kind == "severity":
                sty = _STAR_SEVERITY_STYLE.get(
                    str(rule.get("severity") or "").lower())
            elif kind == "status":
                sty = _STAR_STATUS_STYLE.get(
                    str(rule.get("status") or "").lower())
            elif kind == "scope":
                sty = _STAR_SCOPE_STYLE.get(
                    str(rule.get("scope") or "").lower())
            if sty:
                c.fill = PatternFill("solid", start_color=sty[0],
                                     end_color=sty[0])
                c.font = Font(name=_XL_FONT, size=10, bold=True, color=sty[1])
                c.alignment = Alignment(horizontal="center", vertical="top")

    ws.freeze_panes = "B5"
    ws.auto_filter.ref = f"A4:{last_col}{4 + len(rules)}"

    wb.save(path)
    return len(rules)


# ═══════════════════════════════════════════════════════════════════════
#  Migration Gap Report — per-element restore reconciliation
# ═══════════════════════════════════════════════════════════════════════
#
# The restore report answers "did the run finish?". It does NOT answer the
# question every operator actually asks afterwards: "I backed up 45
# exclusions and only 43 landed — WHICH two are missing, and why?".
#
# RestorePage._run_restore records one ledger row per item it touched:
#   {node, scope, element, kind, item, status, reason}
# status ∈ GAP_STATUSES. Everything below turns that flat ledger into a
# tabbed document (one tab per element) with an explicit
# restored / not-restored split. Pure functions — no GUI, no network.

# Ordered so the report always reads the same way.
GAP_STATUSES = ("created", "exists", "failed", "skipped", "manual",
                "not attempted", "inherited", "empty")
# What counts as "it is on the destination".
GAP_RESTORED_STATUSES = ("created", "exists")
# What the operator has to act on. `not attempted` is in here on purpose:
# it means the element was selected but the backup held nothing for it,
# which is how four elements went missing for a whole migration.
GAP_MISSING_STATUSES = ("failed", "skipped", "manual", "not attempted")
# Neither restored nor missing:
#   inherited — the item belongs to a different scope and is restored
#               there; re-creating it here would duplicate it.
#   empty     — the element was selected and the backup legitimately holds
#               no items for this scope.
# Counting these as gaps would drown the real ones (the API returns
# inherited rules/tags at EVERY level, so a 200-group migration would
# report thousands of phantom "missing" items).
GAP_INFO_STATUSES = ("inherited", "empty")

# Restore-result label -> human tab title. Labels are the short ones used
# in the restore results table / operation log, so the two line up.
GAP_ELEMENT_TITLES = {
    "(node)": "Scopes Skipped",
    "policy": "Policy",
    "excl": "Exclusions",
    "unified-excl": "Unified Exclusions",
    "blocklist": "Blocklist",
    "fw-cfg": "Firewall Config",
    "fw-rules": "Firewall Rules",
    "nq-cfg": "Network Quarantine Config",
    "nq-rules": "Network Quarantine Rules",
    "dc-cfg": "Device Control Config",
    "dc-rules": "Device Control Rules",
    "tags-fw": "Tags — Firewall",
    "tags-nq": "Tags — Network Quarantine",
    "tags-ep": "Tags — Endpoint (named)",
    "ep-tags": "Tags — Endpoint (key/value)",
    "star": "STAR Custom Rules",
    "dv-filters": "Saved Filters",
    "overrides": "Config Overrides",
    "threat-intel": "Threat Intelligence",
    "log-rules": "Log Collection Rules",
    "upgrade-pol": "Auto-Upgrade Policies",
    "locations": "Locations",
    "webhooks": "Webhooks",
    "sched-rep": "Scheduled Reports",
    "mkt-apps": "Marketplace Apps",
    "scripts": "Remote Scripts",
    "roles": "RBAC Roles",
    "svc-users": "Service Users",
    "users": "Console Users",
    "set-noti": "Settings — Notifications",
    "set-sysl": "Settings — Syslog",
    "set-acti": "Settings — Active Directory",
    "set-smtp": "Settings — SMTP",
    "set-sso": "Settings — SSO",
    "recipients": "Settings — Notification Recipients",
    "group-rank": "Group Ranking",
}

# Tab display order — anything unknown is appended alphabetically after.
_GAP_ORDER = list(GAP_ELEMENT_TITLES)


def gap_element_title(key: str) -> str:
    """Human tab title for a restore-result label."""
    return GAP_ELEMENT_TITLES.get(key, str(key or "other").replace("-", " ").title())


def build_gap_report(ledger: list, meta: Optional[dict] = None) -> dict:
    """Group a flat restore ledger into per-element tabs with counts.

    Returns a JSON-serialisable dict:
      {generatedAt, meta, totals, elements: [{key, title, counts,
        restored, missing, total, rows: [...]}]}
    """
    meta = dict(meta or {})
    rows = [r for r in (ledger or []) if isinstance(r, dict)]

    groups: dict = {}
    for r in rows:
        key = str(r.get("element") or "other")
        groups.setdefault(key, []).append(r)

    def _order(key):
        return (_GAP_ORDER.index(key) if key in _GAP_ORDER
                else len(_GAP_ORDER)), gap_element_title(key).lower()

    elements = []
    totals = {s: 0 for s in GAP_STATUSES}
    for key in sorted(groups, key=_order):
        items = groups[key]
        counts = {s: 0 for s in GAP_STATUSES}
        for r in items:
            st = str(r.get("status") or "")
            if st not in counts:
                counts[st] = 0
            counts[st] += 1
            totals[st] = totals.get(st, 0) + 1
        restored = sum(counts.get(s, 0) for s in GAP_RESTORED_STATUSES)
        missing = sum(counts.get(s, 0) for s in GAP_MISSING_STATUSES)
        info = sum(counts.get(s, 0) for s in GAP_INFO_STATUSES)
        elements.append({
            "key": key,
            "title": gap_element_title(key),
            "counts": counts,
            "restored": restored,
            "missing": missing,
            "info": info,
            "total": len(items) - info,
            "rowCount": len(items),
            # Not-restored rows first — that is what the report is for.
            "rows": sorted(
                items,
                key=lambda r: (str(r.get("status")) in GAP_RESTORED_STATUSES,
                               str(r.get("node") or ""),
                               str(r.get("item") or ""))),
        })

    total_info = sum(totals.get(s, 0) for s in GAP_INFO_STATUSES)
    total_items = len(rows) - total_info
    total_restored = sum(totals.get(s, 0) for s in GAP_RESTORED_STATUSES)
    total_missing = sum(totals.get(s, 0) for s in GAP_MISSING_STATUSES)
    return {
        "tool": "S1 Command Center",
        "kind": "migration-gap-report",
        "version": 1,
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "meta": meta,
        "totals": {
            **totals,
            "items": total_items,
            "rows": len(rows),
            "restored": total_restored,
            "missing": total_missing,
            "info": total_info,
        },
        "elements": elements,
    }


_GAP_STATUS_CLASS = {
    "created": "badge-green", "exists": "badge-blue",
    "failed": "badge-red", "skipped": "badge-yellow",
    "manual": "badge-yellow", "not attempted": "badge-red",
    "inherited": "badge-blue", "empty": "badge-blue",
}

_GAP_CSS = """
.tabs { display:flex; flex-wrap:wrap; gap:6px; margin:24px 0 18px; }
.tab-btn {
    background:#1a1a2e; border:1px solid #2d2d44; color:#aaa;
    border-radius:10px; padding:8px 14px; font-size:13px; cursor:pointer;
    font-family:inherit;
}
.tab-btn:hover { background:#222238; color:#fff; }
.tab-btn.active { background:#6b0aea; border-color:#6b0aea; color:#fff;
    font-weight:600; }
.tab-btn .n { font-size:11px; color:#fdcb6e; margin-left:6px; }
.tab-btn.clean .n { color:#00b894; }
.panel { display:none; }
.panel.active { display:block; }
h2.sec { color:#fff; margin:8px 0 12px; font-size:18px; }
p.hint { color:#888; font-size:13px; margin-bottom:14px; }
tbody td.err { color:#e94560; white-space:normal; font-size:12px; }
tbody td.wrap { white-space:normal; }
"""

_GAP_JS = """
function s1tab(id){
  document.querySelectorAll('.panel').forEach(function(p){
    p.classList.toggle('active', p.id === id); });
  document.querySelectorAll('.tab-btn').forEach(function(b){
    b.classList.toggle('active', b.dataset.target === id); });
}
"""


def _esc(val) -> str:
    s = "" if val is None else str(val)
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def generate_gap_html(report: dict) -> str:
    """Render a gap report as a self-contained tabbed HTML document."""
    report = report or {}
    meta = report.get("meta", {}) or {}
    elements = report.get("elements", []) or []
    tot = report.get("totals", {}) or {}
    now = report.get("generatedAt", "") or datetime.now().isoformat(
        timespec="seconds")

    stats = f"""<div class="stats">
      <div class="stat-card"><div class="label">Items Tracked</div>
        <div class="value" style="color:#74b9ff">{tot.get('items', 0)}</div></div>
      <div class="stat-card"><div class="label">On Destination</div>
        <div class="value">{tot.get('restored', 0)}</div></div>
      <div class="stat-card"><div class="label">NOT Migrated</div>
        <div class="value accent">{tot.get('missing', 0)}</div></div>
      <div class="stat-card"><div class="label">Created</div>
        <div class="value">{tot.get('created', 0)}</div></div>
      <div class="stat-card"><div class="label">Already Existed</div>
        <div class="value" style="color:#74b9ff">{tot.get('exists', 0)}</div></div>
      <div class="stat-card"><div class="label">Failed</div>
        <div class="value accent">{tot.get('failed', 0)}</div></div>
      <div class="stat-card"><div class="label">Skipped</div>
        <div class="value warn">{tot.get('skipped', 0)}</div></div>
      <div class="stat-card"><div class="label">Manual Action</div>
        <div class="value warn">{tot.get('manual', 0)}</div></div>
      <div class="stat-card"><div class="label">Inherited / Empty</div>
        <div class="value" style="color:#74b9ff">{tot.get('info', 0)}</div></div>
    </div>"""

    info_rows = "".join(
        f'<tr><td style="color:#888; padding:4px 16px 4px 0; border:none;">'
        f'{_esc(k)}</td><td style="color:#e0e0e0; border:none;">'
        f'{_esc(v)}</td></tr>'
        for k, v in (
            ("Source Console", meta.get("source_url") or "—"),
            ("Destination Console", meta.get("dest_url") or "—"),
            ("Started", (meta.get("start_time") or "")[:19].replace("T", " ")),
            ("Finished", (meta.get("end_time") or "")[:19].replace("T", " ")),
            ("Duration", meta.get("elapsed") or "—"),
            ("Nodes restored", f"{meta.get('restored_count', '—')} of "
                               f"{meta.get('total_nodes', '—')}"),
        ))
    info = f"""<div style="background:#1a1a2e; border:1px solid #2d2d44;
      border-radius:12px; padding:20px 28px; margin-bottom:8px;">
      <table style="border:none; background:transparent;">{info_rows}</table>
    </div>"""

    # ── Tab buttons ──
    btns = ['<button class="tab-btn active" data-target="p-summary" '
            'onclick="s1tab(\'p-summary\')">📋 Summary</button>']
    for i, el in enumerate(elements):
        cls = "tab-btn" + (" clean" if not el["missing"] else "")
        badge = (f'<span class="n">{el["missing"]} missing</span>'
                 if el["missing"] else '<span class="n">✓</span>')
        btns.append(
            f'<button class="{cls}" data-target="p-{i}" '
            f'onclick="s1tab(\'p-{i}\')">{_esc(el["title"])}{badge}</button>')
    tabs_html = f'<div class="tabs">{"".join(btns)}</div>'

    # ── Summary panel ──
    sum_rows = ""
    for el in elements:
        c = el["counts"]
        miss_cls = "badge-red" if el["missing"] else "badge-green"
        sum_rows += (
            f'<tr><td>{_esc(el["title"])}</td>'
            f'<td>{el["total"]}</td>'
            f'<td style="color:#00b894">{el["restored"]}</td>'
            f'<td><span class="badge {miss_cls}">{el["missing"]}</span></td>'
            f'<td>{c.get("created", 0)}</td>'
            f'<td>{c.get("exists", 0)}</td>'
            f'<td style="color:#e94560">{c.get("failed", 0)}</td>'
            f'<td style="color:#fdcb6e">{c.get("skipped", 0)}</td>'
            f'<td style="color:#fdcb6e">{c.get("manual", 0)}</td>'
            f'<td style="color:#e94560">{c.get("not attempted", 0)}</td>'
            f'<td style="color:#74b9ff">{el["info"]}</td>'
            f'</tr>')
    summary_panel = f"""<div class="panel active" id="p-summary">
      {info}
      <h2 class="sec">Per-element reconciliation</h2>
      <p class="hint">"In backup" is every item this scope actually owned.
        Anything that is not <b>created</b> or <b>already existed</b> is
        <b>not on the destination</b> — open that element's tab for the exact
        item names and the reason. <b>Inherited / empty</b> is counted
        separately: those items belong to another scope (and are restored
        there) or the backup simply held none.</p>
      <table><thead><tr>
        <th>Element</th><th>In backup</th><th>On destination</th>
        <th>Missing</th><th>Created</th><th>Existed</th><th>Failed</th>
        <th>Skipped</th><th>Manual</th><th>Not attempted</th>
        <th>Inherited / empty</th>
      </tr></thead><tbody>{sum_rows or '<tr><td colspan="11">No items recorded.</td></tr>'}</tbody></table>
    </div>"""

    # ── One panel per element ──
    panels = [summary_panel]
    for i, el in enumerate(elements):
        rows_html = ""
        for r in el["rows"]:
            st = str(r.get("status") or "")
            cls = _GAP_STATUS_CLASS.get(st, "badge-blue")
            rows_html += (
                f'<tr>'
                f'<td style="color:#aaa">{_esc(r.get("node"))}</td>'
                f'<td style="color:#888">{_esc(r.get("scope"))}</td>'
                f'<td class="wrap" style="color:#fff; '
                f'font-family:Consolas,monospace; font-size:12px;">'
                f'{_esc(r.get("item"))}</td>'
                f'<td style="color:#888">{_esc(r.get("kind"))}</td>'
                f'<td><span class="badge {cls}">{_esc(st)}</span></td>'
                f'<td class="err">{_esc(r.get("reason"))}</td>'
                f'</tr>')
        head = (f'<h2 class="sec">{_esc(el["title"])} — '
                f'{el["restored"]} of {el["total"]} on destination, '
                f'<span style="color:'
                f'{"#e94560" if el["missing"] else "#00b894"}">'
                f'{el["missing"]} missing</span></h2>')
        panels.append(
            f'<div class="panel" id="p-{i}">{head}'
            f'<table><thead><tr><th>Scope Path</th><th>Level</th>'
            f'<th>Item</th><th>Type</th><th>Status</th>'
            f'<th>Reason / Error</th></tr></thead>'
            f'<tbody>{rows_html}</tbody></table></div>')

    title = meta.get("customer") or meta.get("dest_console") or ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Migration Gap Report — S1 Command Center</title>
<style>{_CSS}{_GAP_CSS}</style></head><body>
<div class="header">
  <h1>🧩 Migration Gap Report</h1>
  <div class="subtitle">Exactly what was restored and what was not{
      f' &bull; {_esc(title)}' if title else ''}</div>
  <div class="meta">Generated {now[:19].replace('T', ' ')} &bull;
    {tot.get('items', 0)} items &bull; {tot.get('missing', 0)} not migrated</div>
</div>
{stats}
{tabs_html}
{''.join(panels)}
<div class="footer">S1 Command Center &bull; Made by Ran Jacobi</div>
<script>{_GAP_JS}</script>
</body></html>"""


_GAP_SHEET_BAD = re.compile(r"[\[\]:*?/\\]")


def _sheet_name(title: str, used: set) -> str:
    name = _GAP_SHEET_BAD.sub("-", str(title or "Sheet")).strip() or "Sheet"
    name = name[:31]
    base, n = name, 2
    while name.lower() in used:
        suffix = f" ({n})"
        name = base[:31 - len(suffix)] + suffix
        n += 1
    used.add(name.lower())
    return name


def generate_gap_excel(path: str, report: dict):
    """Write the gap report as a workbook: Summary + one sheet per element."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    report = report or {}
    meta = report.get("meta", {}) or {}
    elements = report.get("elements", []) or []
    tot = report.get("totals", {}) or {}

    ink = "1A1A2E"
    head_fill = PatternFill("solid", start_color=ink, end_color=ink)
    head_font = Font(name=_XL_FONT, size=10, bold=True, color="FFFFFF")
    body_font = Font(name=_XL_FONT, size=10, color="2C2C3A")
    row_border = Border(bottom=Side(style="thin", color="E3E3EC"))
    status_style = {
        "created": ("E3F7EC", "1B7F4F"),
        "exists": ("E2F0FD", "13599C"),
        "failed": ("FDEAE7", "B02020"),
        "skipped": ("FFF6DC", "9C6F00"),
        "manual": ("FFF0DC", "A85B00"),
        "not attempted": ("FDEAE7", "B02020"),
        "inherited": ("EFEFF4", "55556A"),
        "empty": ("EFEFF4", "55556A"),
    }

    wb = Workbook()
    s = wb.active
    s.title = "Summary"
    s.sheet_view.showGridLines = False
    for col, width in (("A", 3), ("B", 34), ("C", 12), ("D", 15), ("E", 11),
                       ("F", 11), ("G", 11), ("H", 11), ("I", 11), ("J", 15),
                       ("K", 15), ("L", 17)):
        s.column_dimensions[col].width = width

    t = s.cell(row=2, column=2, value="Migration Gap Report")
    t.font = Font(name=_XL_FONT, size=18, bold=True, color=ink)
    sub = s.cell(row=3, column=2,
                 value="What was restored to the destination — and what was not")
    sub.font = Font(name=_XL_FONT, size=10, color="8A8A9A")

    r = 5
    for label, value in (
        ("Source console", meta.get("source_url") or "—"),
        ("Destination console", meta.get("dest_url") or "—"),
        ("Generated", (report.get("generatedAt") or "")[:19].replace("T", " ")),
        ("Duration", meta.get("elapsed") or "—"),
        ("Items tracked", tot.get("items", 0)),
        ("On destination", tot.get("restored", 0)),
        ("NOT migrated", tot.get("missing", 0)),
    ):
        lc = s.cell(row=r, column=2, value=label)
        lc.font = Font(name=_XL_FONT, size=10, color="8A8A9A")
        vc = s.cell(row=r, column=3, value=value)
        vc.font = Font(name=_XL_FONT, size=10, bold=True,
                       color="B02020" if (label == "NOT migrated"
                                          and tot.get("missing", 0)) else ink)
        r += 1

    r += 1
    headers = ["Element", "In backup", "On destination", "Missing", "Created",
               "Existed", "Failed", "Skipped", "Manual", "Not attempted",
               "Inherited / empty"]
    for j, h in enumerate(headers, 2):
        c = s.cell(row=r, column=j, value=h)
        c.font = head_font
        c.fill = head_fill
        c.alignment = Alignment(horizontal="left", wrap_text=True)
    r += 1
    for el in elements:
        c = el["counts"]
        vals = [el["title"], el["total"], el["restored"], el["missing"],
                c.get("created", 0), c.get("exists", 0), c.get("failed", 0),
                c.get("skipped", 0), c.get("manual", 0),
                c.get("not attempted", 0), el["info"]]
        for j, v in enumerate(vals, 2):
            cell = s.cell(row=r, column=j, value=_xl_safe(v))
            cell.font = body_font
            cell.border = row_border
            if j == 5 and el["missing"]:
                cell.font = Font(name=_XL_FONT, size=10, bold=True,
                                 color="B02020")
                cell.fill = PatternFill("solid", start_color="FDEAE7",
                                        end_color="FDEAE7")
        r += 1

    # ── One sheet per element ──
    cols = [("Scope Path", "node", 40), ("Level", "scope", 10),
            ("Item", "item", 52), ("Type", "kind", 16),
            ("Status", "status", 14), ("Reason / Error", "reason", 70)]
    used = {"summary"}
    for el in elements:
        ws = wb.create_sheet(_sheet_name(el["title"], used))
        ws.sheet_view.showGridLines = False
        last = get_column_letter(len(cols))
        ws.merge_cells(f"A1:{last}1")
        tc = ws.cell(row=1, column=1,
                     value=f"{el['title']} — {el['restored']} of "
                           f"{el['total']} on destination, "
                           f"{el['missing']} missing")
        tc.font = Font(name=_XL_FONT, size=13, bold=True,
                       color="B02020" if el["missing"] else ink)
        for j, (title, _k, width) in enumerate(cols, 1):
            c = ws.cell(row=3, column=j, value=title)
            c.font = head_font
            c.fill = head_fill
            c.alignment = Alignment(horizontal="left", vertical="center")
            ws.column_dimensions[get_column_letter(j)].width = width
        for i, row in enumerate(el["rows"]):
            excel_row = i + 4
            for j, (_t, key, _w) in enumerate(cols, 1):
                c = ws.cell(row=excel_row, column=j,
                            value=_xl_safe(row.get(key, "")))
                c.font = body_font
                c.border = row_border
                c.alignment = Alignment(horizontal="left", vertical="top",
                                        wrap_text=(key == "reason"))
                if key == "status":
                    sty = status_style.get(str(row.get("status") or ""))
                    if sty:
                        c.fill = PatternFill("solid", start_color=sty[0],
                                             end_color=sty[0])
                        c.font = Font(name=_XL_FONT, size=10, bold=True,
                                      color=sty[1])
        ws.freeze_panes = "A4"
        if el["rows"]:
            ws.auto_filter.ref = f"A3:{last}{3 + len(el['rows'])}"

    wb.save(path)


def gap_report_rows(report: dict) -> list:
    """Flatten a gap report back to plain rows (for the JSON export)."""
    out = []
    for el in (report or {}).get("elements", []):
        for r in el.get("rows", []):
            out.append({"element": el["title"], **r})
    return out


# (header, row key)
GAP_CSV_COLUMNS = [
    ("Element", "element"),
    ("Scope Path", "node"),
    ("Level", "scope"),
    ("Item", "item"),
    ("Type", "kind"),
    ("Status", "status"),
    ("Restored", "restored"),
    ("Reason / Error", "reason"),
]


def gap_csv_rows(report: dict) -> list:
    """Flat rows for the CSV export.

    A CSV has no tabs, so the element becomes a column (filter/pivot on it)
    and the rows keep the tab order: element by element, everything that did
    NOT reach the destination first. `Restored` is a plain yes/no/n-a so the
    sheet can be filtered without knowing the status vocabulary."""
    out = []
    for el in (report or {}).get("elements", []):
        for r in el.get("rows", []):
            status = str(r.get("status") or "")
            if status in GAP_RESTORED_STATUSES:
                restored = "yes"
            elif status in GAP_MISSING_STATUSES:
                restored = "NO"
            else:
                restored = "n/a"
            out.append({
                "element": el["title"],
                "node": r.get("node", ""),
                "scope": r.get("scope", ""),
                "item": r.get("item", ""),
                "kind": r.get("kind", ""),
                "status": status,
                "restored": restored,
                "reason": r.get("reason", ""),
            })
    return out


def write_gap_csv(path: str, report: dict) -> int:
    """Write the gap report as one flat CSV. Returns the row count."""
    rows = gap_csv_rows(report)
    # utf-8-sig: Excel on Windows reads a plain utf-8 CSV as cp1252 and
    # mangles every non-ASCII rule name; the BOM makes it open correctly.
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([h for h, _k in GAP_CSV_COLUMNS])
        for r in rows:
            w.writerow([r.get(k, "") for _h, k in GAP_CSV_COLUMNS])
    return len(rows)


def export_gap_csv(report: dict, default_name: str = ""):
    """Save dialog + flat CSV of every item the last restore touched."""
    if not (report or {}).get("elements"):
        messagebox.showwarning(
            "Nothing to Report",
            "No per-item restore data yet — run a restore first.")
        return None
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    path = filedialog.asksaveasfilename(
        title="Export Migration Gap Report (CSV)",
        initialfile=default_name or f"s1-migration-gaps-{ts}",
        defaultextension=".csv",
        filetypes=[("CSV (comma separated)", "*.csv")])
    if not path:
        return None
    try:
        n = write_gap_csv(path, report)
        tot = report.get("totals", {})
        cli_log(f"Gap report CSV exported → {os.path.basename(path)} "
                f"({n} row(s), {tot.get('missing', 0)} not migrated)",
                "success")
        cli_log(f"File saved to: {path}", "info")
        return path
    except Exception as e:
        cli_log(f"Gap report CSV export error: {e}", "error")
        messagebox.showerror("Export Error", str(e))
        return None


def export_gap_report(report: dict, default_name: str = ""):
    """Save dialog + write the gap report as Excel (tabs), HTML (tabs) or
    JSON. Returns the path written, or None if the user cancelled."""
    if not (report or {}).get("elements"):
        messagebox.showwarning(
            "Nothing to Report",
            "No per-item restore data yet — run a restore first.")
        return None
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    path = filedialog.asksaveasfilename(
        title="Export Migration Gap Report",
        initialfile=default_name or f"s1-migration-gaps-{ts}",
        defaultextension=".xlsx",
        filetypes=[
            ("Excel Workbook (one tab per element)", "*.xlsx"),
            ("HTML Report (tabbed)", "*.html"),
            ("CSV (flat, one row per item)", "*.csv"),
            ("JSON Data", "*.json"),
        ])
    if not path:
        return None
    try:
        ext = os.path.splitext(path)[1].lower()
        if ext == ".xlsx":
            generate_gap_excel(path, report)
        elif ext == ".csv":
            write_gap_csv(path, report)
        elif ext == ".json":
            with open(path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, default=str)
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(generate_gap_html(report))
        tot = report.get("totals", {})
        cli_log(f"Gap report exported → {os.path.basename(path)} "
                f"({tot.get('missing', 0)} item(s) not migrated)", "success")
        cli_log(f"File saved to: {path}", "info")
        return path
    except Exception as e:
        cli_log(f"Gap report export error: {e}", "error")
        messagebox.showerror("Export Error", str(e))
        return None


# ═══════════════════════════════════════════════════════════════════════
#  Unified export dialog
# ═══════════════════════════════════════════════════════════════════════

def export_report(title: str, columns: list[str], rows: list[dict],
                  stats: Optional[list[dict]] = None,
                  subtitle: str = ""):
    """Show save dialog and export as HTML or Excel based on user choice."""
    if not rows:
        messagebox.showwarning("No Data", "Nothing to export — load data first.")
        return

    ts = datetime.now().strftime("%Y%m%d-%H%M")
    safe_title = title.lower().replace(" ", "-").replace("&", "and")
    path = filedialog.asksaveasfilename(
        title=f"Export {title}",
        initialfile=f"s1-{safe_title}-{ts}",
        defaultextension=".html",
        filetypes=[
            ("HTML Report", "*.html"),
            ("Excel Workbook", "*.xlsx"),
            ("JSON Data", "*.json"),
        ],
    )
    if not path:
        return

    try:
        ext = os.path.splitext(path)[1].lower()
        if ext == ".xlsx":
            generate_excel(path, title, columns, rows)
        elif ext == ".json":
            # encoding is explicit everywhere: Python defaults to the
            # platform encoding, which is cp1252 on Windows, so a single
            # non-ASCII character in a rule name or query killed the export
            # ("'charmap' codec can't encode…") — and where it didn't, the
            # bytes contradicted the utf-8 the HTML declares.
            with open(path, "w", encoding="utf-8") as f:
                json.dump(rows, f, indent=2, default=str)
        else:
            html = generate_html(title, columns, rows, stats=stats,
                                 subtitle=subtitle)
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)

        cli_log(f"Exported {len(rows)} records → {os.path.basename(path)}",
                "success")
        cli_log(f"File saved to: {path}", "info")
    except Exception as e:
        cli_log(f"Export error: {e}", "error")
        messagebox.showerror("Export Error", str(e))


# ═══════════════════════════════════════════════════════════════════════
#  Rich migration report (agent runs, status) — one structured dict in,
#  a self-contained HTML document / Excel / CSV / JSON out.
# ═══════════════════════════════════════════════════════════════════════
#
# The caller hands a plain dict so the whole report is testable without a
# console or a window:
#   {title, icon, subtitle, meta_line,
#    info:    [(label, value), ...],          # the connection/scope box
#    stats:   [{label, value, class}],        # class in "", accent, warn,
#                                             #   blue, muted
#    note:    {text, kind} | None,            # kind in info|warn|danger
#    sections:[{title, icon, color, columns, rows, badge_cols, empty}],
#    log:     [line, ...] | None,
#    flat:    {columns, rows}}                 # feeds Excel/CSV/JSON

def _stat_cards(stats) -> str:
    if not stats:
        return ""
    cards = "".join(
        f'<div class="stat-card"><div class="label">{_esc(s.get("label", ""))}'
        f'</div><div class="value {s.get("class", "")}">'
        f'{_esc(s.get("value", ""))}</div></div>'
        for s in stats)
    return f'<div class="stats">{cards}</div>'


def _section_html(sec: dict, idx: int = 0) -> str:
    cols = sec.get("columns", [])
    rows = sec.get("rows", [])
    badge = set(sec.get("badge_cols", []))
    head = (f'<h2 class="rep-h2" style="color:{sec.get("color", "#fff")}">'
            f'{(sec.get("icon", "") + " ") if sec.get("icon") else ""}'
            f'{_esc(sec.get("title", ""))} '
            f'<span style="color:#666; font-weight:400; font-size:14px;">'
            f'({len(rows)})</span></h2>')
    if not rows:
        return head + (f'<p style="color:#666; font-size:13px; '
                       f'margin-bottom:8px;">'
                       f'{_esc(sec.get("empty", "Nothing here."))}</p>')
    tid = f"tbl-{idx}"
    th = "".join(f"<th>{_esc(c)}</th>" for c in cols)
    body = []
    for r in rows:
        tds = ""
        for c in cols:
            val = r.get(c, "")
            tds += (f"<td>{_badge(_esc(val))}</td>" if c in badge
                    else f"<td>{_esc(_cell(val))}</td>")
        body.append(f"<tr>{tds}</tr>")
    ncols = len(cols) or 1
    tools = (f'<div class="tbl-tools">'
             f'<input class="tbl-search" data-for="{tid}" '
             f'placeholder="Filter\u2026" aria-label="Filter rows">'
             f'<span class="tbl-count" id="cnt-{tid}"></span></div>')
    nomatch = (f'<tr class="no-match" style="display:none">'
               f'<td colspan="{ncols}">No matching rows.</td></tr>')
    return head + tools + (
        f'<table class="data-table" id="{tid}">'
        f'<thead><tr>{th}</tr></thead>'
        f'<tbody>{"".join(body)}{nomatch}</tbody></table>')


def generate_migration_html(report: dict) -> str:
    """Render a structured migration report as a self-contained HTML page."""
    report = report or {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    icon = report.get("icon", "")
    title = _esc(report.get("title", "Migration Report"))
    subtitle = _esc(report.get("subtitle", "S1 Command Center Report"))
    meta_line = _esc(report.get("meta_line", f"Generated {now}"))

    info = report.get("info") or []
    info_html = ""
    if info:
        rows = "".join(
            f'<tr><td class="k">{_esc(k)}</td>'
            f'<td class="v">{_esc(v)}</td></tr>' for k, v in info)
        info_html = f'<div class="infobox"><table>{rows}</table></div>'

    note = report.get("note") or {}
    note_html = ""
    if note.get("text"):
        note_html = (f'<div class="banner {note.get("kind", "info")}">'
                     f'{_esc(note["text"])}</div>')

    sections_html = "\n".join(
        _section_html(s, i)
        for i, s in enumerate(report.get("sections", [])))

    log = report.get("log")
    log_html = ""
    if log:
        lines = "".join(
            f'<div style="font-family:Consolas,monospace; font-size:11px; '
            f'color:#888; padding:1px 0;">{_esc(l)}</div>' for l in log)
        log_html = (
            f'<details style="margin-top:28px;"><summary style="color:#888; '
            f'cursor:pointer; font-size:14px; margin-bottom:8px;">Full log '
            f'({len(log)} lines)</summary><div style="background:#111; '
            f'border-radius:8px; padding:16px; max-height:600px; '
            f'overflow-y:auto;">{lines}</div></details>')

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{title} — S1 Command Center Report</title>
<style>{_CSS}</style></head><body>
<div class="header">
  <h1>{(icon + ' ') if icon else ''}{title}</h1>
  <div class="subtitle">{subtitle}</div>
  <div class="meta">{meta_line}</div>
</div>
{_stat_cards(report.get('stats'))}
{info_html}
{note_html}
{sections_html}
{log_html}
<div class="footer">S1 Command Center &bull; Made by Ran Jacobi &bull; Generated {now}</div>
{_REPORT_JS}
</body></html>"""


def _write_flat_csv(path: str, columns: list, rows: list) -> int:
    """One flat CSV of `rows`. utf-8-sig so Excel-on-Windows keeps non-ASCII."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for r in rows:
            w.writerow([r.get(c, "") for c in columns])
    return len(rows)


def _open_path(path: str):
    """Open a saved file with the OS default handler."""
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except Exception as e:
        cli_log(f"Could not open the file: {e}", "warning")


def export_agent_report(report: dict, default_name: str = ""):
    """Save dialog + write a migration report as a rich HTML document, Excel
    workbook, flat CSV or JSON. Returns the path written, or None."""
    report = report or {}
    flat = report.get("flat") or {}
    columns = flat.get("columns") or []
    rows = flat.get("rows") or []
    if not rows and not report.get("sections"):
        messagebox.showwarning(
            "Nothing to Export",
            "Run the report first — there is no data yet.")
        return None
    ts = datetime.now().strftime("%Y%m%d-%H%M")
    path = filedialog.asksaveasfilename(
        title=f"Export {report.get('title', 'Report')}",
        initialfile=default_name or f"s1-agent-report-{ts}",
        defaultextension=".html",
        filetypes=[
            ("HTML Report", "*.html"),
            ("Excel Workbook", "*.xlsx"),
            ("CSV (flat)", "*.csv"),
            ("JSON Data", "*.json"),
        ])
    if not path:
        return None
    try:
        ext = os.path.splitext(path)[1].lower()
        if ext == ".xlsx":
            generate_excel(path, report.get("title", "Report"), columns, rows)
        elif ext == ".csv":
            _write_flat_csv(path, columns, rows)
        elif ext == ".json":
            with open(path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, default=str)
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(generate_migration_html(report))
        cli_log(f"Report exported → {os.path.basename(path)} "
                f"({len(rows)} row(s))", "success")
        cli_log(f"File saved to: {path}", "info")
        if messagebox.askyesno(
                "Open report?",
                f"Saved to:\n{path}\n\nOpen it now?"):
            _open_path(path)
        return path
    except Exception as e:
        cli_log(f"Report export error: {e}", "error")
        messagebox.showerror("Export Error", str(e))
        return None
